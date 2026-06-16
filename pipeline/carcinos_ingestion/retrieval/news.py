"""
Lane 6 — Hybrid Oncology News Monitoring Layer.

Architecture (two distinct tiers):

  PRIMARY FEEDS — high-trust early-access sources
  ─────────────────────────────────────────────
  Major journals (NEJM, Lancet Oncology, JCO, JAMA Oncology, IJROBP,
  Annals of Oncology) and society news feeds (ASCO, ESMO, ASTRO, AACR,
  NCCN) publish content before PubMed indexes it (typically 24–72h lag
  for journals; conference abstracts may never appear in PubMed at all).

  Primary records are converted to full PubMedRecord objects tagged with
    conference_source = "JOURNAL_EARLY_ACCESS"  (journals)
    conference_source = "SOCIETY_NEWS"          (ASCO/ESMO/ASTRO/AACR/NCCN)
  They flow through the normal Gate 1 → Gate 2 → Pass 2 pipeline and
  CAN become cards if they earn a qualifying signal.

  SECONDARY FEEDS — signal detection only, never create cards
  ──────────────────────────────────────────────────────────
  Oncology trade press (OncLive, Cancer Network, Medscape Oncology,
  Targeted Oncology, Fierce Biotech, Endpoints News, MedPage Today) is
  monitored purely for trial name / NCT discovery.

  Headlines are scanned for named trial patterns and NCT IDs. Any matches
  are injected into `effective_watched_trials` for the current run, so that
  PubMed or conference records mentioning the same trial score QS_WATCHED_TRIAL
  and surface normally through the evidence pipeline.

  Secondary sources NEVER create PubMedRecord objects. They cannot drive
  a card directly — they expand the pipeline's awareness of what to watch.

  Example:
    OncLive: "Phase III PEACE-3 positive in metastatic CRPC"
    → "PEACE-3" extracted → added to watched_trials
    → If PEACE-3 appears in a JCO abstract or ESMO abstract this week,
      that record scores QS_WATCHED_TRIAL → flows to Pass 2 → card

Design rationale:
  The clinical oncology discovery cycle runs:
    Conference presentation → trade press coverage
      → journal publication → PubMed indexing → guideline adoption
  Systems that only monitor PubMed join the story halfway through.
  Lane 6 catches the earlier phases without letting trade press
  directly pollute the evidence-graded card feed.
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

log = logging.getLogger("carcinos.news")


# ── PRIMARY FEEDS ────────────────────────────────────────────────────────────
# These produce PubMedRecord objects that can become cards.
# Source tag → (rss_url, conference_source_tag)
#
# Journal eTOC feeds fire when a paper posts online-first, before PubMed
# indexing. They carry the actual paper abstract in the RSS <description>.
# Society feeds post news items about presentations, approvals, and updates.

PRIMARY_FEEDS: dict[str, tuple[str, str]] = {
    # Major journals — early-access / eTOC
    "NEJM": (
        "https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss",
        "JOURNAL_EARLY_ACCESS",
    ),
    "LANCET_ONCO": (
        "https://www.thelancet.com/action/showFeed?jc=lanonc&type=etoc&feed=rss",
        "JOURNAL_EARLY_ACCESS",
    ),
    "JCO": (
        "https://ascopubs.org/action/showFeed?type=etoc&feed=rss&jc=jco",
        "JOURNAL_EARLY_ACCESS",
    ),
    "JAMA_ONCO": (
        "https://jamanetwork.com/rss/site_3/67.xml",
        "JOURNAL_EARLY_ACCESS",
    ),
    "IJROBP": (
        "https://www.redjournal.org/action/showFeed?jc=ijrobp&type=etoc&feed=rss",
        "JOURNAL_EARLY_ACCESS",
    ),
    "ANN_ONCO": (
        "https://www.annalsofoncology.org/action/showFeed?jc=annonc&type=etoc&feed=rss",
        "JOURNAL_EARLY_ACCESS",
    ),
    # Society news
    "ASCO_NEWS": (
        "https://www.asco.org/about-asco/press-center/news-releases/rss",
        "SOCIETY_NEWS",
    ),
    "ESMO_NEWS": (
        "https://www.esmo.org/rss/press-releases.xml",
        "SOCIETY_NEWS",
    ),
    "ASTRO_NEWS": (
        "https://www.astro.org/RSS/News",
        "SOCIETY_NEWS",
    ),
    "AACR_NEWS": (
        "https://www.aacr.org/blog/rss/",
        "SOCIETY_NEWS",
    ),
    "NCCN_NEWS": (
        "https://www.nccn.org/rss/news.xml",
        "SOCIETY_NEWS",
    ),
}

# ── SECONDARY FEEDS ──────────────────────────────────────────────────────────
# These produce only trial name / NCT strings — no PubMedRecord objects.
# Source tag → rss_url

SECONDARY_FEEDS: dict[str, str] = {
    "ONCLIVE":         "https://www.onclive.com/rss/news",
    "CANCER_NETWORK":  "https://www.cancernetwork.com/rss",
    "MEDSCAPE_ONCO":   "https://www.medscape.com/cx/rssfeeds/2922.xml",
    "TARGETED_ONCO":   "https://www.targetedonc.com/rss",
    "FIERCE_BIOTECH":  "https://www.fiercebiotech.com/rss/rss.xml",
    "ENDPOINTS":       "https://endpts.com/feed/",
    "MEDPAGE_ONCO":    "https://www.medpagetoday.com/rss/headlines.xml",
}


# ── CONTENT FILTERS ──────────────────────────────────────────────────────────
# Applied to primary records before creating PubMedRecord objects.
# We want papers/items about clinical trial results, approvals, and guidelines —
# NOT editorials, drug mechanisms, preclinical data, or meeting announcements.

_CLINICAL_SIGNAL_RE = re.compile(
    r"\b("
    r"phase\s*(i{1,3}|[123])[ab]?\s*(trial|study|rct|randomi)"
    r"|randomi[sz]ed"
    r"|overall survival|progression.free survival|disease.free survival"
    r"|objective response|complete response|pathologic response"
    r"|fda\s+approv|accelerated approval|granted approval|full approval"
    r"|guideline|nccn\s+update|category\s+[12]"
    r"|lba\s*\d|plenary|late.breaking"
    r"|non.inferior|de.escalat"
    r")\b",
    re.IGNORECASE,
)

# Oncology content filter — must mention cancer type or oncology context
_ONCO_RE = re.compile(
    r"\b("
    r"cancer|carcinoma|lymphoma|leukemia|myeloma|melanoma|sarcoma"
    r"|glioma|glioblastoma|tumor|tumour|oncol|neoplasm|malignant"
    r"|breast|lung|colon|colorectal|prostate|bladder|renal|ovarian"
    r"|cervical|endometrial|pancreatic|gastric|biliary|hepatocellular"
    r"|head.{1,5}neck|nsclc|sclc|cll|aml|dlbcl|mds|myelofibrosis"
    r")\b",
    re.IGNORECASE,
)


# ── TRIAL NAME EXTRACTOR ─────────────────────────────────────────────────────
# Patterns that commonly identify named clinical trials in oncology headlines.

# Named trial patterns: KEYNOTE-522, PEACE-3, CheckMate 816, POLO, LAURA,
# ADAURA, FLAURA2, IMpower150, DESTINY-Breast06, etc.
_TRIAL_NAME_RE = re.compile(
    r"(?<!\w)("
    # Pattern 1: Optional 2-3 letter prefix (e.g. DE-, RE-, CO-) + ALLCAPS name
    # Handles: DE-ESCALATE, PEACE-3, POLO, LAURA, FLAURA2, ALEX
    # Requires ≥4 uppercase letters total to reduce abbreviation false-positives
    r"(?:[A-Z]{2,3}-)?[A-Z]{4,}(?:[A-Z0-9]*)?(?:-\d+[A-Z]?)?"
    r"|"
    # Pattern 2: CamelCase brand trial names with optional numeric/letter suffix
    # e.g. CheckMate 816, IMpower150, DESTINY-Breast06
    r"(?:CheckMate|IMpower|KEYNOTE|IMbrave|OAK|POPLAR|IMpassion|Destiny|"
    r"ENESTnd|ADAURA|FLAURA|MARIPOSA|PAPILLON|CHRYSALIS|"
    r"SUNRISE|SUNSET|MOONRISE|HORIZONS?|BEACON|TROPHY|PACIFIC|COAST|"
    r"POSEIDON|CASPIAN|ADMIRAL|VIALE|TOPAZ|HIMALAYA|REFLECT|SHARP)"
    r"[\w-]*(?:\s*\d+[A-Z]?)?"
    r"|"
    # Pattern 3: NCT identifier
    r"NCT\d{8}"
    r")(?!\w)"
)

# Common false-positive ALLCAPS strings that are NOT trial names
_TRIAL_NAME_STOPWORDS = frozenset({
    # Regulatory / society bodies
    "FDA", "NCCN", "ASCO", "ESMO", "ASTRO", "AACR", "ASH", "SITC", "ESMO",
    "EMA", "WHO", "NIH", "NCI", "CMS",
    # Countries / regions
    "US", "EU", "UK", "USA",
    # Endpoints and statistics
    "OS", "PFS", "DFS", "RFS", "EFS", "LFS", "DMFS",
    "ORR", "DCR", "CBR", "TTR", "DOR", "MRD",
    "CR", "PR", "SD", "PD", "NR",
    "HR", "CI", "OR", "RR", "NNT", "ARR", "RRR",
    "AE", "SAE", "TEAE", "DLT",
    # Dosing / routes
    "IV", "SC", "PO", "IM", "QD", "BID", "TID", "QID",
    # Gene / biomarker names (common false positives)
    "EGFR", "ALK", "ROS", "MET", "KRAS", "BRAF", "NRAS", "HRAS",
    "PIK", "AKT", "MTOR", "PTEN", "CDK", "RB", "TP",
    "BRCA", "PALB", "ATM", "CHEK", "RAD",
    "PD-L1", "PDL1", "CTLA", "LAG", "TIM", "TIGIT",
    "HER", "VEGF", "FGFR", "PDGFR", "KIT", "FLT",
    "IDH", "NPM", "FLT", "JAK", "STAT", "BCL",
    "MMR", "MSI", "TMB", "DNMT", "EZH", "HDAC",
    "NRG", "NTRK", "RET", "MYC",
    # Drug class abbreviations
    "CAR", "ADC", "IO", "TKI", "CART", "TCR",
    "PARP", "CDK", "BTK", "SYK", "MDM",
    # Lab / assay
    "RNA", "DNA", "PCR", "IHC", "ISH", "NGS", "WGS", "WES",
    "CTC", "ctDNA", "FISH",
    # Cancer types / disease abbreviations (common in headlines)
    "NSCLC", "SCLC", "TNBC", "CRPC", "HCC", "CRC", "CLL", "AML",
    "DLBCL", "MCL", "MDS", "GBM", "GIST", "BPDCN",
    "GI", "GU", "CNS", "HPV", "EBV",
    # Histology / staging
    "SCC", "ACC", "NEC", "NET", "LCNEC", "SCLC",
    # Regulatory submission types
    "NDA", "BLA", "SNDA", "SBLA", "IND", "EUA", "MAA",
    # Job titles / credentials
    "CEO", "CMO", "CTO", "CSO", "VP", "MD", "PHD", "MBA",
    # Generic descriptor words that match ALLCAPS pattern
    "PHASE", "TRIAL", "STUDY", "DATA", "NEWS", "UPDATE", "RESULTS",
    "OPEN", "LABEL", "BLINDED", "DOSE", "COHORT", "ARMS", "ARM",
    "ABSTRACT", "PLENARY", "POSTER", "ORAL",
    # Roman numerals (matched by ALLCAPS pattern)
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII",
    # Clinical trial phases written as words
    "PHASE",
    # Common radiation oncology terms
    "SBRT", "SABR", "IMRT", "VMAT", "SRS", "TBI", "TACE",
    "CRT", "CCRT", "RT", "XRT",
    # Other common abbrevs
    "QOL", "PRO", "ECOG", "KPS", "RECIST", "PERCIST",
})


def extract_trial_names(text: str) -> list[str]:
    """
    Extract candidate clinical trial names and NCT IDs from free text.

    Returns a deduplicated list of strings, each a plausible trial name.
    Filters out common acronyms and gene/biomarker names that match the
    pattern but are not trial names.
    """
    candidates: set[str] = set()
    for m in _TRIAL_NAME_RE.finditer(text):
        name = m.group(0).strip()
        # Skip pure stopwords
        if name.upper() in _TRIAL_NAME_STOPWORDS:
            continue
        # Skip very short strings that are likely gene names (≤2 chars after cleaning)
        if len(re.sub(r"[\s\-]", "", name)) < 3:
            continue
        # Skip if it's a pure number or single letter
        if re.fullmatch(r"[\d\s-]+", name):
            continue
        candidates.add(name)
    return sorted(candidates)


# ── HTTP HELPERS ──────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "CarcinoS/1.0 (oncology research pipeline)"}


def _fetch_rss(url: str, timeout: int = 15) -> list:
    """Fetch an RSS feed. Returns feedparser entries or []."""
    try:
        import feedparser  # type: ignore
    except ImportError:
        log.warning("feedparser not installed — news lane disabled. pip install feedparser")
        return []
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        return feedparser.parse(resp.text).entries
    except Exception as exc:
        log.debug("RSS fetch failed (%s): %s", url, exc)
        return []


def _parse_entry_date(entry) -> tuple[Optional[date], str]:
    """Extract publication date from a feedparser entry."""
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                d = parsedate_to_datetime(raw).date()
                return d, d.isoformat()
            except Exception:
                pass
    return None, ""


def _fetch_page_text(url: str, max_chars: int = 1200, timeout: int = 10) -> str:
    """
    Fetch a page and return a plain-text excerpt of the body.
    Used to enrich RSS entries that have thin <description> fields.
    """
    if not url or "feedburner" in url:
        return ""
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        text = resp.text
        # Strip tags
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = " ".join(plain.split())
        # Find first substantive paragraph mentioning clinical content
        match = re.search(_CLINICAL_SIGNAL_RE, plain)
        if match:
            start = max(0, match.start() - 200)
            return plain[start: start + max_chars].strip()
        return plain[:max_chars].strip()
    except Exception as exc:
        log.debug("Page fetch failed (%s): %s", url, exc)
        return ""


# ── PRIMARY FEED RETRIEVAL ───────────────────────────────────────────────────

@dataclass
class NewsRecord:
    """Intermediate representation before conversion to PubMedRecord."""
    source_key: str
    conference_source_tag: str   # "JOURNAL_EARLY_ACCESS" or "SOCIETY_NEWS"
    title: str
    abstract: str                # enriched body text
    url: str
    pub_date: str


def fetch_primary_records(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
) -> list[PubMedRecord]:
    """
    Fetch primary feed records (journal early-access + society news).
    Returns PubMedRecord objects ready to merge into the pipeline.

    These records can earn qualifying signals (QS_PHASE_III_RANDOMIZED,
    QS_MAJOR_CONFERENCE, etc.) and become cards if the evidence supports it.
    They are NOT force-kept — Gate 2 applies normally.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    records: list[PubMedRecord] = []
    seen_urls: set[str] = set()

    for source_key, (feed_url, conf_tag) in PRIMARY_FEEDS.items():
        entries = _fetch_rss(feed_url)
        if not entries:
            log.debug("[Lane6] %s: no entries from %s", source_key, feed_url)
            continue

        site_count = 0
        for entry in entries:
            pub_date, pub_date_str = _parse_entry_date(entry)
            if pub_date and pub_date < cutoff:
                continue

            title   = (getattr(entry, "title",   None) or "").strip()
            summary = (getattr(entry, "summary", None)
                       or getattr(entry, "description", None) or "").strip()
            url     = (getattr(entry, "link",    None) or "").strip()

            if not title:
                continue
            if url and url in seen_urls:
                continue
            seen_urls.add(url)

            combined = f"{title} {summary}"

            # Must match oncology content
            if not _ONCO_RE.search(combined):
                continue
            # Must look like a clinical result, approval, or guideline item
            if not _CLINICAL_SIGNAL_RE.search(combined):
                continue

            # Enrich abstract by fetching the article page if summary is thin
            abstract = summary
            if enrich_abstracts and url and len(summary) < 200:
                page_text = _fetch_page_text(url)
                if len(page_text) > len(abstract):
                    abstract = page_text

            records.append(_news_to_pubmed_record(
                title=title,
                abstract=abstract,
                url=url,
                pub_date=pub_date_str,
                source_key=source_key,
                conf_tag=conf_tag,
            ))
            site_count += 1

        if site_count:
            log.info("[Lane6] %s: %d clinical records (lookback=%dd)", source_key, site_count, lookback_days)

    log.info("[Lane6] primary feeds total: %d records", len(records))
    return records


