"""
Conference abstract retrieval module.

Major oncology meetings publish abstracts in supplement issues of PubMed-indexed
journals. This module maintains a meeting calendar and constructs targeted PubMed
queries that run alongside the main weekly sweep, using a wider date window around
each meeting's publication month so supplements aren't missed.

Meetings covered:
  ASCO Annual Meeting     → Journal of Clinical Oncology suppl      (May/June)
  ASCO GU Symposium       → Journal of Clinical Oncology suppl      (February)
  ASCO Breast Symposium   → Journal of Clinical Oncology suppl      (October)
  ESMO Congress           → Annals of Oncology suppl                (September)
  ESMO Breast Congress    → Annals of Oncology suppl                (May)
  ASTRO Annual Meeting    → Int J Radiat Oncol Biol Phys suppl      (October)
  ASH Annual Meeting      → Blood suppl                             (December)
  AACR Annual Meeting     → Cancer Research suppl                   (April)
  SGO Annual Meeting      → Gynecologic Oncology suppl              (March)
  SITC Annual Meeting     → J ImmunoTherapy Cancer suppl            (November)

Usage:
    from .conferences import get_active_meetings, build_conference_queries
    from .pubmed import PubMedClient

    meetings = get_active_meetings(reference_date=date.today(), lookback_days=35)
    for meeting, query in build_conference_queries(meetings, site):
        pmids = pubmed_client.esearch(query, retmax=500)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from .pubmed import PubMedClient, PubMedRecord
from ..disease_sites.base import DiseaseSiteConfig, _or_block

log = logging.getLogger("carcinos.conferences")


# ---------------------------------------------------------------------------
# Meeting calendar
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConferenceMeeting:
    """Represents a recurring oncology conference."""
    name: str                           # e.g. "ASCO Annual Meeting"
    short_code: str                     # e.g. "ASCO"
    journal: str                        # PubMed [Journal] name for supplement
    pub_month: int                      # typical supplement publication month (1-12)
    window_days: int                    # days before/after pub_month start to search
    relevant_sites: tuple[str, ...] | None  # None = all 10 sites
    extra_mesh: tuple[str, ...] = ()    # additional MeSH headings to narrow by

    def is_active(self, reference_date: date, lookback_days: int = 35) -> bool:
        """
        Returns True if the reference_date falls within lookback_days of this
        meeting's typical supplement publication window.
        """
        year = reference_date.year
        # Check this year and previous year (for January runs catching Dec ASH)
        for y in (year, year - 1):
            try:
                meeting_pub = date(y, self.pub_month, 1)
            except ValueError:
                continue
            delta = (reference_date - meeting_pub).days
            if 0 <= delta <= lookback_days + self.window_days:
                return True
        return False

    def get_pub_window(self, reference_date: date, lookback_days: int = 35) -> tuple[date, date]:
        """
        Return the (start, end) date window to use in the PubMed query.
        """
        year = reference_date.year
        # Pick the most recent active year
        for y in (year, year - 1):
            try:
                meeting_pub = date(y, self.pub_month, 1)
            except ValueError:
                continue
            if (reference_date - meeting_pub).days >= 0:
                start = meeting_pub - timedelta(days=self.window_days)
                end = meeting_pub + timedelta(days=lookback_days)
                return start, min(end, reference_date)
        # Fallback: use broad window
        start = reference_date - timedelta(days=lookback_days + self.window_days)
        return start, reference_date


# The meeting registry. Supplement pub_month is when PubMed typically indexes
# the abstract supplement — usually 0-4 weeks after the live meeting.
MEETING_REGISTRY: tuple[ConferenceMeeting, ...] = (
    ConferenceMeeting(
        name="ASCO Annual Meeting",
        short_code="ASCO",
        journal="Journal of Clinical Oncology",
        pub_month=6,        # ASCO is late May; JCO suppl usually June
        window_days=14,
        relevant_sites=None,  # covers all solid tumor sites
    ),
    ConferenceMeeting(
        name="ASCO GU Symposium",
        short_code="ASCO_GU",
        journal="Journal of Clinical Oncology",
        pub_month=2,
        window_days=14,
        relevant_sites=("gu",),
    ),
    ConferenceMeeting(
        name="ASCO Breast Cancer Symposium",
        short_code="ASCO_Breast",
        journal="Journal of Clinical Oncology",
        pub_month=10,
        window_days=14,
        relevant_sites=("breast",),
    ),
    ConferenceMeeting(
        name="ESMO Congress",
        short_code="ESMO",
        journal="Annals of Oncology",
        pub_month=9,
        window_days=14,
        relevant_sites=None,
    ),
    ConferenceMeeting(
        name="ESMO Breast Cancer Congress",
        short_code="ESMO_Breast",
        journal="Annals of Oncology",
        pub_month=5,
        window_days=14,
        relevant_sites=("breast",),
    ),
    ConferenceMeeting(
        name="ASTRO Annual Meeting",
        short_code="ASTRO",
        journal="International Journal of Radiation Oncology Biology Physics",
        pub_month=10,
        window_days=14,
        relevant_sites=None,  # radiation spans all sites
    ),
    ConferenceMeeting(
        name="ASH Annual Meeting",
        short_code="ASH",
        journal="Blood",
        pub_month=12,
        window_days=14,
        relevant_sites=("hematologic",),
    ),
    ConferenceMeeting(
        name="AACR Annual Meeting",
        short_code="AACR",
        journal="Cancer Research",
        pub_month=4,
        window_days=14,
        relevant_sites=None,
    ),
    ConferenceMeeting(
        name="SGO Annual Meeting",
        short_code="SGO",
        journal="Gynecologic Oncology",
        pub_month=3,
        window_days=14,
        relevant_sites=("gynecologic",),
    ),
    ConferenceMeeting(
        name="SITC Annual Meeting",
        short_code="SITC",
        journal="Journal for ImmunoTherapy of Cancer",
        pub_month=11,
        window_days=14,
        relevant_sites=None,
    ),
)


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

def get_active_meetings(
    reference_date: date | None = None,
    lookback_days: int = 35,
    site_code: str | None = None,
) -> list[ConferenceMeeting]:
    """
    Return meetings whose supplement window overlaps the reference_date.
    Optionally filter to meetings relevant to a specific disease site.
    """
    if reference_date is None:
        reference_date = date.today()
    active = []
    for m in MEETING_REGISTRY:
        if not m.is_active(reference_date, lookback_days=lookback_days):
            continue
        if site_code and m.relevant_sites and site_code not in m.relevant_sites:
            continue
        active.append(m)
    return active


def build_conference_query(
    meeting: ConferenceMeeting,
    site: DiseaseSiteConfig,
    reference_date: date,
    lookback_days: int = 35,
) -> str:
    """
    Build a PubMed query for a specific meeting × disease site combination.

    Structure:
        (site core terms) AND (journal) AND (date window) AND "congress"[pt]
        AND (trial/results keywords — filters out educational talks and reviews)
    """
    start, end = meeting.get_pub_window(reference_date, lookback_days=lookback_days)

    date_str_start = start.strftime("%Y/%m/%d")
    date_str_end = end.strftime("%Y/%m/%d")
    # Use BOTH [Date - Publication] and [Date - Entrez] so epub-ahead abstracts
    # and recently indexed supplements are not missed. ASCO/ESMO supplements are
    # indexed in PubMed close to the meeting date but their print issue date is
    # set weeks later — [Date - Publication] alone misses them entirely.
    pub_range    = f'("{date_str_start}"[Date - Publication] : "{date_str_end}"[Date - Publication])'
    entrez_range = f'("{date_str_start}"[Date - Entrez] : "{date_str_end}"[Date - Entrez])'
    date_block   = f"({pub_range} OR {entrez_range})"

    journal_block = f'"{meeting.journal}"[Journal]'
    pubtype_block = '"congress"[Publication Type]'
    core_block = site.core_block()

    # Broad "science signal" filter. The previous version required trial/outcome
    # language (randomized / phase II-III / OS / PFS / FDA / approval / guideline),
    # which silently excluded translational and biomarker abstracts that never use
    # those words — a real recall hole at ASCO/ESMO. We now keep any abstract that
    # shows clinical OR translational substance and rely on the LLM-first pipeline
    # downstream to tier them. This still filters out pure educational sessions,
    # state-of-the-art talks, and disclosure/ethics items that dominate supplements.
    science_filter = (
        '('
        # Trial / outcome language (original terms, retained)
        '"randomized" OR "randomised" OR "phase 1" OR "phase I" OR '
        '"phase 2" OR "phase II" OR "phase 3" OR "phase III" OR '
        '"overall survival" OR "progression-free" OR "disease-free" OR '
        '"response rate" OR "hazard ratio" OR "FDA" OR "approval" OR "guideline" OR '
        # Translational / biomarker / molecular substance (newly added)
        '"biomarker" OR "translational" OR "molecular" OR "genomic" OR "mutation" OR '
        '"ctDNA" OR "circulating tumor" OR "minimal residual" OR "MRD" OR '
        '"immunotherapy" OR "antibody-drug conjugate" OR "CAR-T" OR '
        '"efficacy" OR "outcomes" OR "subgroup" OR "real-world"'
        ')'
    )

    return f"{core_block} AND {journal_block} AND {date_block} AND {pubtype_block} AND {science_filter}"


# ---------------------------------------------------------------------------
# Main retrieval entry point
# ---------------------------------------------------------------------------

def retrieve_conference_records(
    pubmed: PubMedClient,
    site: DiseaseSiteConfig,
    reference_date: date | None = None,
    lookback_days: int = 35,
    max_pmids: int = 300,
) -> list[PubMedRecord]:
    """
    Retrieve PubMed records for all active conferences relevant to this site.

    Returns a deduplicated list of PubMedRecord objects, ready to merge with
    the main pipeline's retrieval output before deduplication.
    """
    if reference_date is None:
        reference_date = date.today()

    active = get_active_meetings(
        reference_date=reference_date,
        lookback_days=lookback_days,
        site_code=site.code,
    )

    if not active:
        log.info("[%s] No active conferences in lookback window (%d days)", site.code, lookback_days)
        return []

    # Fetch per meeting so we can tag each record with its conference source
    pmid_to_source: dict[str, str] = {}
    for meeting in active:
        query = build_conference_query(meeting, site, reference_date, lookback_days=lookback_days)
        log.info("[%s] Conference query (%s): %s", site.code, meeting.short_code, query)
        pmids = pubmed.esearch(query, retmax=max_pmids)
        log.info("[%s] %s → %d PMIDs", site.code, meeting.short_code, len(pmids))
        for p in pmids:
            if p and p not in pmid_to_source:
                pmid_to_source[p] = meeting.short_code

    if not pmid_to_source:
        return []

    records = pubmed.efetch(list(pmid_to_source.keys()))
    # Tag each record with its conference source
    for r in records:
        r.conference_source = pmid_to_source.get(r.pmid)
    log.info("[%s] Conference lane: fetched %d records from %d meetings",
             site.code, len(records), len(active))
    return records
