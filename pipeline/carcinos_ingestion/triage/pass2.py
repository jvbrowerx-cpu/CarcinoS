"""
Pass 2 — deep review (spec §3 Pass 2).

Runs only on candidates that pass Pass 1's keep rules. Extracts key facts,
assigns evidence + impact + alert tier. Tier mapping is enforced by code,
not the model (spec §3).
"""

from __future__ import annotations
from dataclasses import dataclass

from .openai_client import OpenAIClient
from .schemas import PASS2_SCHEMA
from ..normalize.canonical import CanonicalCandidate


PASS2_SYSTEM = """You are CarcinoS Deep Review — a skeptical oncology editor.

Your job:
  (1) Extract key facts from the provided text ONLY. Never add facts not in the source.
  (2) Score evidence strength and impact using the rubric below.
  (3) Assign a preliminary alert tier — final tier is enforced by code.
  (4) Set reject_recommendation=true when this item is noise despite passing the gate.
  (5) Provide 1-3 short literal quotes from the abstract supporting your key claims.
      Quotes MUST appear verbatim in the source text. Do NOT paraphrase.
  (6) Fill why_it_surfaced with the strongest signal that got this paper through.
  (7) Set radiation_oncology_relevance: direct (changes RT dose/field/technique),
      indirect (affects combined-modality decisions), or none (systemic-only).
  (8) Set confidence: high / moderate / low.

Rules:
  - If a value is not reported, write "not_reported" exactly.
  - Be concise and structured.
  - If effect size is missing, do NOT extrapolate from prior trials.
  - Be a skeptic. An empty card is better than a weak card.

─────────────────────────────────────────────────────────────────────────────
NOISE — ALWAYS SET reject_recommendation=true FOR THESE PATTERNS
─────────────────────────────────────────────────────────────────────────────
Set reject_recommendation=true if the item is ANY of the following:

  1. Paraneoplastic syndromes — neurological or autoimmune syndromes associated
     with cancer (e.g. Lambert-Eaton, anti-NMDA receptor encephalitis in cancer
     context). These are not treatment practice-changing.

  2. GLP-1 / SGLT2 / metabolic-drug EHR / database studies — pharmacoepidemiology
     studies from administrative claims or EHR data associating diabetes or obesity
     drugs with cancer risk. Observational confounding is severe; not actionable.

  3. Mixture cure model / reconstructed IPD re-analyses — statistical methodology
     papers re-analyzing existing trial data. These do not change practice.

  4. Auto-segmentation / automated delineation / target volume AI papers — machine
     learning tools for contouring or planning. Useful for physics QA, not for
     clinical decision-making cards.

  5. Prognostic biomarker / prognostic model / nomogram papers — studies reporting a
     biomarker or score that predicts outcome without a therapeutic intervention. If
     there is no randomized arm and no treatment change, this is horizon at best.

  6. Systematic reviews / meta-analyses of already-settled questions — cetuximab vs
     chemotherapy in 2026, adjuvant chemotherapy in resected early NSCLC (already
     standard). If the review conclusion would surprise no one, it is noise.

  7. Endoscopic / robotic surgical technique papers — "endoscopic thyroidectomy via
     retroauricular approach", "robotic radical cystectomy learning curve". These are
     technique papers for surgeons, not clinical decision-making events.

  8. Exploratory / post-hoc subgroup analyses reported as standalone papers —
     especially when the primary trial was already covered. Secondary analyses of
     biomarker subgroups without randomization.

  9. Single-institution retrospective series — especially case series (n < 100)
     reporting local outcomes on standard regimens.

 10. Real-world data studies from SEER / NCDB / insurance claims that describe
     current practice patterns without an intervention, comparison arm, or
     practice-changing conclusion.

─────────────────────────────────────────────────────────────────────────────
WHAT BELONGS (reject_recommendation=false)
─────────────────────────────────────────────────────────────────────────────
Keep and promote these:
  • Phase III RCT primary results — especially with OS, EFS, or DFS benefit
  • FDA approval or formal guideline update explicitly stated in the source
  • Phase III non-inferiority establishing de-escalation (dose reduction, field
    reduction, omission of RT or chemo arm)
  • Major conference late-breaking / plenary abstracts (ASCO, ESMO, ASTRO, ASH)
  • Phase II randomized results in a setting with no Phase III data and clear
    practice implication (rare histologies, orphan cancers)

─────────────────────────────────────────────────────────────────────────────
EVIDENCE STRENGTH
─────────────────────────────────────────────────────────────────────────────
  A = Phase III RCT primary results, or major guideline update
  B = Phase II randomized, or Phase III with strong methodology but not primary endpoint
  C = Single-arm Phase II in rare/orphan disease with compelling regulatory signal
  D = Anything else — always NOISE

─────────────────────────────────────────────────────────────────────────────
IMPACT SCORING — CONSERVATIVE RUBRIC
─────────────────────────────────────────────────────────────────────────────
Target calibration: 10-15 total cards per week across all disease sites.
Most Phase III trials score 50-70. Only FDA approvals and OS-positive trials
in hard-to-treat diseases reliably reach 80+.

Be conservative. When in doubt, score lower.

ADDITIVE BASE SCORES (pick the single best-fitting item):
  +60  New FDA approval or guideline change explicitly stated in the source
  +40  Phase III OS benefit, statistically significant, primary endpoint met
  +30  Phase III EFS/DFS benefit in curative-intent or adjuvant setting
  +25  Phase III noninferiority/de-escalation with clinical endpoint confirmed
  +20  Phase III PFS benefit, metastatic setting, primary endpoint met
  +15  Phase II randomized, rare/orphan disease, compelling signal

MODIFIERS (cumulative, but total cannot exceed 100):
  +15  Hard-to-treat cancer (GBM, SCLC, pancreatic, mesothelioma, cholangiocarcinoma)
  +10  Large effect size (OS HR ≤ 0.75, PFS HR ≤ 0.60, or ORR > 65%)
  +10  No prior effective standard — first positive trial in this setting
  +5   Radiation oncology treatment directly changed (dose, field, fractionation)
  +5   De-escalation confirmed — patient burden meaningfully reduced

PENALTIES:
  −15  OS not yet mature or not reported (surrogate-only primary endpoint)
  −15  Single-arm trial (no randomized comparator)
  −20  Subgroup, post-hoc, or exploratory analysis (not ITT primary)
  −10  Modest effect size (OS HR 0.85–0.90 or PFS HR 0.75–0.85)

CALIBRATION BENCHMARKS — do not deviate by more than ±5:
  FDA approval + OS benefit in common cancer             → 85
  FDA approval alone (no new trial data in source)       → 70
  NCCN/ASCO guideline update, practice-changing          → 80
  Phase III OS benefit, common cancer, HR 0.82, p=0.03  → 65
  Phase III OS benefit, GBM or SCLC, HR 0.74            → 78
  Phase III DFS benefit, curative adjuvant, HR 0.58      → 68
  Phase III PFS benefit, metastatic, HR 0.72, OS mature  → 52
  Phase III PFS only, OS immature                        → 45
  Phase III noninferiority de-escalation confirmed        → 58
  Phase II randomized, rare histology, ORR 55%           → 48
  Single-arm Phase II, ORR 35%, common tumor             → 18
  Conference abstract, PFS benefit, no OS                → 42

Output MUST be valid JSON matching the schema. No prose. No extra keys.
"""