def _news_to_pubmed_record(
    *,
    title: str,
    abstract: str,
    url: str,
    pub_date: str,
    source_key: str,
    conf_tag: str,
) -> PubMedRecord:
    """Convert a news item to a synthetic PubMedRecord."""
    raw = f"NEWS|{source_key}|{url}|{title}"
    text_hash = hashlib.sha256(raw.encode()).hexdigest()

    # Map source key to a representative journal name for signal scoring
    _JOURNAL_MAP = {
        "NEJM":        "New England Journal of Medicine",
        "LANCET_ONCO": "Lancet Oncology",
        "JCO":         "Journal of Clinical Oncology",
        "JAMA_ONCO":   "JAMA Oncology",
        "IJROBP":      "International Journal of Radiation Oncology Biology Physics",
        "ANN_ONCO":    "Annals of Oncology",
        "ASCO_NEWS":   "ASCO News",
        "ESMO_NEWS":   "ESMO News",
        "ASTRO_NEWS":  "ASTRO News",
        "AACR_NEWS":   "AACR News",
        "NCCN_NEWS":   "NCCN News",
    }

    return PubMedRecord(
        pmid="",
        title=title,
        abstract=abstract,
        journal=_JOURNAL_MAP.get(source_key, source_key),
        pub_date=pub_date,
        publication_types=["Journal Article"],
        doi=None,
        pmc_id=None,
        nct_ids=[],
        mesh_terms=[],
        authors=[],
        language="eng",
        raw_xml=raw,
        text_hash=text_hash,
        conference_source=conf_tag,
    )


