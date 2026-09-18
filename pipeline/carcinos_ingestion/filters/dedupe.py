"""
Deterministic dedupe (spec §2.1).

Two passes:
  1. Hard dedupe — drop on exact ID collision (DOI, PMID, NCT)
  2. Fuzzy dedupe — collapse if title similarity >= 0.92 AND pub dates within ±7 days

When fuzzy collapsing, keep the "best" copy:
  - Has abstract over no-abstract
  - Higher journal rank (lower index in JOURNAL_RANK)
  - PMC full text available

This runs BEFORE the LLM ever sees a record.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Iterable, Optional

from ..retrieval.pubmed import PubMedRecord


# Top-tier journals get lower numbers (= higher rank). This is *only* used as
# a tiebreaker in fuzzy dedupe — it does NOT decide what gets kept overall.
JOURNAL_RANK = [
    "New England Journal of Medicine",
    "Lancet",
    "Lancet Oncology",
    "JAMA",
    "JAMA Oncology",
    "Journal of Clinical Oncology",
    "Nature Medicine",
    "Nature Cancer",
    "Annals of Oncology",
    "Blood",
    "European Urology",
    "Journal of Thoracic Oncology",
    "Gut",
    "Hepatology",
    "Journal of Hepatology",
    "Lancet Haematology",
    "Lancet Gastroenterology and Hepatology",
    "Neuro-Oncology",
    "International Journal of Radiation Oncology Biology Physics",
    "Radiotherapy and Oncology",
    "Gynecologic Oncology",
    "Head & Neck",
    "Oral Oncology",
    "Breast Cancer Research and Treatment",
    "Leukemia",
    "Cancer",
    "JNCI",
]
_RANK_LOOKUP = {j.lower(): i for i, j in enumerate(JOURNAL_RANK)}
_DEFAULT_RANK = len(JOURNAL_RANK) + 100


def journal_rank(journal: str) -> int:
    if not journal:
        return _DEFAULT_RANK
    j = journal.lower()
    if j in _RANK_LOOKUP:
        return _RANK_LOOKUP[j]
    # Loose contains match: "Lancet Oncol" → "lancet oncology" wins.
    for name, rank in _RANK_LOOKUP.items():
        if name in j or j in name:
            return rank
    return _DEFAULT_RANK


# ---------------------------------------------------------------------------
# Hard dedupe (exact ID collisions)
# ---------------------------------------------------------------------------

def hard_dedupe(records: Iterable[PubMedRecord]) -> list[PubMedRecord]:
    """Drop exact-ID duplicates. PMID is unique within PubMed but DOI / NCT
    can collide across multiple PMIDs (errata, ahead-of-print + print)."""
    by_pmid: dict[str, PubMedRecord] = {}
    by_doi: dict[str, str] = {}                # doi → pmid kept

    for r in records:
        if r.pmid in by_pmid:
            continue
        if r.doi:
            doi_key = r.doi.lower()
            if doi_key in by_doi:
                # Already have this DOI — keep whichever wins on quality.
                existing = by_pmid[by_doi[doi_key]]
                if _quality_score(r) > _quality_score(existing):
                    by_pmid.pop(by_doi[doi_key], None)
                    by_pmid[r.pmid] = r
                    by_doi[doi_key] = r.pmid
                continue
            by_doi[doi_key] = r.pmid
        by_pmid[r.pmid] = r

    return list(by_pmid.values())


# ---------------------------------------------------------------------------
# Fuzzy dedupe
# ---------------------------------------------------------------------------

def fuzzy_dedupe(
    records: list[PubMedRecord],
    title_threshold: float = 0.92,
    date_window_days: int = 7,
) -> list[PubMedRecord]:
    """Collapse near-duplicate records (early online vs print, abstract vs paper)."""
    sorted_recs = sorted(records, key=lambda r: -_quality_score(r))
    kept: list[PubMedRecord] = []

    for r in sorted_recs:
        is_dup = False
        for k in kept:
            sim = _title_similarity(r.title, k.title)
            if sim >= title_threshold:
                if _within_window(r.pub_date, k.pub_date, date_window_days):
                    is_dup = True
                    break
        if not is_dup:
            kept.append(r)
    return kept


def _quality_score(r: PubMedRecord) -> float:
    score = 0.0
    if r.abstract:
        score += 50
    if r.pmc_id:
        score += 5
    score += max(0, 50 - journal_rank(r.journal))
    return score


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def _normalize_title(t: str) -> str:
    return " ".join(t.lower().split())


def _within_window(d1: str, d2: str, days: int) -> bool:
    a = _parse_pubdate(d1)
    b = _parse_pubdate(d2)
    if a is None or b is None:
        # Be conservative: if we can't parse one of the dates, treat them as
        # *potentially* in-window so they get fuzzy-matched.
        return True
    return abs((a - b).days) <= days


def _parse_pubdate(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

def dedupe(records: Iterable[PubMedRecord]) -> list[PubMedRecord]:
    return fuzzy_dedupe(hard_dedupe(records))
