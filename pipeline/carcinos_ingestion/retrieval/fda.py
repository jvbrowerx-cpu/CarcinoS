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

# FDA press releases RSS — all FDA news, we filter below
FDA_PRESS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/press-releases/rss.xml"
)

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
) -> list[FDAItem]:
    """
    Fetch FDA press releases from RSS and return only oncology approval items
    published within the lookback window.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    entries = _fetch_feed(FDA_PRESS_RSS)
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

        uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        items.append(FDAItem(
            uid=uid,
            title=title,
            summary=summary,
            url=url,
            pub_date=pub_date_str,
        ))

    log.info(
        "FDA lane: %d oncology approval items (lookback=%dd, from %d total RSS entries)",
        len(items), lookback_days, len(entries),
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
) -> list[PubMedRecord]:
    """
    Main entry point for the FDA ingestion lane.
    Returns synthetic PubMedRecord objects ready to merge into the pipeline.
    """
    items = fetch_fda_oncology_items(
        lookback_days=lookback_days,
        reference_date=reference_date,
    )
    return [_item_to_pubmed_record(item) for item in items]
