"""
signal_score.py — additions for conference stratification and journal guardrail.

HOW TO APPLY
------------
1. Add the two compiled regexes and _score_conference_abstract() near the top
   of signal_score.py, after any existing conference-related constants.

2. Replace the block that emits "MAJOR_CONFERENCE" with a call to
   _score_conference_abstract() so it returns HIGH or LOW instead.

3. Add check_journal_force_guardrail() anywhere in the file (it's standalone).

4. In pipeline.py, call check_journal_force_guardrail() before promoting a
   force-keep QS_NONE candidate to Pass 2 (see pipeline_patch.py for the
   exact insertion point).
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # CanonicalCandidate is defined in normalize/canonical.py.
    # Import only for type-checking to avoid circular imports.
    from ..normalize.canonical import CanonicalCandidate


# ---------------------------------------------------------------------------
# Conference abstract tier patterns
# ---------------------------------------------------------------------------

# High-confidence conference signal: LBA, plenary, Phase III, OS endpoint,
# or a watched/named trial explicitly mentioned.
_CONF_HIGH_RE = re.compile(
    r"\b("
    r"late.?breaking|LBA\b|plenary|presidential\s+symposium"
    r"|oral\s+(abstract|presentation|session)"
    r"|phase\s+(III|3)|phase-III|phase-3"
    r"|overall\s+survival\b|OS\s+benefit|OS\s+data|mature\s+OS"
    r"|practice.?changing|landmark\s+(trial|study|data)"
    r"|guideline.?changing|approval"
    r")\b",
    re.IGNORECASE,
)

# Low-confidence conference signal: poster, single-arm Phase II, retrospective,
# exploratory, or subgroup-only analysis.
_CONF_LOW_RE = re.compile(
    r"\b("
    r"poster\b|e-poster|poster\s+(session|presentation|number|#)"
    r"|phase\s+II\s+single|phase-II\s+single|single.arm"
    r"|retrospective|real.world\s+(evidence|data|analysis)"
    r"|exploratory\s+(analysis|cohort|endpoint)"
    r"|pilot\s+(study|trial)|feasibility"
    r"|translational\s+(research|study)|correlative"
    r"|biomarker\s+(analysis|sub.?study)|subset\s+analysis"
    r"|subgroup\s+(analysis|only)"
    r")\b",
    re.IGNORECASE,
)


def _score_conference_abstract(
    candidate: "CanonicalCandidate",
    watched_trials: frozenset[str],
) -> str:
    """
    Classify a conference abstract as MAJOR_CONFERENCE_HIGH or MAJOR_CONFERENCE_LOW.

    HIGH → card candidate (proceeds through Pass 1 → Pass 2 normally).
    LOW  → discovery signal only; updates the watchlist, does not become a card.

    Call this only when the existing signal scorer has already determined the
    candidate is a conference abstract (is_conference_abstract=True).

    Priority order:
      1. Watched trial mention → always HIGH, regardless of abstract language.
         These are trials the pipeline already knows are high-value.
      2. High-confidence language (LBA, plenary, Phase III, OS) without
         low-confidence language → HIGH.
      3. High-confidence + low-confidence language together → HIGH
         (e.g., a plenary abstract that is also a subgroup analysis).
         The high-confidence signal wins.
      4. Low-confidence language only, or no signal either way → LOW.
    """
    text = f"{candidate.title or ''} {(candidate.abstract or '')[:3000]}"

    # Rule 1: watched trial → always HIGH
    if watched_trials:
        text_lower = text.lower()
        if any(t.lower() in text_lower for t in watched_trials if t):
            return "MAJOR_CONFERENCE_HIGH"

    high_match = bool(_CONF_HIGH_RE.search(text))

    # Rules 2 + 3: any high-confidence language → HIGH
    if high_match:
        return "MAJOR_CONFERENCE_HIGH"

    # Rule 4: low-only or ambiguous → LOW
    return "MAJOR_CONFERENCE_LOW"


# ---------------------------------------------------------------------------
# Top-journal force-keep guardrail
# ---------------------------------------------------------------------------

# Minimum language for a paper to retain the top-journal override.
# Keeps the bar low — a NEJM oncology trial needs very little language to pass.
# The point is only to catch clearly non-clinical or non-oncology papers
# (e.g., a cardiovascular meta-analysis in NEJM) from getting force-promoted.
_CLINICAL_ONCO_RE = re.compile(
    r"\b("
    r"trial|randomized|randomised"
    r"|phase\s+(I|II|III|IV|1|2|3|4)"
    r"|overall\s+survival|progression.free|disease.free|event.free"
    r"|response\s+rate|hazard\s+ratio|odds\s+ratio"
    r"|guideline|recommendation|approval|indication"
    r"|regimen|chemotherapy|immunotherapy|targeted\s+therapy"
    r"|checkpoint|VEGF|PARP|CDK|mTOR|EGFR|ALK|ROS1|KRAS|BRAF|HER2"
    r"|radiation|radiotherapy|radiosurgery|brachytherapy|PORT|SBRT|IMRT"
    r"|surgery|resection|mastectomy|prostatectomy|nephrectomy|hepatectomy"
    r"|adjuvant|neoadjuvant|metastatic|locally\s+advanced|recurrent|refractory"
    r"|first.line|second.line|maintenance|consolidation"
    r"|biomarker|mutation|amplification|MSI|TMB|PD.L1"
    r")\b",
    re.IGNORECASE,
)


def check_journal_force_guardrail(
    candidate: "CanonicalCandidate",
    *,
    relevance_floor: int = 35,
) -> tuple[bool, str]:
    """
    Determine whether a top-journal paper's force-keep privilege is warranted.

    A paper earns the force-keep bypass if it meets AT LEAST ONE of:
      1. Deterministic relevance score >= relevance_floor (disease-site keyword hit)
      2. Title or abstract contains clinical oncology language

    If neither condition holds, the paper is demoted from force-keep to
    standard QS_NONE mini-triage routing. It can still reach Pass 2 via
    mini-triage — it just loses the automatic bypass.

    Returns:
        (passes_guardrail: bool, reason: str)

    Design note — why narrow?
    The point of this guardrail is not to filter good oncology papers; it's
    to stop clearly non-clinical papers in top journals (e.g., a NEJM study
    of cardiovascular risk biomarkers with no cancer relevance) from consuming
    a Pass 2 slot. The threshold is deliberately low so that anything even
    marginally relevant still passes.

    Do NOT add a "watched trial" condition here. If a watched trial is failing
    to score a qualifying signal (WATCHED_TRIAL), fix signal_score.py's trial-
    name matching — don't paper over it in the guardrail.
    """
    # Condition 1: disease-site relevance (keyword score, set by relevance.py)
    if candidate.deterministic_relevance_score >= relevance_floor:
        return True, f"journal_force_relevance_{candidate.deterministic_relevance_score}"

    # Condition 2: clinical oncology language anywhere in title or abstract
    text = f"{candidate.title or ''} {(candidate.abstract or '')[:3000]}"
    if _CLINICAL_ONCO_RE.search(text):
        return True, "journal_force_clinical_language"

    return False, (
        f"journal_force_guardrail_failed: "
        f"relevance={candidate.deterministic_relevance_score} "
        f"and no clinical oncology language detected in title/abstract"
    )
