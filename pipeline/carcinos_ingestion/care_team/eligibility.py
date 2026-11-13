"""Deterministic gate: which cards are even considered for a care-team section.

No model is involved here. A card must pass every rule; the first failing rule
is returned as the reason so the editor can see why a card was skipped.
"""

from __future__ import annotations

from .config import CareTeamSettings


def is_fda_card(alert: dict) -> bool:
    """FDA approval cards, including ones added by hand in the admin portal."""
    s = alert.get("summary_json") or {}
    cls = s.get("classification") or {}
    return (
        (s.get("conference_source") or "").upper() == "FDA"
        or (s.get("qualifying_signal") or "").upper() in ("FDA", "QS_FORCE_KEEP")
        or (cls.get("study_design") or s.get("study_design") or "") == "fda_approval"
        or "fda" in (s.get("journal") or "").lower()
        or (alert.get("title") or "").lower().startswith("fda ")
    )


def check_eligibility(
    alert: dict,
    paper_text: str,
    settings: CareTeamSettings,
    *,
    force: bool = False,
) -> tuple[bool, str]:
    s = alert.get("summary_json") or {}

    tier = alert.get("tier")
    if tier not in settings.tiers:
        return False, f"tier {tier} not in eligible tiers {settings.tiers}"

    if s.get("reject_recommendation") is True:
        return False, "pipeline recommended rejection"

    # FDA approval cards (often added by hand) have no stored paper text; the
    # FDA label and ClinicalTrials.gov are their sources. Hand-added cards may
    # also use those external sources. Everything else needs the paper text.
    has_text = bool(paper_text) and len(paper_text) >= 200
    if not has_text and not (is_fda_card(alert) or s.get("is_manually_added")):
        return False, "no stored source text to ground claims"

    if s.get("care_team") and not force:
        return False, "already has a care-team result"

    return True, "eligible"
