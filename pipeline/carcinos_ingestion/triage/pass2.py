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


PASS2_SYSTEM = """You are CarcinoS Deep Review.

Your job:
  (1) Extract key facts from the provided text only.
  (2) Score evidence strength and impact using the rubric.
  (3) Assign a preliminary alert tier — final tier is set by code.
  (4) Provide 1-3 short literal quotes from the abstract that support your
      key claims. These quotes are the grounding evidence and MUST appear
      verbatim in the source text. Do not paraphrase.

Rules:
  - Do not add facts not present in the text.
  - If a value is not reported, say "not_reported" exactly.
  - Be concise and structured.
  - If effect size is missing, do NOT extrapolate from prior trials.

Evidence strength:
  A = phase 3 RCT, high-quality meta-analysis of RCTs, or major guideline update
  B = phase 2 randomized, strong prospective cohort/registry with robust methods
  C = single-arm phase 2, retrospective, early diagnostic accuracy without outcomes
  D = preclinical, case report, opinion

Impact scoring (additive) — be generous, not conservative:
  +40 OS benefit clearly shown in a randomized trial
  +35 OS benefit in a historically hard-to-treat cancer (pancreatic, SCLC, mesothelioma, GBM) — these are landmark even at modest magnitude
  +30 strong EFS/DFS/PFS benefit in early-stage or adjuvant setting with clear practice change potential
  +25 strong PFS benefit with clear adoption potential in the metastatic setting
  +25 noninferiority with meaningful toxicity/QoL improvement or major de-escalation
  +30 new FDA approval or guideline change (only if the source explicitly states it)
  +20 first positive Phase III in an indication with no prior standard targeted therapy (e.g. rare driver mutations, orphan cancers)
  +20 biomarker-defined population with large effect size (HR < 0.65 or ORR > 60%)
  +15 meaningful improvement in a second-line or later setting with few options
  -25 single-arm without comparator
  -15 surrogate-only endpoint with modest magnitude (HR 0.80-0.90 range)
  -20 observational confounding likely
  -10 results from a non-US/EU population with limited generalizability

Important calibration notes:
  - A Phase III trial with OS benefit (even if OS is immature but statistically significant) scores >= 70
  - A Phase III OS benefit in a hard-to-treat cancer (pancreatic, SCLC, GBM, mesothelioma) scores >= 80
  - A first-in-class Phase III beating standard chemotherapy scores >= 75
  - Adjuvant Phase III with EFS/DFS benefit in early-stage disease scores >= 65
  - Do NOT penalize for immature OS if the benefit is statistically significant and clinically meaningful
  - Do NOT penalize for small population size if the biomarker selection is strong
  - FDA approval or guideline update always adds +30 on top of the trial score
  - Review articles and educational summaries of already-established standards score <= 45

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

PASS 1 CONTEXT:
- pass1_relevance_score: {pass1_score}
- pass1_priority_hint: {pass1_hint}
- pass1_one_liner: {pass1_one_liner}

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
