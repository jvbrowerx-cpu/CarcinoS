"""
ASTRO Annual Meeting — direct abstract retrieval from the ASTRO portal.

Why this exists
---------------
ASTRO publishes its abstract supplement in the Red Journal
(Int J Radiat Oncol Biol Phys), but NLM typically indexes it 2–6 weeks
after the meeting opens. The ASTRO portal at amportal.astro.org makes
every abstract available the day the meeting opens, giving CarcinoS
same-day access to LBAs and proffered papers before they hit PubMed.

This module is intentionally separate from conferences.py (the generic
PubMed conference lane). conferences.py continues to run unchanged and will
eventually pick up the same papers once indexed; PMID-level dedup in run.py
prevents double-ingestion.

How it works
------------
1. Enumerate the catalog at https://amportal.astro.org/abstracts?page=N
   (42 pages as of ASTRO 2026) to collect all /sessions/ URLs.
2. For each URL, fetch the page and test for the four required structural
   sections (Purpose/Objective, Materials/Methods, Results, Conclusion).
   Pages that lack all four (Discussants, Introductions, Education sessions)
   are discarded.
3. Qualifying pages are parsed into PubMedRecord objects with:
     pmid              = "ASTRO{year}-{portal_id}"  (synthetic, unique)
     conference_source = "ASTRO"
     url_override      = the portal URL
   so that downstream dedup can match against real PubMed records once
   indexed, and the rendered alert links to the actual abstract.

Integration point
-----------------
Call retrieve_astro_records() from pipeline.py alongside the existing
conference lane. The returned list is prepended to conf_records so it
flows through the same LLM triage and scoring path as any other record.

Dedup key
---------
  conference      = "ASTRO"
  conference_year = str(year)          e.g. "2026"
  abstract_number = "LBA 03" / "179"  from the title prefix

When a PubMed record eventually appears for the same abstract, its
conference_source will be tagged "ASTRO" by conferences.py and the PMID
dedup in run.py prevents re-triage.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .pubmed import PubMedRecord

log = logging.getLogger("carcinos.astro")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTAL_BASE    = "https://amportal.astro.org"
CATALOG_URL    = f"{PORTAL_BASE}/abstracts"
MEETING_YEAR   = 2026          # update each year
MAX_PAGES      = 60            # safety cap — ASTRO 2026 has 42 pages
REQUEST_DELAY  = 0.5           # seconds between HTTP requests (be polite)
REQUEST_TIMEOUT = 20

# Structural section markers.  All four must be present to count as a
# scientific abstract.  We use lowercase for matching.
REQUIRED_SECTIONS = (
    "purpose/objective",
    "materials/methods",
    "results:",
    "conclusion",
)

# Session URL pattern — every abstract lives under /sessions/
_SESSION_RE = re.compile(r"/sessions/[^\"'\s]+")

# Abstract number at the start of a title, e.g. "LBA 03 - ", "179 - "
_ABSTRACT_NUM_RE = re.compile(r"^\s*((?:LBA\s+)?\d+[a-zA-Z]?)\s*-\s*", re.IGNORECASE)

# User-Agent — identify ourselves politely
_UA = (
    "CarcinoS-Pipeline/1.0 (oncology literature pipeline; "
    "contact carcinos@pipeline.internal)"
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, session: requests.Session) -> Optional[requests.Response]:
    """GET with retry on transient errors; returns None on persistent failure."""
    for attempt in range(3):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": _UA})
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt * 2)
                continue
            log.warning("ASTRO: HTTP %d for %s", r.status_code, url)
            return None
        except requests.RequestException as exc:
            log.warning("ASTRO: request error (%s) for %s (attempt %d)", exc, url, attempt + 1)
            time.sleep(1)
    return None


# ---------------------------------------------------------------------------
# Catalog enumeration
# ---------------------------------------------------------------------------

def _collect_session_urls(
    session: requests.Session,
    max_pages: int = MAX_PAGES,
) -> list[str]:
    """
    Walk the abstract catalog and return all /sessions/ URLs found.

    The catalog is paginated: ?page=N.  We stop when a page returns no
    session links or we hit max_pages.
    """
    seen: set[str] = set()
    ordered: list[str] = []

    for page_num in range(1, max_pages + 1):
        url = CATALOG_URL if page_num == 1 else f"{CATALOG_URL}?page={page_num}"
        log.debug("ASTRO catalog page %d: %s", page_num, url)

        resp = _get(url, session)
        if resp is None:
            log.warning("ASTRO: catalog page %d failed — stopping enumeration", page_num)
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        links = [
            a["href"] for a in soup.find_all("a", href=_SESSION_RE)
            if a.get("href", "").startswith("/sessions/")
        ]

        new_links = [l for l in links if l not in seen]
        if not new_links:
            log.info("ASTRO: page %d returned no new links — catalog exhausted", page_num)
            break

        for l in new_links:
            seen.add(l)
            ordered.append(urljoin(PORTAL_BASE, l))

        time.sleep(REQUEST_DELAY)

    log.info("ASTRO: collected %d session URLs across catalog", len(ordered))
    return ordered


# ---------------------------------------------------------------------------
# Abstract page parsing
# ---------------------------------------------------------------------------

def _parse_abstract_page(html: str, url: str) -> Optional[PubMedRecord]:
    """
    Parse one ASTRO session page and return a PubMedRecord if it is a
    scientific abstract (has all four required sections).

    Returns None for Discussants, Introductions, or pages with no abstract.
    """
    soup = BeautifulSoup(html, "html.parser")
    text_lower = soup.get_text(" ").lower()

    # Structural gate: must have all four required sections
    if not all(sec in text_lower for sec in REQUIRED_SECTIONS):
        return None

    # ── Title and abstract number ─────────────────────────────────────────
    # Title is in <h1> inside .session__presentations-wrapper, prefixed with
    # the abstract number: "LBA 03 - SWOG S1827/MAVERICK: ..."
    h1 = None
    wrapper = soup.find(class_="session__presentations-wrapper")
    if wrapper:
        h1 = wrapper.find("h1")
    if h1 is None:
        h1 = soup.find("h1")

    raw_title = h1.get_text(" ", strip=True) if h1 else ""
    abstract_number = ""
    clean_title = raw_title
    m = _ABSTRACT_NUM_RE.match(raw_title)
    if m:
        abstract_number = m.group(1).strip()
        clean_title = raw_title[m.end():].strip()

    if not clean_title:
        return None   # no parseable title — skip

    # ── Abstract sections ─────────────────────────────────────────────────
    # The abstract body is structured with <b> labels followed by text.
    # We walk the content and stitch sections together.
    abstract = _extract_abstract_sections(soup)

    # ── Authors ───────────────────────────────────────────────────────────
    # First <p> in the abstract area contains the author list in the form
    # "A. Author1, B. Author2, ..."
    authors = _extract_authors(soup)

    # ── Presenter ─────────────────────────────────────────────────────────
    # .session__presentations-info contains "Presenter(s)" h2 + <a> links
    presenters = _extract_presenters(soup)

    # ── Portal ID and synthetic PMID ─────────────────────────────────────
    # The portal ID is the last numeric token in the URL slug, e.g. 114268
    portal_id = _portal_id_from_url(url)
    synthetic_pmid = f"ASTRO{MEETING_YEAR}-{portal_id}" if portal_id else (
        f"ASTRO{MEETING_YEAR}-{hashlib.md5(url.encode()).hexdigest()[:8]}"
    )

    # ── Session date ──────────────────────────────────────────────────────
    pub_date = _extract_session_date(soup)

    # ── Text hash ─────────────────────────────────────────────────────────
    text_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

    return PubMedRecord(
        pmid=synthetic_pmid,
        title=clean_title,
        abstract=abstract,
        journal="International Journal of Radiation Oncology Biology Physics",
        pub_date=pub_date,
        publication_types=["Congress"],
        doi=None,
        pmc_id=None,
        nct_ids=_extract_nct_ids(abstract),
        authors=authors if authors else presenters,
        language="eng",
        raw_xml="",          # no XML for portal records
        text_hash=text_hash,
        entrez_date="",      # not a PubMed record
        conference_source="ASTRO",
        url_override=url,
    )


def _extract_abstract_sections(soup: BeautifulSoup) -> str:
    """
    Walk the DOM and reconstruct the abstract text section by section.

    The portal renders each section label as a standalone <b> tag followed
    by a sequence of text nodes / <br> / <p> elements.  We collect text
    until the next <b> section header.
    """
    section_labels = {
        "Purpose/Objective(s):",
        "Purpose/Objectives:",
        "Materials/Methods:",
        "Results:",
        "Conclusion:",
        "Conclusions:",
    }

    parts: list[str] = []
    # Find all <b> tags that are section labels
    for b_tag in soup.find_all("b"):
        label_text = b_tag.get_text(strip=True)
        if not any(label_text.startswith(lbl.rstrip(":")) for lbl in section_labels):
            continue

        # Collect text that follows this <b> until the next sibling <b>
        section_text_parts: list[str] = [label_text]
        for sibling in b_tag.next_siblings:
            # Stop if we hit another section <b>
            if sibling.name == "b" and sibling.get_text(strip=True) in section_labels:
                break
            if hasattr(sibling, "get_text"):
                t = sibling.get_text(" ", strip=True)
                if t:
                    section_text_parts.append(t)
            elif isinstance(sibling, str):
                t = sibling.strip()
                if t:
                    section_text_parts.append(t)
        parts.append(" ".join(section_text_parts))

    return "\n\n".join(parts)


def _extract_authors(soup: BeautifulSoup) -> list[str]:
    """
    Extract the full author list from the first <p> in the abstract area.

    ASTRO uses superscript affiliation numbers; we strip them and parse
    "Last Initials" style names separated by commas.
    """
    # The author paragraph is the first <p> inside the abstract block,
    # before the section <b> tags.
    for p in soup.find_all("p"):
        # Strip superscripts and underlines (presenter underline)
        for tag in p.find_all(["sup", "u"]):
            tag.decompose()
        text = p.get_text(", ", strip=True)
        # Heuristic: author lists have commas and capital initials like "A. B, C. D"
        if "," in text and len(text) > 10:
            # Split on "; " or on ","
            raw = re.split(r"[;,]\s*", text)
            names = [n.strip() for n in raw if re.match(r"^[A-Z]", n.strip())]
            if len(names) >= 2:
                return names[:30]  # cap at 30 authors
    return []


def _extract_presenters(soup: BeautifulSoup) -> list[str]:
    """Extract named presenters from the Presenter(s) block."""
    h2 = soup.find("h2", string=re.compile(r"Presenter", re.I))
    if h2 is None:
        return []
    presenters = []
    for a in h2.find_next_siblings("a"):
        name = a.get_text(strip=True)
        if name:
            presenters.append(name)
    return presenters


def _extract_session_date(soup: BeautifulSoup) -> str:
    """Extract the session date (e.g. 'Sep 27') and return as YYYY-MM-DD."""
    # .session__presentations-date contains "Sep" and a big-number day
    date_div = soup.find(class_="session__presentations-date")
    if date_div is None:
        return f"{MEETING_YEAR}"
    text = date_div.get_text(" ", strip=True)  # e.g. "Sep 27"
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", text, re.I)
    if m:
        month_str = m.group(1).lower()[:3]
        month_map = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04",
            "may": "05", "jun": "06", "jul": "07", "aug": "08",
            "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }
        mm = month_map.get(month_str, "09")
        dd = m.group(2).zfill(2)
        return f"{MEETING_YEAR}-{mm}-{dd}"
    return f"{MEETING_YEAR}"


def _portal_id_from_url(url: str) -> str:
    """Extract the numeric portal ID from the tail of a session URL."""
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-(\d{5,8})$", slug)
    return m.group(1) if m else ""


def _extract_nct_ids(text: str) -> list[str]:
    """Extract ClinicalTrials.gov NCT IDs from abstract text."""
    return re.findall(r"\bNCT\d{8}\b", text, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Disease-site filtering
# ---------------------------------------------------------------------------

def _abstract_matches_site(record: PubMedRecord, site) -> bool:
    """
    Return True if this abstract is relevant to the given disease site.

    Uses the same SITE_QUICK_TERMS approach as the FDA lane: any quick
    term found in title+abstract qualifies.  Sites with no quick terms
    (site_code not in SITE_QUICK_TERMS) receive all abstracts.
    """
    from ..disease_sites.base import SITE_QUICK_TERMS  # avoid circular import at module load

    terms = SITE_QUICK_TERMS.get(site.code, [])
    if not terms:
        return True
    haystack = f"{record.title} {record.abstract}".lower()
    return any(t.lower() in haystack for t in terms)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def retrieve_astro_records(
    site,
    reference_date: Optional[date] = None,
    max_pages: int = MAX_PAGES,
) -> list[PubMedRecord]:
    """
    Retrieve ASTRO abstract records from the portal for the given disease site.

    This function:
      1. Checks that the current date falls within the ASTRO meeting window
         (Sep 27 – Oct 30, MEETING_YEAR).  Outside this window it returns []
         immediately — no network calls.
      2. Enumerates the catalog to collect all session URLs.
      3. Fetches and parses each session page.
      4. Filters by structural abstract sections and site relevance.
      5. Returns a list of PubMedRecord objects tagged conference_source="ASTRO".

    Parameters
    ----------
    site : DiseaseSiteConfig
        The current disease site being processed.
    reference_date : date, optional
        Defaults to today.  Used to gate the meeting window.
    max_pages : int
        Safety cap on catalog pages to enumerate.
    """
    if reference_date is None:
        reference_date = date.today()

    # Gate: only run during the ASTRO meeting window
    window_start = date(MEETING_YEAR, 9, 25)   # 2 days before meeting opens
    window_end   = date(MEETING_YEAR, 11, 5)   # ~5 weeks post-meeting
    if not (window_start <= reference_date <= window_end):
        log.info(
            "[%s] ASTRO direct lane: outside meeting window (%s – %s) — skipping",
            site.code, window_start, window_end,
        )
        return []

    log.info("[%s] ASTRO direct lane: starting catalog enumeration", site.code)

    with requests.Session() as http:
        session_urls = _collect_session_urls(http, max_pages=max_pages)

        records: list[PubMedRecord] = []
        n_skipped = 0
        for i, url in enumerate(session_urls):
            resp = _get(url, http)
            if resp is None:
                n_skipped += 1
                continue

            record = _parse_abstract_page(resp.text, url)
            if record is None:
                n_skipped += 1
                continue

            if not _abstract_matches_site(record, site):
                continue

            records.append(record)
            time.sleep(REQUEST_DELAY)

            if (i + 1) % 50 == 0:
                log.info(
                    "[%s] ASTRO direct lane: processed %d/%d URLs, %d records so far",
                    site.code, i + 1, len(session_urls), len(records),
                )

    log.info(
        "[%s] ASTRO direct lane: %d qualifying records from %d URLs (%d skipped/failed)",
        site.code, len(records), len(session_urls), n_skipped,
    )
    return records