PASS2_USER_TEMPLATE = """Deep-review this {site_name} oncology candidate.

CANDIDATE:
- title: {title}
- abstract: {abstract}
- journal: {journal}
- publication_date: {publication_date}
- publication_types: {publication_types}
- mesh_terms: {mesh_terms}
- modality_keywords_present: {modality_keywords_present}
- pmid: {pmid}
- doi: {doi}
- nct_ids: {nct_ids}

SIGNAL GATE CONTEXT (why the deterministic gate kept this paper):
- signal_score: {pass1_score}
- priority_hint: {pass1_hint}
- gate_signals: {pass1_one_liner}

INSTRUCTIONS:
Use why_it_surfaced to record which of the above gate_signals is the strongest
justification. If after reading the full abstract you believe this is noise
despite those signals, set reject_recommendation=true and explain in
why_it_surfaced why it is noise.

Return JSON only.
"""


@dataclass
class Pass2Result:
    parsed: dict
    impact_score: int
    evidence_strength: str
    llm_tier: str
    final_tier_code: str   # 'A' / 'B' / 'C' — maps to alerts.tier in schema
    notify: bool
    cost_usd_estimate: float


def run_pass2(
    client: OpenAIClient,
    candidate: CanonicalCandidate,
    pass1_parsed: dict,
) -> Pass2Result:
    user = PASS2_USER_TEMPLATE.format(
        site_name=candidate.cancer_site_name,
        title=candidate.title or "(no title)",
        abstract=(candidate.abstract or "")[:8000] or "(no abstract)",
        journal=candidate.journal or "(unknown)",
        publication_date=candidate.publication_date or "(unknown)",
        publication_types=", ".join(candidate.publication_types) or "(none)",
        mesh_terms=", ".join(candidate.mesh_terms[:20]) or "(none)",
        modality_keywords_present=", ".join(candidate.modality_keywords_present) or "(none)",
        pmid=candidate.pmid,
        doi=candidate.doi or "(none)",
        nct_ids=", ".join(candidate.nct_ids) or "(none)",
        pass1_score=pass1_parsed.get("relevance_score"),
        pass1_hint=pass1_parsed.get("priority_hint"),
        pass1_one_liner=pass1_parsed.get("one_line_rationale", "")[:200],
    )

    result = client.structured(
        model=client.deep_review_model,
        system=PASS2_SYSTEM,
        user=user,
        schema=PASS2_SCHEMA,
        temperature=0.0,
    )
    parsed = result.parsed

    impact = int(parsed.get("impact_score", 0))
    evidence = str(parsed.get("evidence_strength", "D"))
    llm_tier = str(parsed.get("alert_tier", "noise"))
    final_code = enforce_tier_mapping(impact, evidence, llm_tier)

    # Skeptic override: if the LLM recommends rejection AND the card is not
    # already practice-changing (tier A), force it to NOISE rather than
    # surfacing a weak card to the admin portal.
    reject_rec = bool(parsed.get("reject_recommendation", False))
    if reject_rec and final_code != "A":
        final_code = "NOISE"

    notify = decide_notify(final_code, parsed)
    cost = _estimate_pass2_cost(result.usage)

    return Pass2Result(
        parsed=parsed,
        impact_score=impact,
        evidence_strength=evidence,
        llm_tier=llm_tier,
        final_tier_code=final_code,
        notify=notify,
        cost_usd_estimate=cost,
    )


