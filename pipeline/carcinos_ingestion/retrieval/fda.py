"""
FDA Oncology approvals ingestion lane.

PRIMARY SOURCE: HTML scrape of the FDA oncology approval notifications page.

  https://www.fda.gov/drugs/resources-information-approved-drugs/
      oncology-cancerhematologic-malignancies-approval-notifications

This page is the canonical, continuously updated table of ALL oncology drug
approvals, label expansions, and safety notifications. Each row already
contains the full indication text, so no secondary page fetches are needed.

FALLBACK: dual RSS feeds (drug-approvals + press-releases) used if the HTML
page is unreachable. The RSS feeds are less reliable (one is often empty,
the other returns gzip that some environments can't parse), so they are
secondary.

Records are returned as synthetic PubMedRecord objects tagged with:
  publication_types = ["FDA Drug Approval"]
  conference_source = "FDA"

The pipeline treats conference_source == "FDA" as force-keep, bypassing
signal scoring and going directly to Pass 2 for summarisation.

Usage:
    from .fda import retrieve_fda_records
    records = retrieve_fda_records(lookback_days=7)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from .pubmed import PubMedRecord

log = logging.getLogger("carcinos.fda")

# ── Source URLs ───────────────────────────────────────────────────────────────

# Primary: HTML approval notifications table (most reliable, most complete)
FDA_ONCO_APPROVALS_PAGE = (
    "https://www.fda.gov/drugs/resources-information-approved-drugs"
    "/oncology-cancerhematologic-malignancies-approval-notifications"
)

# Fallback: RSS feeds (use only if page scrape yields nothing)
FDA_DRUG_APPROVALS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/drug-approvals-and-databases/rss.xml"
)
FDA_PRESS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/press-releases/rss.xml"
)
_ALL_FDA_FEEDS = [FDA_DRUG_APPROVALS_RSS, FDA_PRESS_RSS]

# ── Oncology / approval filters ───────────────────────────────────────────────

_ONCO_RE = re.compile(
    r"\b("
    r"cancer|carcinoma|lymphoma|leukemia|leukaemia|myeloma|melanoma"
    r"|sarcoma|glioma|glioblastoma|tumor|tumour|oncol|neoplasm"
    r"|malignant|malignancy|metastatic|metastasis"
    r"|breast|lung|colon|colorectal|rectal|ovarian|cervical|endometrial"
    r"|uterine|prostate|bladder|renal|kidney|hepatocellular|pancreatic"
    r"|gastric|esophageal|biliary|cholangiocarcinoma"
    r"|head.{1,5}neck|laryngeal|oropharyngeal|nasopharyngeal|thyroid"
    r"|gbm|astrocytoma|medulloblastoma|gist|osteosarcoma"
    r"|nsclc|sclc|mesothelioma|thymoma"
    r"|cll|aml|cml|dlbcl|mds|myelofibrosis|myelodysplastic"
    r"|merkel|cutaneous|hematolog|haematolog"
    r")\b",
    re.IGNORECASE,
)

_APPROVAL_RE = re.compile(
    r"\b("
    r"approv|granted|clearance|label.{1,10}update|label.{1,10}change"
    r"|new indication|indication.{1,10}expand|expanded indication"
    r"|priority review|breakthrough therapy|accelerated approval"
    r"|regular approval|full approval|biologics license"
    r"|supplemental.{1,10}application|sNDA|sBLA|NDA|BLA"
    r"|safety.{1,10}notification|safety labeling"
    r")\b",
    re.IGNORECASE,
)

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FDAItem:
    """Parsed FDA approval record before conversion to PubMedRecord."""
    uid: str        # sha256[:16] of the URL
    title: str
    summary: str    # Full indication text (from page) or RSS summary
    url: str
    pub_date: str   # ISO 8601 (YYYY-MM-DD) or ""
    source: str     # "page" | "rss"


# ── Primary source: HTML table scraper ───────────────────────────────────────

# The approval page table columns:
#   col 0: <a href="/drugs/...">Title text</a>
#   col 1: Full description / indication text
#   col 2: Date like "6/12/2026"

_TD_RE    = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
_A_RE     = re.compile(r'href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_TAG_RE   = re.compile(r"<[^>]+>")
_WS_RE    = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _parse_fda_date(raw: str) -> tuple[Optional[date], str]:
    """Parse dates like '6/12/2026' or 'June 12, 2026'. Returns (date, iso_str)."""
    raw = raw.strip()
    # M/D/YYYY or M/DD/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return d, d.isoformat()
        except ValueError:
            pass
    # "Month D, YYYY"
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            d = datetime.strptime(raw, fmt).date()
            return d, d.isoformat()
        except ValueError:
            pass
    return None, ""


def _scrape_approval_page(
    cutoff: date,
    timeout: int = 20,
) -> list[FDAItem]:
    """
    Scrape the FDA oncology approval notifications HTML page.

    The page contains a table with one approval per row. Each row has:
      - A link to the approval-specific page (with the title as link text)
      - The full indication description text
      - The approval date

    We stop consuming rows once the date falls before `cutoff`, since the
    table is always ordered newest-first.
    """
    try:
        resp = requests.get(
            FDA_ONCO_APPROVALS_PAGE,
            timeout=timeout,
            headers={"User-Agent": "CarcinoS/1.0"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        log.warning("FDA approval page fetch failed: %s", exc)
        return []

    # Find the main content table. The page has exactly one data table.
    # Split into <tr> blocks and parse each.
    tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    if not tr_blocks:
        log.warning("FDA approval page: no <tr> blocks found")
        return []

    items: list[FDAItem] = []
    for tr in tr_blocks:
        tds = _TD_RE.findall(tr)
        if len(tds) < 3:
            continue

        # Column 0: link cell  →  extract href + title text
        link_cell = tds[0]
        a_match = _A_RE.search(link_cell)
        if not a_match:
            continue
        href  = a_match.group(1).strip()
        title = _strip_html(a_match.group(2))
        if not title:
            title = _strip_html(link_cell)

        # Build absolute URL
        if href.startswith("/"):
            url = "https://www.fda.gov" + href
        elif href.startswith("http"):
            url = href
        else:
            continue  # skip malformed

        # Column 1: description / indication text
        summary = _strip_html(tds[1])

        # Column 2: date
        raw_date = _strip_html(tds[2])
        pub_date_obj, pub_date_str = _parse_fda_date(raw_date)

        # Date filtering — if date parses and is before cutoff, stop (table is newest-first)
        if pub_date_obj and pub_date_obj < cutoff:
            break

        # Oncology / approval filter (belt-and-suspenders; the page is already oncology-only)
        combined = f"{title} {summary}"
        if not _ONCO_RE.search(combined) and not _APPROVAL_RE.search(combined):
            continue

        uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        items.append(FDAItem(
            uid=uid,
            title=title,
            summary=summary,
            url=url,
            pub_date=pub_date_str,
            source="page",
        ))

    log.info("FDA scraper: %d items from approval notifications page (cutoff=%s)",
             len(items), cutoff.isoformat())
    return items


# ── Fallback: RSS feeds ───────────────────────────────────────────────────────

def _fetch_rss_feed(url: str, timeout: int = 20) -> list:
    """Fetch and parse a single RSS feed. Returns feedparser entries."""
    try:
        import feedparser  # type: ignore
    except ImportError:
        log.warning("feedparser not installed — RSS fallback disabled. "
                    "Run: pip install feedparser")
        return []

    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "CarcinoS/1.0"})
        resp.raise_for_status()
        # feedparser can handle both text and bytes
        feed = feedparser.parse(resp.content)
        return feed.entries
    except Exception as exc:
        log.warning("FDA RSS fetch failed (%s): %s", url, exc)
        return []


def _fetch_rss_items(cutoff: date, timeout: int = 20) -> list[FDAItem]:
    """
    Fallback RSS ingestion. Fetches both FDA RSS feeds, deduplicates by URL,
    filters for oncology approvals within the date window.
    """
    from email.utils import parsedate_to_datetime

    seen_urls: set[str] = set()
    items: list[FDAItem] = []

    for feed_url in _ALL_FDA_FEEDS:
        for entry in _fetch_rss_feed(feed_url, timeout=timeout):
            url = (getattr(entry, "link", None) or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Date parsing
            pub_date_obj: Optional[date] = None
            pub_date_str = ""
            try:
                raw = (getattr(entry, "published", None)
                       or getattr(entry, "updated", None))
                if raw:
                    dt = parsedate_to_datetime(raw)
                    pub_date_obj = dt.date()
                    pub_date_str = pub_date_obj.isoformat()
            except Exception:
                pass

            if pub_date_obj and pub_date_obj < cutoff:
                continue

            title   = (getattr(entry, "title",   None) or "").strip()
            summary = (getattr(entry, "summary", None)
                       or getattr(entry, "description", None) or "").strip()

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
                source="rss",
            ))

    log.info("FDA RSS fallback: %d oncology items (cutoff=%s)", len(items), cutoff.isoformat())
    return items


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_fda_oncology_items(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,  # kept for API compat; page scrape already has full text
) -> list[FDAItem]:
    """
    Fetch FDA oncology approval items within the lookback window.

    Strategy:
      1. Scrape the oncology approval notifications HTML page (primary).
         The page description column already contains the full indication text.
      2. If the page scrape yields 0 items, fall back to dual RSS feeds.

    Args:
        lookback_days:    Days to look back (default 7).
        reference_date:   Window end date (default today).
        enrich_abstracts: Unused (kept for backward compat). Page scrape
                          already provides full indication text without a
                          secondary fetch.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    # Try primary source first
    items = _scrape_approval_page(cutoff=cutoff)

    # Fall back to RSS only if page scrape fails entirely
    if not items:
        log.warning("FDA page scrape returned 0 items — trying RSS fallback")
        items = _fetch_rss_items(cutoff=cutoff)

    # Deduplicate by URL (in case both sources somehow run)
    seen: set[str] = set()
    deduped: list[FDAItem] = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            deduped.append(item)

    log.info(
        "FDA lane total: %d oncology approval items "
        "(lookback=%dd, cutoff=%s, page=%d, rss=%d)",
        len(deduped),
        lookback_days,
        cutoff.isoformat(),
        sum(1 for i in deduped if i.source == "page"),
        sum(1 for i in deduped if i.source == "rss"),
    )
    return deduped


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
