"""
Pass 1 — fast triage (spec §3 Pass 1).

Decides keep vs drop, basic classification, and a relevance hint.
Runs on every candidate that survives the deterministic filters.
"""

from __future__ import annotations
from dataclasses import dataclass

from .openai_client import OpenAIClient
from .schemas import PASS1_SCHEMA
from ..normalize.canonical import CanonicalCandidate


PASS1_SYSTEM = """You are CarcinoS Triage, an oncology literature triage engine.

Your job is NOT to summarize. Your job is to classify and decide whether
this item should be reviewed further.

Rules:
- Use ONLY the provided text. Do not invent facts.
- If the abstract is missing or unclear, be conservative: keep=true if the
  title plausibly relates to clinical oncology in the named cancer site.
- If the article is preclinical-only with no clinical bridge, drop unless
  it identifies a biomarker or mechanism with explicit therapeutic
  implications.
- If the article is opinion/commentary with no original data, drop.
- "wrong_disease_site" means the article is oncology but for a different
  primary site than the one provided.

Scoring rubric (apply consistently):
  +35 if a clear cancer-site term appears in the title for the requested site
  +20 if randomized/phase 2/phase 3/noninferiority/meta-analysis/guideline appears
  +15 if survival endpoint words (OS/PFS/DFS/EFS/RFS) or toxicity/QoL appear
  +15 if a modality keyword appears (RT, brachy, surgery, IO, targeted, screening)
  -35 if the article is non-oncology
  -30 if commentary/editorial/letter with no original data
  If abstract is missing, do NOT penalize unless the title is clearly irrelevant.

Output MUST be valid JSON matching the schema. No prose. No extra keys.
"""


PASS1_USER_TEMPLATE = """Triage this {site_name} oncology candidate from the past week.

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

DETERMINISTIC PRIOR:
- relevance_score (deterministic, pre-LLM): {det_score}
- relevance_rationale: {det_rationale}
- pubtype_decision: {pubtype}
- force_keep_reason: {force_keep_reason}

Return JSON only.
"""


@dataclass
class Pass1Result:
    parsed: dict
    keep: bool
    relevance_score: int
    priority_hint: str
    drop_reason: str | None
    cost_usd_estimate: float


def run_pass1(
    client: OpenAIClient,
    candidate: CanonicalCandidate,
) -> Pass1Result:
    user = PASS1_USER_TEMPLATE.format(
        site_name=candidate.cancer_site_name,
        title=candidate.title or "(no title)",
        abstract=(candidate.abstract or "")[:5000] or "(no abstract)",
        journal=candidate.journal or "(unknown)",
        publication_date=candidate.publication_date or "(unknown)",
        publication_types=", ".join(candidate.publication_types) or "(none)",
        mesh_terms=", ".join(candidate.mesh_terms[:20]) or "(none)",
        modality_keywords_present=", ".join(candidate.modality_keywords_present) or "(none)",
        pmid=candidate.pmid,
        doi=candidate.doi or "(none)",
        det_score=candidate.deterministic_relevance_score,
        det_rationale="; ".join(candidate.deterministic_rationale) or "(none)",
        pubtype=f"keep={candidate.pubtype_keep} low_priority={candidate.pubtype_low_priority} ({candidate.pubtype_rationale})",
        force_keep_reason=candidate.force_keep_reason or "(none)",
    )

    result = client.structured(
        model=client.triage_model,
        system=PASS1_SYSTEM,
        user=user,
        schema=PASS1_SCHEMA,
        temperature=0.0,
    )

    parsed = result.parsed
    cost = _estimate_pass1_cost(result.usage, model=client.triage_model)

    return Pass1Result(
        parsed=parsed,
        keep=bool(parsed.get("keep")),
        relevance_score=int(parsed.get("relevance_score", 0)),
        priority_hint=str(parsed.get("priority_hint", "low")),
        drop_reason=parsed.get("drop_reason"),
        cost_usd_estimate=cost,
    )


def _estimate_pass1_cost(usage: dict, model: str = "") -> float:
    """
    Token-based cost estimate using published OpenAI rates.
    Model-aware so telemetry reflects the actual model used.
    Don't depend on these for billing — they are for budget telemetry only.
    """
    m = model.lower()
    if "gpt-4o-mini" in m:
        in_per_million, out_per_million = 0.15, 0.60
    elif "gpt-4o" in m:
        in_per_million, out_per_million = 2.50, 10.00
    elif "gpt-4.1-mini" in m:
        in_per_million, out_per_million = 0.40, 1.60
    elif "gpt-4.1" in m:
        in_per_million, out_per_million = 2.00, 8.00
    else:
        in_per_million, out_per_million = 2.50, 10.00
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    return (pt / 1e6) * in_per_million + (ct / 1e6) * out_per_million


# ---------------------------------------------------------------------------
# Post-LLM threshold enforcement (spec §3: "your code, not the model,
# enforces alert thresholds").
# ---------------------------------------------------------------------------

def enforce_pass1_keep_rules(
    candidate: CanonicalCandidate,
    pass1: Pass1Result,
    keep_threshold: int = 50,
    high_priority_floor: int = 40,
) -> tuple[bool, str]:
    """
    Returns (final_keep, reason). The LLM's `keep` is a *hint* — these rules
    are authoritative. This is what makes the pipeline auditable.
    """
    # Force-keep override: whitelisted journals always pass to Pass 2.
    if candidate.force_keep_reason:
        return True, f"force_keep: {candidate.force_keep_reason}"

    # The LLM said drop AND deterministic agrees AND no other override.
    if not pass1.keep and pass1.relevance_score < keep_threshold:
        return False, f"pass1_drop: {pass1.drop_reason or 'low_relevance'}"

    # Score >= threshold → keep.
    if pass1.relevance_score >= keep_threshold:
        return True, f"pass1_score_{pass1.relevance_score}"

    # High-priority hint with score 40-49 → keep (spec §3).
    if pass1.priority_hint == "high" and pass1.relevance_score >= high_priority_floor:
        return True, f"pass1_high_priority_score_{pass1.relevance_score}"

    return False, f"pass1_below_threshold_score_{pass1.relevance_score}"
