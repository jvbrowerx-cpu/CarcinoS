"""
Trial-name deduplication — prevents the same trial from appearing multiple times
when indexed across different disease-site queries or retrieval lanes.

Problem
-------
FLAURA2 OS results might surface as:
  • A JCO article (main PubMed lane, thoracic site)
  • The same ASCO abstract (conference lane, also thoracic)

Without dedup, the editor sees two cards for the same trial update. With dedup,
only the highest-priority source is kept.

Deduplication key
-----------------
Normalized trial_name from Pass 2 LLM extraction (lowercase, stripped). Papers
without a trial_name (null) are never deduplicated — they might be reviews,
meta-analyses, or single-institution reports that coincidentally discuss the same topic.

Source priority (highest → lowest)
------------------------------------
  3 — FDA approval record (study_design == "fda_approval")
  2 — Journal article (is_conference_abstract=False or conference_source falsy)
  1 — Conference / meeting abstract (is_conference_abstract=True)

Tie-breaking
------------
If two sources share the same priority, keep the one with the higher Gate 3
additive score (captures: OS endpoint, LBA label, RT relevance, first-line, etc.).
If scores also tie, keep the one with the lower PMID (earlier publication).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..pipeline import AlertOutput

log = logging.getLogger("carcinos.trial_dedup")


def _source_priority(alert: "AlertOutput") -> int:
    """
    Return a source priority integer (higher = preferred).
    FDA > journal > conference abstract.
    """
    p2 = alert.pass2.parsed
    if p2.get("study_design") == "fda_approval":
        return 3
    if getattr(alert.candidate, "is_conference_abstract", False):
        return 1
    return 2


def _sort_key(alert: "AlertOutput") -> tuple:
    """
    Sort key for selecting the best alert within a trial group.
    Ascending sort; the element with the smallest key is the winner.
    Negate priority/score so that higher values sort first.
    """
    priority = _source_priority(alert)
    # Gate 3 additive score stored in synthetic pass1.relevance_score
    score = getattr(alert.pass1, "relevance_score", 0) or 0
    # Lower PMID = earlier publication (tiebreak — prefer earlier)
    pmid_int = int(alert.candidate.pmid or "99999999")
    return (-priority, -score, pmid_int)


def deduplicate_by_trial_name(
    alerts: list["AlertOutput"],
) -> tuple[list["AlertOutput"], list["AlertOutput"]]:
    """
    Deduplicate a flat list of alerts by trial_name.

    Returns:
        (kept, dropped)
        kept:    alerts to forward to the portal — one per trial where trial_name is set,
                 plus all alerts with null trial_name (never deduplicated)
        dropped: alerts removed as lower-priority duplicates

    Caller should log and/or count dropped alerts for transparency.
    """
    kept: list["AlertOutput"] = []
    dropped: list["AlertOutput"] = []

    # Group by normalized trial name (null trial_name = never deduplicate)
    trial_groups: dict[str, list["AlertOutput"]] = {}
    no_trial_name: list["AlertOutput"] = []

    for alert in alerts:
        name = (alert.pass2.parsed.get("trial_name") or "").strip()
        if not name:
            no_trial_name.append(alert)
            continue
        key = name.lower()
        trial_groups.setdefault(key, []).append(alert)

    # For each trial group: keep the best source, drop the rest
    for trial_key, group in trial_groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue

        # Sort: ascending _sort_key → first element is highest priority
        group_sorted = sorted(group, key=_sort_key)
        winner = group_sorted[0]
        losers = group_sorted[1:]

        kept.append(winner)
        dropped.extend(losers)

        if losers:
            trial_display = (winner.pass2.parsed.get("trial_name") or trial_key).upper()
            winner_src = "FDA" if _source_priority(winner) == 3 else (
                "conference abstract" if _source_priority(winner) == 1 else "journal"
            )
            log.info(
                "[trial_dedup] %s: kept %s (%s, PMID %s); dropped %d duplicate(s): %s",
                trial_display,
                winner.candidate.journal or "?",
                winner_src,
                winner.candidate.pmid or "?",
                len(losers),
                [a.candidate.pmid for a in losers],
            )

    # Papers with no trial name are always kept
    kept.extend(no_trial_name)

    return kept, dropped
