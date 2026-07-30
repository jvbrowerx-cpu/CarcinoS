"""
pipeline.py — targeted patch for three routing changes.

HOW TO APPLY
------------
Find the three marked insertion points in pipeline.py and apply each patch.

All three changes are self-contained additions to existing routing blocks;
they do not restructure the pipeline.

PATCH 1: Conference stratification — LOW → watchlist only
PATCH 2: Journal force-keep guardrail
PATCH 3: Pass discovery-only candidates to watchlist, not Pass 2
"""

# ═══════════════════════════════════════════════════════════════════════════════
# PATCH 1: Conference stratification
# ═══════════════════════════════════════════════════════════════════════════════
#
# LOCATION: In the qualifying-signal scoring block, wherever the existing code
# handles the "MAJOR_CONFERENCE" signal code. Replace the existing emit of
# "MAJOR_CONFERENCE" with the call to _score_conference_abstract().
#
# BEFORE (existing logic, conceptually):
#
#   if is_conference_abstract:
#       qs_code = "MAJOR_CONFERENCE"
#       # ... fall through to Pass 1 → Pass 2 normally
#
# AFTER:
#
#   from .filters.signal_score_additions import _score_conference_abstract
#
#   if is_conference_abstract:
#       qs_code = _score_conference_abstract(candidate, effective_watchlist)
#
#       if qs_code == "MAJOR_CONFERENCE_LOW":
#           # Discovery only: update the trial watchlist for the next run,
#           # do not route to Pass 1 or Pass 2.
#           trial_name = _extract_trial_name_from_title(candidate.title or "")
#           if trial_name:
#               stats.conf_low_trial_names_discovered.append(trial_name)
#           stats.conf_low_discovery_count += 1
#           log.debug(
#               "[%s] MAJOR_CONFERENCE_LOW routed to watchlist-only: %s",
#               site_code, candidate.pmid,
#           )
#           continue   # ← skip to next candidate, never reaches Pass 1/Pass 2
#
#       # MAJOR_CONFERENCE_HIGH falls through to normal Pass 1 → Pass 2 routing.
#       # confidence_source is already set to "late_breaking_abstract" by
#       # assign_confidence_source() at normalization time.
#
# NOTE: _extract_trial_name_from_title() can be a simple regex that matches
# all-caps acronyms of 3–10 characters, or you can reuse the trial_name
# field from Pass 2 of a prior run. Keep it lightweight — this runs before
# any LLM call.

def _extract_trial_name_from_title(title: str) -> str | None:
    """
    Attempt to extract a trial acronym from an abstract title.
    Used for MAJOR_CONFERENCE_LOW abstracts that go to watchlist-only.

    Matches patterns like:
      "LAURA trial: ...", "CheckMate 816 ...", "The PATHOS study ...",
      "FLAURA2: ...", "(NCT03521153) ..."
    """
    import re

    # Named trial acronyms: 3–10 uppercase letters, optionally followed by a digit
    acronym_re = re.compile(
        r"\b([A-Z]{3,10}\d{0,3})\b(?:\s*(?:trial|study|:))?",
        re.IGNORECASE,
    )
    # NCT number
    nct_re = re.compile(r"\b(NCT\d{8})\b")

    # NCT takes priority
    nct = nct_re.search(title)
    if nct:
        return nct.group(1)

    # Try acronym — skip common non-trial uppercase words
    _SKIP = frozenset({
        "ASCO", "ESMO", "ASTRO", "ASH", "AACR", "SABCS", "SITC",
        "FDA", "NCCN", "NEJM", "JCO", "JAMA", "BMJ",
        "RCT", "OS", "PFS", "DFS", "EFS", "ORR", "DCR", "pCR",
        "NSCLC", "SCLC", "GBM", "CLL", "AML", "CML", "MDS",
        "HR", "HER", "PDL", "MSI", "TMB",
    })

    for m in acronym_re.finditer(title):
        candidate = m.group(1).upper()
        if candidate not in _SKIP and len(candidate) >= 4:
            return candidate

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH 2: Journal force-keep guardrail
# ═══════════════════════════════════════════════════════════════════════════════
#
# LOCATION: In the QS_NONE routing block, wherever the existing code handles
# candidates with force_keep_reason set (top-journal override path).
#
# BEFORE (existing logic, conceptually):
#
#   if qs_code == "NONE" and candidate.force_keep_reason:
#       stats.qs_none_top_journal_count += 1
#       candidates_for_pass2.append(candidate)   # ← direct bypass to Pass 2
#
# AFTER:
#
#   from .filters.signal_score_additions import check_journal_force_guardrail
#
#   if qs_code == "NONE" and candidate.force_keep_reason:
#       passes_guardrail, guard_reason = check_journal_force_guardrail(
#           candidate,
#           relevance_floor=config.journal_force_relevance_floor,  # default 35
#       )
#       if passes_guardrail:
#           # Journal override confirmed: direct to Pass 2 as before
#           stats.qs_none_top_journal_count += 1
#           candidates_for_pass2.append(candidate)
#       else:
#           # Guardrail failed: demote to mini-triage
#           log.info(
#               "[%s] journal_force_guardrail demoted %s to mini-triage: %s",
#               site_code, candidate.pmid, guard_reason,
#           )
#           stats.qs_none_guardrail_demoted = getattr(stats, "qs_none_guardrail_demoted", 0) + 1
#           # Falls through to normal QS_NONE mini-triage routing below
#           candidates_for_minitriage.append(candidate)


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH 3: Discovery-only source guard (before Pass 2 queue)
# ═══════════════════════════════════════════════════════════════════════════════
#
# LOCATION: Just before appending a candidate to candidates_for_pass2, add a
# check that blocks discovery-only sources from reaching Pass 2.
# (tier_logic.py also blocks them, but blocking here avoids the LLM cost.)
#
# BEFORE:
#
#   candidates_for_pass2.append(candidate)
#
# AFTER:
#
#   from .signal import DISCOVERY_ONLY_SOURCES
#
#   if candidate.confidence_source in DISCOVERY_ONLY_SOURCES:
#       # Source cannot generate a card. Add to watchlist if it has a trial name.
#       trial_name = _extract_trial_name_from_title(candidate.title or "")
#       if trial_name:
#           stats.discovery_only_trial_names = (
#               getattr(stats, "discovery_only_trial_names", []) + [trial_name]
#           )
#       stats.discovery_only_blocked = getattr(stats, "discovery_only_blocked", 0) + 1
#       log.debug(
#           "[%s] discovery_only blocked from Pass 2: source=%s pmid=%s",
#           site_code, candidate.confidence_source, candidate.pmid,
#       )
#       continue   # ← skip Pass 2 entirely
#
#   candidates_for_pass2.append(candidate)   # ← unchanged for all other sources
