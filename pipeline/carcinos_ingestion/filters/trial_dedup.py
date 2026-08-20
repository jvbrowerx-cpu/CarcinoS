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
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..pipeline import AlertOutput

log = logging.getLogger("carcinos.trial_dedup")

# Title similarity threshold for cross-site duplicate detection when one
# instance has trial_name and the other has null.  0.88 is tight enough to
# avoid false positives between related-but-distinct papers while still
# catching the same abstract processed by two disease sites.
_TITLE_SIM_THRESHOLD = 0.88


def _normalize_title(t: str) -> str:
    return " ".join(t.lower().split())


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


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

    # Group by normalized trial name (null trial_name = never deduplicated by name)
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
    named_winners: list["AlertOutput"] = []
    for trial_key, group in trial_groups.items():
        if len(group) == 1:
            winner = group[0]
            kept.append(winner)
            named_winners.append(winner)
            continue

        # Sort: ascending _sort_key → first element is highest priority
        group_sorted = sorted(group, key=_sort_key)
        winner = group_sorted[0]
        losers = group_sorted[1:]

        kept.append(winner)
        named_winners.append(winner)
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

    # Title-similarity pass for null-trial_name items.
    #
    # A paper processed by two disease sites may produce one alert with
    # trial_name set and one with null — the trial-name dedup above cannot
    # link them. Compare each null-trial_name alert against every named winner
    # by title similarity; if they are the same paper (sim >= threshold), drop
    # the null-trial_name copy (it is always the lower-priority duplicate,
    # because the named winner already survived the priority sort above).
    remaining_no_trial: list["AlertOutput"] = []
    for alert in no_trial_name:
        alert_title = alert.candidate.title or ""
        is_dup = False
        for winner in named_winners:
            sim = _title_similarity(alert_title, winner.candidate.title or "")
            if sim >= _TITLE_SIM_THRESHOLD:
                is_dup = True
                log.info(
                    "[trial_dedup] title-sim match (%.2f >= %.2f): dropping null-trial_name "
                    "duplicate (PMID %s title='%.60s...') — kept named winner PMID %s '%s'",
                    sim, _TITLE_SIM_THRESHOLD,
                    alert.candidate.pmid or "?",
                    alert_title,
                    winner.candidate.pmid or "?",
                    (winner.pass2.parsed.get("trial_name") or "?").upper(),
                )
                dropped.append(alert)
                break
        if not is_dup:
            remaining_no_trial.append(alert)

    # Also dedup within the null-trial_name group itself by title similarity.
    # Prevents the same no-name paper (e.g. a review) from appearing twice if
    # it was captured by two sites that both assigned trial_name=null.
    deduped_no_trial: list["AlertOutput"] = []
    for alert in remaining_no_trial:
        alert_title = alert.candidate.title or ""
        is_dup = False
        for existing in deduped_no_trial:
            sim = _title_similarity(alert_title, existing.candidate.title or "")
            if sim >= _TITLE_SIM_THRESHOLD:
                # Keep the higher-priority source
                if _sort_key(alert) < _sort_key(existing):
                    deduped_no_trial.remove(existing)
                    deduped_no_trial.append(alert)
                    dropped.append(existing)
                else:
                    dropped.append(alert)
                is_dup = True
                break
        if not is_dup:
            deduped_no_trial.append(alert)

    kept.extend(deduped_no_trial)

    return kept, dropped
