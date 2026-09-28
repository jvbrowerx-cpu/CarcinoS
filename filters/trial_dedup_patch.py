"""
filters/trial_dedup.py — patch to sort by CONFIDENCE_SOURCE_RANK.

HOW TO APPLY
------------
In trial_dedup.py, find the function that selects which alert to keep when
two or more alerts share the same trial name. Replace the existing source-
priority comparison (which uses string matching on conference_source or
publication_types) with a lookup into CONFIDENCE_SOURCE_RANK.

This makes the trust hierarchy explicit and consistent with the new
confidence_source field on CanonicalCandidate.

CURRENT BEHAVIOR (implicit priority):
  The existing code likely does something like:
      if "FDA" in candidate.conference_source: priority = 100
      elif candidate.is_conference_abstract: priority = 50
      else: priority = 70   # journal
  ...using ad-hoc comparisons that don't account for trade_press or llm_discovery.

NEW BEHAVIOR (explicit CONFIDENCE_SOURCE_RANK lookup):
  Sort by CONFIDENCE_SOURCE_RANK[candidate.confidence_source] descending.
  The alert with the highest-ranked source wins.
  If ranks are equal (same source type), prefer the one with the earlier
  publication_date (i.e., the primary publication, not an update/erratum).
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from ..signal import CONFIDENCE_SOURCE_RANK

if TYPE_CHECKING:
    from ..pipeline import AlertOutput   # AlertOutput.candidate is CanonicalCandidate


def _source_rank(alert: "AlertOutput") -> int:
    """Return the CONFIDENCE_SOURCE_RANK for this alert's candidate."""
    cs = getattr(alert.candidate, "confidence_source", "peer_reviewed")
    return CONFIDENCE_SOURCE_RANK.get(cs, 0)


# ── Drop-in replacement for the existing dedup key function ──────────────────
#
# BEFORE (existing dedup logic, conceptually):
#
#   def _priority(alert):
#       cs = alert.candidate.conference_source or ""
#       if cs.upper() == "FDA": return 100
#       if alert.candidate.is_conference_abstract: return 50
#       return 70
#
#   # Keep the highest-priority alert per trial name
#   kept = {}
#   for alert in alerts:
#       name = alert.pass2.parsed.get("trial_name") or ""
#       if not name:
#           continue
#       if name not in kept or _priority(alert) > _priority(kept[name]):
#           kept[name] = alert
#
# AFTER:
#
#   def _sort_key(alert):
#       rank = _source_rank(alert)
#       # Secondary sort: earlier publication date preferred (primary publication)
#       pub = alert.candidate.publication_date or "9999-99-99"
#       return (-rank, pub)   # negate rank so higher rank sorts first
#
#   from itertools import groupby
#
#   # Group alerts by trial name, then pick the highest-ranked source per group
#   named_alerts = [a for a in alerts if a.pass2.parsed.get("trial_name")]
#   unnamed_alerts = [a for a in alerts if not a.pass2.parsed.get("trial_name")]
#
#   kept_named = {}
#   for alert in sorted(named_alerts, key=_sort_key):
#       name = alert.pass2.parsed["trial_name"]
#       if name not in kept_named:
#           kept_named[name] = alert   # first = highest-ranked source
#
#   deduplicated = list(kept_named.values()) + unnamed_alerts
#   dropped = [a for a in named_alerts if a not in kept_named.values()]
#   return deduplicated, dropped


def _sort_key_for_dedup(alert: "AlertOutput") -> tuple:
    """
    Sorting key for trial-name deduplication.

    Primary:   CONFIDENCE_SOURCE_RANK descending (higher = more trusted)
    Secondary: publication_date ascending (earlier = more likely primary publication)

    Usage:
        sorted_alerts = sorted(named_alerts, key=_sort_key_for_dedup)
        # First alert for each trial_name is the one to keep.
    """
    rank = _source_rank(alert)
    pub  = getattr(alert.candidate, "publication_date", None) or "9999-99-99"
    return (-rank, pub)    # negate rank so highest rank sorts to front
