"""
FDA Oncology approvals ingestion lane.

Monitors the FDA press releases RSS feed filtered for oncology approvals.
Records are returned as synthetic PubMedRecord objects tagged with
  publication_types = ["FDA Drug Approval"]
  conference_source = "FDA"

The pipeline treats conference_source == "FDA" as force-keep, so these
records bypass signal scoring and go directly to Pass 2 for summarisation.

RSS source:
  https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml

A record is included only if it matches BOTH:
  1. An oncology term (cancer type present in title/summary)
  2. An approval/label term (confirms it is an actual regulatory event)

Usage:
    from .fda import retrieve_fda_records
    records = retrieve_fda_records(lookback_days=7)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

from .pubmed import PubMedRecord

log = logging.getLogger("carcinos.fda")

# FDA RSS feeds.
#
# We consume TWO feeds and merge them because the FDA publishes drug approval
# notifications on a different content stream from press releases:
#
#   1. Drug approvals & databases RSS — the canonical source for ALL drug
#      approval notifications (NDA, BLA, sNDA, accelerated approval). This
#      is the feed that posts entries like "FDA approves capivasertib for
#      PTEN-deficient prostate cancer." It is updated within hours of each
#      approval action and covers approvals that never get a press release.
#
#   2. Press releases RSS — covers major label changes and breakthrough
#      therapy designations that get a dedicated FDA news item. Overlaps
#      with feed #1 for blockbuster approvals; adds context on safety signals
#      and policy decisions not covered by the drug approval notifications.
#
# Using only the press releases RSS (the previous behaviour) missed the
# majority of approvals — particularly accelerated approvals and label
# expansions that do not warrant a full press release.
FDA_DRUG_APPROVALS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/drug-approvals-and-databases/rss.xml"
)
FDA_PRESS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/press-releases/rss.xml"
)
_ALL_FDA_FEEDS = [FDA_DRUG_APPROVALS_RSS, FDA_PRESS_RSS]

# Cancer type terms — at least one must appear in the record text
_ONCO_RE = re.compile(
    r"\b("
    r"cancer|carcinoma|lymphoma|leukemia|leukaemia|myeloma|melanoma"
    r"|sarcoma|glioma|glioblastoma|tumor|tumour|oncol|neoplasm"
    r"|malignant|malignancy|metastatic|metastasis"
    r"|breast|lung|colon|colorectal|rectal|ovarian|cervical|endometrial"
    r"|uterine|prostate|bladder|renal|kidney|hepatocellular|pancreatic"
    r"|gastric|esophageal|biliary|cholangiocarcinoma"
    r"|head.{1,5}neck|laryngeal|oropharyngeal|nasopharyngeal|thyroid"
    r"|glioblastoma|gbm|astrocytoma|medulloblastoma"
    r"|sarcoma|gist|osteosarcoma"
    r"|nsclc|sclc|mesothelioma|thymoma"
    r"|cll|aml|cml|dlbcl|mds|myelofibrosis|myelodysplastic"
    r"|merkel|cutaneous"
    r")\b",
    re.IGNORECASE,
)

# Regulatory event terms — at least one must appear
_APPROVAL_RE = re.compile(
    r"\b("
    r"approv|granted|clearance|label.{1,10}update|label.{1,10}change"
    r"|new indication|indication.{1,10}expand|expanded indication"
    r"|priority review|breakthrough therapy|accelerated approval"
    r"|regular approval|full approval|biologics license"
    r"|supplemental.{1,10}application|sNDA|sBLA|NDA|BLA"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class FDAItem:
    """Parsed FDA press release item before conversion to PubMedRecord."""
    uid: str            # sha256[:16] of the URL
    title: str
    summary: str
    url: str
    pub_date: str       # ISO 8601 (YYYY-MM-DD) or ""


def _fetch_feed(url: str, timeout: int = 20) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of entry dicts."""
    try:
        import feedparser  # type: ignore
    except ImportError:
        log.warning(
            "feedparser not installed — FDA lane disabled. "
            "Run: pip install feedparser"
        )
        return []

    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "CarcinoS/1.0"})
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    except Exception as exc:
        log.warning("FDA RSS fetch failed (%s): %s", url, exc)
        return []

    return feed.entries


def _fetch_all_feeds(timeout: int = 20) -> list[dict]:
    """
    Fetch all FDA RSS feeds and return a deduplicated list of entries.
    Entries are deduplicated by URL so that approvals covered by both the
    drug approvals feed and the press releases feed appear only once.
    """
    seen_urls: set[str] = set()
    all_entries: list[dict] = []
    for feed_url in _ALL_FDA_FEEDS:
        for entry in _fetch_feed(feed_url, timeout=timeout):
            url = (getattr(entry, "link", None) or "").strip()
            if url and url in seen_urls:
                continue
            seen_urls.add(url)
            all_entries.append(entry)
    return all_entries