# ── SECONDARY FEED MONITORING ────────────────────────────────────────────────

def fetch_secondary_trial_signals(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
) -> list[str]:
    """
    Scan secondary oncology news feeds for trial names and NCT IDs.
    Returns a deduplicated list of candidate trial names to add to
    effective_watched_trials for this pipeline run.

    No PubMedRecord objects are created. Secondary sources can only
    influence the run by expanding what the pipeline watches.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    all_names: set[str] = set()
    source_counts: dict[str, int] = {}

    for source_key, feed_url in SECONDARY_FEEDS.items():
        entries = _fetch_rss(feed_url)
        if not entries:
            log.debug("[Lane6-secondary] %s: no entries", source_key)
            continue

        found: set[str] = set()
        for entry in entries:
            pub_date, _ = _parse_entry_date(entry)
            if pub_date and pub_date < cutoff:
                continue

            title   = (getattr(entry, "title",   None) or "").strip()
            summary = (getattr(entry, "summary", None)
                       or getattr(entry, "description", None) or "").strip()
            combined = f"{title} {summary}"

            # Only scan items with oncology + clinical signal content
            if not _ONCO_RE.search(combined):
                continue
            if not _CLINICAL_SIGNAL_RE.search(combined):
                continue

            for name in extract_trial_names(combined):
                found.add(name)

        if found:
            source_counts[source_key] = len(found)
            all_names.update(found)
            log.info(
                "[Lane6-secondary] %s: %d trial name(s) extracted: %s",
                source_key, len(found), sorted(found),
            )

    result = sorted(all_names)
    log.info(
        "[Lane6-secondary] total: %d unique trial signal(s) across %d source(s): %s",
        len(result), len(source_counts), result,
    )
    return result


# ── COMBINED ENTRY POINT ─────────────────────────────────────────────────────

def run_news_lane(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
) -> tuple[list[PubMedRecord], list[str]]:
    """
    Run the full Lane 6 hybrid monitoring layer.

    Returns:
        primary_records:   PubMedRecord objects from primary feeds.
                           Merge into the record pool before Gate 1.
        secondary_signals: Trial name strings from secondary feeds.
                           Merge into effective_watched_trials.
    """
    primary_records = fetch_primary_records(
        lookback_days=lookback_days,
        reference_date=reference_date,
        enrich_abstracts=enrich_abstracts,
    )
    secondary_signals = fetch_secondary_trial_signals(
        lookback_days=lookback_days,
        reference_date=reference_date,
    )
    return primary_records, secondary_signals
