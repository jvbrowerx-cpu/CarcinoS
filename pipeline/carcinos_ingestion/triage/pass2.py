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
  A = Phase III RCT, high-quality meta-analysis of Phase III RCTs, major guideline update
  B = Phase II randomized, prospective cohort with strong methodology
  C = Single-arm Phase II, retrospective with comparator, early diagnostic study
  D = Preclinical, case report, opinion, editorial

─────────────────────────────────────────────────────────────────────────────
IMPACT SCORING (additive)
─────────────────────────────────────────────────────────────────────────────
  +40 OS benefit in a randomized trial
  +35 OS benefit in hard-to-treat cancer (pancreatic, SCLC, GBM, mesothelioma)
  +30 EFS/DFS benefit in early-stage or adjuvant setting with clear practice-change
  +30 New FDA approval or guideline change (source must explicitly state it)
  +25 Strong PFS benefit with clear adoption potential in metastatic setting
  +25 Noninferiority with meaningful toxicity/QoL improvement or major de-escalation
  +20 First positive Phase III in indication with no prior standard (rare mutations, orphan)
  +20 Biomarker-defined population, large effect (HR < 0.65 or ORR > 60%)
  +15 Meaningful improvement in second-line or later with few options
  −10 Surrogate-only endpoint, modest magnitude (HR 0.80–0.90)
  −15 Single-arm without comparator
  −20 Observational confounding likely
  −25 Post-hoc or exploratory subgroup only (not pre-specified primary analysis)

Calibration:
  Phase III with OS benefit → score ≥ 70
  Phase III OS in hard-to-treat cancer → score ≥ 80
  FDA approval or guideline update always adds +30 on top of trial score
  Reviews and educational summaries of established standards → score ≤ 40

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
    Map (impact, evidence, llm hint) → A / B / C / NOISE.

    Returns one of: 'A' (Practice Impacting), 'B' (Incremental),
    'C' (Horizon), 'NOISE' (do not surface).

    Evidence-adjusted thresholds:
      Evidence A (Phase III RCT, high-quality meta-analysis, major guideline):
        >= 70 → Practice Impacting  (lower bar: Phase III OS benefit is clinically
                                     impacting even when OS is not yet fully mature)
        50–69 → Incremental
      Evidence B (Phase II randomized, strong prospective cohort):
        >= 80 → Practice Impacting
        60–79 → Incremental
      Evidence C (single-arm, retrospective):
        >= 70 → Incremental
        35–69 → Horizon
      Evidence D or impact < 35 → NOISE
    """
    e = evidence.upper()

    # Evidence A: Phase III RCTs and high-quality meta-analyses get a lower
    # Practice Impacting bar. A Phase III trial showing OS benefit (even immature)
    # is clinically practice-changing regardless of the exact impact score.
    if e == "A":
        if impact >= 70:
            return "A"
        if impact >= 50:
            return "B"
        if impact >= 35:
            return "C"
        return "NOISE"

    # Evidence B
    if e == "B":
        if impact >= 80:
            return "A"
        if impact >= 60:
            return "B"
        if impact >= 35:
            return "C"
        return "NOISE"

    # Evidence C
    if e == "C":
        if impact >= 70:
            return "B"
        if impact >= 35:
            return "C"
        return "NOISE"

    # Evidence D or unrecognized → NOISE
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
