"""
Publication-type filter (spec §2.3).

Always KEEP:
  - Randomized trials, Phase II/III, non-inferiority/equivalence
  - Meta-analyses, systematic reviews
  - Practice guidelines / consensus statements
  - FDA approvals / label changes (handled in metadata; pass through)
  - Population-based epi (SEER, registry studies)

KEEP-LOW-PRIORITY (pass through with `low_priority=True`):
  - Prospective cohort
  - QoL / toxicity / survivorship
  - Biomarker validation in human cohorts

AUTO-DROP:
  - Editorial, Comment, Letter (without original data)
  - Narrative reviews (i.e. Review NOT Systematic Review)
  - Opinion / Perspective

Whitelisted journals (force-keep) override the drop rule so guidelines and
consensus papers in major venues never get filtered out (spec §2.4).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from ..retrieval.pubmed import PubMedRecord


# PubMed PublicationType vocab (sample):
#   "Randomized Controlled Trial", "Clinical Trial, Phase III",
#   "Meta-Analysis", "Systematic Review", "Practice Guideline",
#   "Comment", "Editorial", "Letter", "Review", "Case Reports",
#   "Observational Study", "Multicenter Study"

KEEP_TYPES = {
    "randomized controlled trial",
    "clinical trial, phase ii",
    "clinical trial, phase iii",
    "clinical trial, phase iv",
    "controlled clinical trial",
    "equivalence trial",
    "pragmatic clinical trial",
    "meta-analysis",
    "systematic review",
    "practice guideline",
    "guideline",
    "consensus development conference",
    "consensus development conference, nih",
    "validation study",
    "evaluation study",
    "multicenter study",
    "observational study",
}

LOW_PRIORITY_TYPES = {
    "clinical trial",                   # generic — could be phase 1
    "clinical trial, phase i",
    "comparative study",
    "clinical study",
    "journal article",                  # default tag — keep but low priority
    "twin study",
    "clinical conference",
}

DROP_TYPES = {
    "editorial",
    "comment",
    "letter",
    "news",
    "biography",
    "personal narrative",
    "interview",
    "introductory journal article",
    "case reports",
    "review",                            # generic Review — narrative; force-keep overrides
    "historical article",
    "video-audio media",
}


@dataclass
class PubTypeDecision:
    keep: bool
    low_priority: bool
    rationale: str


def classify(record: PubMedRecord) -> PubTypeDecision:
    types = {pt.lower() for pt in record.publication_types}

    # Force-keep on positive signals
    keep_hits = types & KEEP_TYPES
    if keep_hits:
        return PubTypeDecision(
            keep=True, low_priority=False,
            rationale=f"matched keep type: {sorted(keep_hits)[0]}"
        )

    # Drop on clear negatives
    drop_hits = types & DROP_TYPES
    if drop_hits and not (types & LOW_PRIORITY_TYPES):
        return PubTypeDecision(
            keep=False, low_priority=False,
            rationale=f"matched drop type: {sorted(drop_hits)[0]}"
        )

    # Default: low priority pass-through
    low_hits = types & LOW_PRIORITY_TYPES
    return PubTypeDecision(
        keep=True, low_priority=True,
        rationale=f"low-priority type: {sorted(low_hits)[0] if low_hits else 'unspecified'}"
    )


def filter_by_pubtype(
    records: Iterable[PubMedRecord],
    journal_force_keep: list[str] | None = None,
) -> list[tuple[PubMedRecord, PubTypeDecision]]:
    """
    Apply publication-type filter, with journal-whitelist override.

    Returns list of (record, decision) for KEPT records only.
    """
    out: list[tuple[PubMedRecord, PubTypeDecision]] = []
    force_keep = list(journal_force_keep or [])
    for r in records:
        d = classify(r)
        if d.keep:
            out.append((r, d))
            continue
        # Force-keep override
        if r.matches_journal_whitelist(force_keep):
            out.append((r, PubTypeDecision(
                keep=True, low_priority=True,
                rationale=f"force-kept by journal whitelist (would-have-dropped: {d.rationale})"
            )))
    return out