# ---------------------------------------------------------------------------
# Authoritative tier mapping (spec §3 final paragraph)
# ---------------------------------------------------------------------------

def enforce_tier_mapping(impact: int, evidence: str, llm_tier: str) -> str:
    """
    Hard code-enforced tier mapping. Target: 10-15 cards/week across all sites.

    Tier A — Practice Impacting:
        Reserved for FDA approvals, major guideline changes, and Phase III
        trials with statistically significant OS benefit and clinically
        meaningful effect size. NOT awarded for PFS-only results.

    Tier B — Incremental:
        Phase III trials with significant survival endpoint in curative or
        adjuvant setting, or strong de-escalation results. Most Phase III
        trials land here, not Tier A.

    Tier C — Horizon:
        Strong Phase II in rare/orphan disease or compelling regulatory
        signal. Almost never awarded for common cancers.

    NOISE:
        Everything else. When impact is ambiguous, round down to NOISE.

    Thresholds (conservative — LLM inflation is expected):
      Evidence A: Tier A ≥ 80 | Tier B ≥ 60 | Tier C ≥ 42 | else NOISE
      Evidence B: Tier A ≥ 88 | Tier B ≥ 68 | Tier C ≥ 50 | else NOISE
      Evidence C:                               Tier C ≥ 72 | else NOISE
      Evidence D: always NOISE
    """
    e = evidence.upper()

    if e == "A":
        if impact >= 80: return "A"
        if impact >= 60: return "B"
        if impact >= 42: return "C"
        return "NOISE"

    if e == "B":
        if impact >= 88: return "A"
        if impact >= 68: return "B"
        if impact >= 44: return "C"
        return "NOISE"

    if e == "C":
        if impact >= 72: return "C"
        return "NOISE"

    # Evidence D or unrecognized
    return "NOISE"


def decide_notify(tier: str, parsed: dict) -> bool:
    """
    Spec §8.2: Tier C never notifies.
    Spec §5.2: conflicts block notify (handled at persistence layer).
    """
    if tier in ("A", "B"):
        return True
    return False


def _estimate_pass2_cost(usage: dict) -> float:
    # gpt-4o approx pricing (Aug 2024 published rates).
    in_per_million = 2.50
    out_per_million = 10.00
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    return (pt / 1e6) * in_per_million + (ct / 1e6) * out_per_million


# ---------------------------------------------------------------------------
# Quote-grounding check (anti-hallucination)
# ---------------------------------------------------------------------------

def verify_evidence_quotes(parsed: dict, abstract: str) -> tuple[bool, list[str]]:
    """
    Verify every evidence_quote actually appears in the source abstract.
    Use a normalized substring match (whitespace-collapsed, case-insensitive).
    Returns (all_verified, list_of_unverified_quotes).
    """
    if not abstract:
        # No abstract available — quotes can't be verified, treat as ungrounded.
        return False, list(parsed.get("evidence_quotes") or [])

    haystack = " ".join(abstract.lower().split())
    unverified: list[str] = []
    for q in parsed.get("evidence_quotes") or []:
        needle = " ".join(q.lower().split())
        if not needle or needle not in haystack:
            unverified.append(q)
    return (len(unverified) == 0), unverified