def _enrich_abstract(url: str, existing_summary: str, timeout: int = 10) -> str:
    """
    Fetch the FDA approval notification page and extract the indication text.

    FDA approval notification pages (fda.gov/drugs/resources-information-
    approved-drugs/fda-approves-...) contain a structured indication paragraph
    immediately after the approval date. This is far more useful for Pass 2
    than the thin RSS summary (which is usually just the title restated).

    Falls back to `existing_summary` on any error.
    """
    if not url or "fda.gov" not in url:
        return existing_summary

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "CarcinoS/1.0"},
        )
        resp.raise_for_status()
        text = resp.text

        # The approval pages follow a consistent structure:
        # <div class="lcds-text-passage"> ... <p>Drug (Brand, Sponsor) is approved for ...</p>
        # We extract all <p> content in the first ~3000 chars of the main body.
        import re as _re
        # Strip HTML tags
        stripped = _re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace
        stripped = " ".join(stripped.split())

        # Find the indication sentence — typically starts with "FDA approved" or
        # the drug name followed by "is approved for"
        indication_match = _re.search(
            r"(FDA approved\s.{20,600}?\.)",
            stripped,
            _re.IGNORECASE,
        )
        if indication_match:
            indication = indication_match.group(1).strip()
            # Append the first ~500 chars of body for additional context
            body_start = stripped.find(indication)
            context = stripped[body_start:body_start + 800].strip()
            return context if len(context) > len(existing_summary) else existing_summary

    except Exception as exc:
        log.debug("FDA abstract enrichment failed for %s: %s", url, exc)

    return existing_summary


def _parse_date(entry) -> tuple[Optional[date], str]:
    """Extract publication date from a feedparser entry."""
    try:
        raw = getattr(entry, "published", None) or getattr(entry, "updated", None)
        if raw:
            dt = parsedate_to_datetime(raw)
            d = dt.date()
            return d, d.isoformat()
    except Exception:
        pass
    return None, ""


def fetch_fda_oncology_items(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
) -> list[FDAItem]:
    """
    Fetch FDA drug approval and press release entries from ALL configured RSS
    feeds, filter for oncology approvals within the lookback window, and
    optionally enrich each item's summary by fetching the linked approval page.

    Args:
        lookback_days:    How many days back to look (default 7).
        reference_date:   Window end (default today).
        enrich_abstracts: If True, fetch the linked FDA approval page for each
                          item to extract the full indication text as the abstract.
                          Adds one HTTP request per item (~10 items/week at most).
                          Set to False in unit tests or cost-sensitive dry runs.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    entries = _fetch_all_feeds()
    if not entries:
        return []

    items: list[FDAItem] = []
    for entry in entries:
        pub_date, pub_date_str = _parse_date(entry)

        # Skip items outside the window (if date is parseable)
        if pub_date and pub_date < cutoff:
            continue

        title   = (getattr(entry, "title",   None) or "").strip()
        summary = (getattr(entry, "summary", None)
                   or getattr(entry, "description", None) or "").strip()
        url     = (getattr(entry, "link",    None) or "").strip()

        combined = f"{title} {summary}"

        if not _ONCO_RE.search(combined):
            continue
        if not _APPROVAL_RE.search(combined):
            continue

        # Enrich the abstract by fetching the actual approval notification page.
        # RSS summaries for drug approvals are typically just the title re-stated;
        # the approval page contains the full indication, drug name, and sponsor.
        if enrich_abstracts and url:
            summary = _enrich_abstract(url, summary)

        uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        items.append(FDAItem(
            uid=uid,
            title=title,
            summary=summary,
            url=url,
            pub_date=pub_date_str,
        ))

    log.info(
        "FDA lane: %d oncology approval items (lookback=%dd, enriched=%s, from %d total RSS entries)",
        len(items), lookback_days, enrich_abstracts, len(entries),
    )
    return items


def _item_to_pubmed_record(item: FDAItem) -> PubMedRecord:
    """
    Convert an FDAItem to a synthetic PubMedRecord so it flows through the
    standard pipeline. Key tags:
      - publication_types = ["FDA Drug Approval"]  → pubtype filter passes it
      - conference_source = "FDA"                  → pipeline force-keeps it
      - pmid = ""                                  → no PubMed identity
    """
    raw = f"FDA|{item.url}|{item.title}"
    text_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return PubMedRecord(
        pmid="",
        title=item.title,
        abstract=item.summary,
        journal="FDA Hematology-Oncology",
        pub_date=item.pub_date,
        publication_types=["FDA Drug Approval"],
        doi=None,
        pmc_id=None,
        nct_ids=[],
        mesh_terms=[],
        authors=["U.S. Food and Drug Administration"],
        language="eng",
        raw_xml=raw,
        text_hash=text_hash,
        conference_source="FDA",
    )


def retrieve_fda_records(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
) -> list[PubMedRecord]:
    """
    Main entry point for the FDA ingestion lane.
    Returns synthetic PubMedRecord objects ready to merge into the pipeline.
    """
    items = fetch_fda_oncology_items(
        lookback_days=lookback_days,
        reference_date=reference_date,
        enrich_abstracts=enrich_abstracts,
    )
    return [_item_to_pubmed_record(item) for item in items]
