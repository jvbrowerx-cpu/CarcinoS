"""
normalize/canonical.py — additions for confidence_source field.

HOW TO APPLY
------------
1. Add the imports at the top of canonical.py:
       from ..signal import ConfidenceSource, CONFIDENCE_SOURCE_RANK

2. Add `confidence_source: ConfidenceSource = "peer_reviewed"` to the
   CanonicalCandidate dataclass (see DATACLASS ADDITION below).

3. Add assign_confidence_source() anywhere in canonical.py.

4. Call assign_confidence_source(candidate) at the end of the normalization
   step, after all other fields are populated, before the candidate is
   returned from the normalizer.

   In pipeline.py, the call should happen in the normalization loop, e.g.:
       candidate = normalize(record, site)
       candidate.confidence_source = assign_confidence_source(candidate)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .canonical import CanonicalCandidate

from ..signal import ConfidenceSource


# ---------------------------------------------------------------------------
# DATACLASS ADDITION
# ---------------------------------------------------------------------------
# Add this field to CanonicalCandidate in canonical.py:
#
#   confidence_source: ConfidenceSource = "peer_reviewed"
#   """
#   Provenance of how this candidate entered the pipeline.
#   Set deterministically at normalization time — not by the LLM.
#   Used by tier_logic.py (to block weak sources from cards) and
#   trial_dedup.py (to prefer the highest-trust source per trial).
#   See signal.py for the full type definition and CONFIDENCE_SOURCE_RANK.
#   """
# ---------------------------------------------------------------------------


def assign_confidence_source(candidate: "CanonicalCandidate") -> ConfidenceSource:
    """
    Assign a ConfidenceSource to a normalized candidate.

    Rules are evaluated top-to-bottom; the first match wins.
    This function is pure and side-effect-free — it returns the value,
    the caller assigns it to candidate.confidence_source.

    Lane mapping:
      Lane 4 (FDA)             → conference_source == "FDA"        → "fda"
      Guideline records        → "Guideline" in publication_types  → "guideline"
      Lane 3 (conferences)     → is_conference_abstract == True    → "late_breaking_abstract"
                                 (HIGH/LOW split happens later in signal_score.py;
                                  here we just mark it as LBA-class)
      Lane 5 (web search)      → conference_source == "WEB_SEARCH" → "llm_discovery"
      Lane 6 primary feeds     → conference_source == "NEWS"        → varies by feed type
      Lane 6 trade press       → conference_source == "TRADE_PRESS" → "trade_press"
      Lane 6 press release     → conference_source == "PRESS_RELEASE" → "company_press_release"
      Lanes 1/2 (PubMed)       → default                           → "peer_reviewed"

    Note: conference_source values are set by the retrieval modules and stored
    on the raw PubMedRecord before normalization. The normalization step copies
    them onto CanonicalCandidate.
    """
    conf_src = (candidate.conference_source or "").upper()
    pub_types = [pt.upper() for pt in (candidate.publication_types or [])]

    # ── FDA approval notification ─────────────────────────────────────────────
    if conf_src == "FDA" or "FDA DRUG APPROVAL" in pub_types:
        return "fda"

    # ── Formal guideline record ───────────────────────────────────────────────
    if "GUIDELINE" in pub_types or conf_src == "GUIDELINE":
        return "guideline"

    # ── Conference abstract (Lane 3) ──────────────────────────────────────────
    # All conference abstracts start as "late_breaking_abstract" here.
    # signal_score.py then further splits them into MAJOR_CONFERENCE_HIGH
    # (which keeps this confidence_source) vs MAJOR_CONFERENCE_LOW (which
    # pipeline.py routes to watchlist-only).
    if candidate.is_conference_abstract:
        return "late_breaking_abstract"

    # ── LLM web search (Lane 5) ───────────────────────────────────────────────
    if conf_src == "WEB_SEARCH":
        return "llm_discovery"

    # ── Trade press (Lane 6 secondary) ───────────────────────────────────────
    if conf_src == "TRADE_PRESS":
        return "trade_press"

    # ── Company press release (Lane 6 primary) ────────────────────────────────
    if conf_src in ("PRESS_RELEASE", "COMPANY_RELEASE"):
        return "company_press_release"

    # ── Default: PubMed-indexed journal article (Lanes 1/2) ──────────────────
    return "peer_reviewed"
