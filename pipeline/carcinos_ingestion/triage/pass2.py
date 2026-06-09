"""
Pass 2 — deep review (spec §3 Pass 2).

Runs only on candidates that pass Gate 2 signal scoring. The LLM is used
ONLY for structured fact extraction — it never scores or assigns tiers.

Architecture:
  1. LLM extracts structured fields: study_phase, primary_endpoint_type,
     primary_endpoint_met, effect_direction, hr_value, p_value_significant,
     hard_to_treat, reject_recommendation, and narrative fields.
  2. compute_tier() in tier_logic.py converts those facts + qualifying_signal
     into a deterministic tier (A / B / C / NOISE). No LLM scoring involved.
  3. reject_recommendation=true is the LLM's one judgment call — it overrides
     the tier to NOISE for papers that passed the gate but are clearly noise.
"""

from __future__ import annotations
from dataclasses import dataclass

from .openai_client import OpenAIClient
from .schemas import PASS2_SCHEMA
from .tier_logic import compute_tier, tier_rationale
from ..normalize.canonical import CanonicalCandidate


PASS2_SYSTEM = """You are CarcinoS Deep Review — a clinical data extraction engine.

Your ONLY jobs are:
  (1) Extract key facts from the provided text. Never add facts not in the source.
  (2) Fill the structured extraction fields accurately (study_phase, endpoint type,
      whether the endpoint was met, effect direction, HR, p-value significance, etc.)
      Tier assignment is computed by code from these fields — do NOT score or assign tiers.
  (3) Set reject_recommendation=true when this item is noise despite passing the gate.
      This is your one judgment call. Everything else is factual extraction.
  (4) Provide 1-3 short literal quotes from the abstract supporting key claims.
      Quotes MUST appear verbatim in the source. Do NOT paraphrase.
  (5) Fill why_it_surfaced with the strongest signal that got this paper through.
  (6) Set radiation_oncology_relevance: direct (changes RT dose/field/technique),
      indirect (affects combined-modality decisions), or none (systemic-only).
  (7) Set confidence: high / moderate / low — your confidence this belongs in the portal.

Rules:
  - Extract only what is stated in the source. Never extrapolate.
  - If a value is not reported, write "not_reported" for text fields.
  - For primary_endpoint_met: use the pre-specified primary endpoint and its
    alpha threshold. If the abstract reports p=0.034 for the primary endpoint,
    primary_endpoint_met=true. If p=0.12, primary_endpoint_met=false.
  - For hr_value: report the numeric hazard ratio (e.g. 0.76). Use null if
    no HR is reported or if the primary endpoint is not a time-to-event outcome.
  - For p_value_significant: true if p < pre-specified alpha (typically 0.05).
  - For effect_direction: report the direction of the PRIMARY result, not secondary endpoints.
  - For hard_to_treat: true for GBM, SCLC, pancreatic, biliary/cholangiocarcinoma,
    mesothelioma, gastric, DIPG, or any cancer with expected OS < 12 months in this setting.

─────────────────────────────────────────────────────────────────────────────
STRUCTURED EXTRACTION — fill these fields accurately
─────────────────────────────────────────────────────────────────────────────

study_phase — select exactly one:
  phase3_rct          Primary results of a randomized Phase III trial
  phase2_rct          Phase II trial with a randomized comparator arm
  phase2_single_arm   Phase II trial, no comparator (single-arm)
  phase1              Dose-finding or safety study
  meta_analysis       Quantitative pooled analysis or IPD meta-analysis
  systematic_review   Qualitative systematic review (no quantitative pooling)
  guideline_update    Formal revision: NCCN, ASCO, ESMO, ASTRO, ASH
  fda_approval        FDA approval record
  observational       Cohort, registry, real-world, retrospective
  other_or_unclear

primary_endpoint_type — the PRE-SPECIFIED primary endpoint of the study:
  overall_survival / progression_free_survival / disease_free_survival /
  event_free_survival / objective_response_rate / non_inferiority /
  pathologic_response / locoregional_control / other / not_reported

primary_endpoint_met — boolean:
  true  = primary endpoint formally met at pre-defined significance threshold
  false = primary endpoint NOT met (negative trial or missed primary)

effect_direction — direction of the PRIMARY result:
  positive      intervention shows benefit (lower HR, higher ORR, longer OS)
  non_inferior  NI margin pre-specified and confirmed (de-escalation proven)
  negative      no benefit or harm demonstrated
  inconclusive  mixed or ambiguous signal
  not_reported  insufficient data in abstract

hr_value — numeric hazard ratio (e.g. 0.76) or null if not a time-to-event endpoint

p_value_significant — boolean: p < pre-specified alpha (typically 0.05)

hard_to_treat — boolean: true for GBM, SCLC, pancreatic, biliary,
  mesothelioma, gastric, DIPG, appendiceal, or any setting with expected OS < 12 months

─────────────────────────────────────────────────────────────────────────────
REJECT RECOMMENDATION — your one judgment call
─────────────────────────────────────────────────────────────────────────────
Set reject_recommendation=true if the paper is noise despite passing the gate:

  • Paraneoplastic syndromes — not treatment practice-changing
  • GLP-1 / SGLT2 / EHR pharmacoepidemiology — observational confounding, not actionable
  • Auto-segmentation / AI contouring / planning tools — physics QA, not clinical decisions
  • Prognostic biomarker / nomogram — no intervention, no treatment change
  • Meta-analysis of fully settled question — conclusion surprises no one
  • Exploratory / post-hoc subgroup only — not ITT primary result
  • Single-institution retrospective, n < 100, standard regimen
  • SEER / NCDB / claims data describing practice patterns only (no intervention)
  • Surgical technique paper — "robotic cystectomy learning curve", "retroauricular thyroidectomy"

Set reject_recommendation=false for:
  • Phase III primary results (any direction — a clearly negative Phase III is still news)
  • Phase II randomized with randomized comparator and any reported endpoint
  • FDA approval or formal guideline update
  • Landmark meta-analyses that resolve a long-standing clinical question
  • Any major conference LBA/plenary abstract

─────────────────────────────────────────────────────────────────────────────
EVIDENCE STRENGTH — for display and sanity-check only (does not determine tier)
─────────────────────────────────────────────────────────────────────────────
  A = Phase III RCT primary results / FDA approval / major guideline update
  B = Phase II randomized / landmark meta-analysis / Phase III strong but not primary
  C = Phase II single-arm / meta-analysis of unsettled question / emerging signal
  D = Anything else

─────────────────────────────────────────────────────────────────────────────
TEXT QUALITY RULES — strictly enforced
─────────────────────────────────────────────────────────────────────────────
Every text field must be publication-ready. No lowercase sentence starts.
No telegraphic fragments. Write as a clinical editor would.

  population
    Complete noun phrase starting with the patient type. Include age range,
    performance status, and key eligibility criteria.
    ✓ "Resected locally advanced SCCHN (oral cavity/oropharynx/larynx/
       hypopharynx), age 19–74, ECOG 0–1, ≥1 high-risk pathologic feature
       (e.g., ENE, positive margin, ≥4 nodes without ENE, PNI)."
    ✗ "patients with resected SCCHN"

  regimen_description
    Proper-case narrative. Include study design, arms, doses, and schedule
    where reported.
    ✓ "Open-label phase III; cisplatin + PORT (66 Gy, cisplatin 100 mg/m²
       q3w ×3) vs same backbone + nivolumab (peri-CRT + adjuvant schedule)."
    ✗ "phase 3 trial nivolumab vs placebo"

  key_results.effect_size
    Complete finding sentence including the endpoint name, direction, and
    numeric result. Include HR/OR/ORR and CI in the same field.
    ✓ "DFS improved with nivolumab + cisplatin-RT vs cisplatin-RT alone
       (HR 0.76, 95% CI 0.60–0.98; p=0.034), regardless of PD-L1 status."
    ✗ "DFS HR 0.76"

  key_results.toxicity_qol_signal
    Complete sentence starting with a capital letter.
    ✓ "Higher grade 4 treatment-related AEs with nivolumab arm (10% vs 5%);
       treatment-related deaths: 2 in each group."
    ✗ "more toxicity in nivo arm"

  carcinos_one_liner
    One complete sentence. Starts with capital. States the clinical
    implication clearly for a radiation or medical oncologist.
    ✓ "For high-risk resected LA-SCCHN, adding nivolumab to standard
       postoperative cisplatin-RT meaningfully improves DFS with a moderate
       toxicity increase, supporting its incorporation into adjuvant regimens."
    ✗ "nivolumab improves DFS in SCCHN"

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
    evidence_strength: str
    final_tier_code: str   # 'A' / 'B' / 'C' / 'NOISE' — maps to alerts.tier in schema
    tier_rationale_text: str
    notify: bool
    cost_usd_estimate: float


def run_pass2(
    client: OpenAIClient,
    candidate: CanonicalCandidate,
    pass1_parsed: dict,
    qualifying_signal: str = "",
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

    evidence = str(parsed.get("evidence_strength", "D"))

    # Deterministic tier assignment — no LLM scoring involved.
    # compute_tier() reads structured extraction fields from the LLM response
    # and applies fixed rules. The only LLM judgment is reject_recommendation.
    final_code = compute_tier(parsed, qualifying_signal)
    rationale_text = tier_rationale(parsed, qualifying_signal, final_code)

    notify = decide_notify(final_code, parsed)
    cost = _estimate_pass2_cost(result.usage)

    return Pass2Result(
        parsed=parsed,
        evidence_strength=evidence,
        final_tier_code=final_code,
        tier_rationale_text=rationale_text,
        notify=notify,
        cost_usd_estimate=cost,
    )


# ---------------------------------------------------------------------------
# DEPRECATED — enforce_tier_mapping() removed in deterministic-tier refactor.
# Tier assignment is now handled by compute_tier() in triage/tier_logic.py.
# The LLM no longer scores papers; it only extracts structured facts.
# ---------------------------------------------------------------------------


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
