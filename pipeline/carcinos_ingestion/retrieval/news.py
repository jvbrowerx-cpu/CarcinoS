"""
Lane 6 — Hybrid Oncology News Monitoring Layer.

Architecture (two distinct tiers):

  PRIMARY FEEDS — journal eTOC RSS (high-trust, deterministic)
  ─────────────────────────────────────────────────────────────
  Major journals (NEJM, Lancet Oncology, JCO, JAMA Oncology, IJROBP,
  Annals of Oncology) + ASTRO and NCCN RSS publish content before PubMed
  indexes it (typically 24–72h lag for journals; conference abstracts may
  never appear in PubMed at all).

  Primary records are converted to full PubMedRecord objects tagged with
    conference_source = "JOURNAL_EARLY_ACCESS"  (journals)
    conference_source = "SOCIETY_NEWS"          (ASTRO/NCCN)
  They flow through the normal Gate 1 → Gate 2 → Pass 2 pipeline and
  CAN become cards if they earn a qualifying signal.

  KEY BUG FIX: feedparser must receive resp.content (bytes), not resp.text
  (decoded string). RSS feeds often return gzip; Python's text decoder may
  corrupt the encoding before feedparser sees it.

  SOCIETY NEWS — LLM web search (ASCO, ESMO, AACR, and others)
  ─────────────────────────────────────────────────────────────
  ASCO and ESMO removed their public RSS feeds. These are now retrieved via
  an LLM web search call that explicitly asks for recent society press
  releases. Results are converted to PubMedRecord objects like primary feeds.

  SECONDARY SOURCES — LLM web search, trial names only
  ─────────────────────────────────────────────────────
  Oncology trade press (OncLive, Cancer Network, Medscape Oncology,
  Targeted Oncology, Fierce Biotech, Endpoints News, MedPage Today) is
  monitored by a single LLM web search call. The LLM is asked to list
  every named clinical trial mentioned in recent oncology news. Those trial
  names are injected into `effective_watched_trials` for the current run,
  so that PubMed or conference records mentioning the same trial score
  QS_WATCHED_TRIAL and surface normally through the evidence pipeline.

  Secondary sources NEVER create PubMedRecord objects. They cannot drive
  a card directly — they expand the pipeline's awareness of what to watch.

  Example:
    LLM web search finds OncLive headline: "Phase III PEACE-3 positive in CRPC"
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

  RSS feeds are used where reliable; LLM web search fills in where RSS
  is dead, blocked, or nonexistent. The LLM search is a single API call
  per pipeline run (not per source), keeping cost minimal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import requests

from .pubmed import PubMedRecord

log = logging.getLogger("carcinos.news")


# ── PRIMARY FEEDS — journal eTOC RSS ─────────────────────────────────────────
# These produce PubMedRecord objects that can become cards.
# Source tag → (rss_url, conference_source_tag)
#
# ASCO and ESMO are NOT included here — their public RSS feeds are dead.
# They are handled by LLM web search in fetch_society_news_via_llm().

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
    # Society RSS feeds that still work
    "ASTRO_NEWS": (
        "https://www.astro.org/RSS/News",
        "SOCIETY_NEWS",
    ),
    "NCCN_NEWS": (
        "https://www.nccn.org/rss/news.xml",
        "SOCIETY_NEWS",
    ),
}

# Society sources whose RSS is dead — retrieved via LLM web search instead
_SOCIETY_SEARCH_SOURCES = ["ASCO", "ESMO", "AACR"]

# Trade press secondary sources — retrieved via LLM web search
_SECONDARY_SEARCH_SOURCES = [
    "OncLive",
    "Cancer Network",
    "Targeted Oncology",
    "Medscape Oncology",
    "Fierce Biotech (oncology)",
    "Endpoints News (oncology)",
    "MedPage Today (oncology)",
]


# ── CONTENT FILTERS ───────────────────────────────────────────────────────────

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


# ── TRIAL NAME EXTRACTOR ──────────────────────────────────────────────────────

_TRIAL_NAME_RE = re.compile(
    r"(?<!\w)("
    r"(?:[A-Z]{2,3}-)?[A-Z]{4,}(?:[A-Z0-9]*)?(?:-\d+[A-Z]?)?"
    r"|"
    r"(?:CheckMate|IMpower|KEYNOTE|IMbrave|OAK|POPLAR|IMpassion|Destiny|"
    r"ENESTnd|ADAURA|FLAURA|MARIPOSA|PAPILLON|CHRYSALIS|"
    r"SUNRISE|SUNSET|MOONRISE|HORIZONS?|BEACON|TROPHY|PACIFIC|COAST|"
    r"POSEIDON|CASPIAN|ADMIRAL|VIALE|TOPAZ|HIMALAYA|REFLECT|SHARP)"
    r"[\w-]*(?:\s*\d+[A-Z]?)?"
    r"|"
    r"NCT\d{8}"
    r")(?!\w)"
)

_TRIAL_NAME_STOPWORDS = frozenset({
    "FDA", "NCCN", "ASCO", "ESMO", "ASTRO", "AACR", "ASH", "SITC",
    "EMA", "WHO", "NIH", "NCI", "CMS",
    "US", "EU", "UK", "USA",
    "OS", "PFS", "DFS", "RFS", "EFS", "LFS", "DMFS",
    "ORR", "DCR", "CBR", "TTR", "DOR", "MRD",
    "CR", "PR", "SD", "PD", "NR",
    "HR", "CI", "OR", "RR", "NNT", "ARR", "RRR",
    "AE", "SAE", "TEAE", "DLT",
    "IV", "SC", "PO", "IM", "QD", "BID", "TID", "QID",
    "EGFR", "ALK", "ROS", "MET", "KRAS", "BRAF", "NRAS", "HRAS",
    "PIK", "AKT", "MTOR", "PTEN", "CDK", "RB", "TP",
    "BRCA", "PALB", "ATM", "CHEK", "RAD",
    "PDL1", "CTLA", "LAG", "TIM", "TIGIT",
    "HER", "VEGF", "FGFR", "PDGFR", "KIT", "FLT",
    "IDH", "NPM", "JAK", "STAT", "BCL",
    "MMR", "MSI", "TMB", "DNMT", "EZH", "HDAC",
    "NRG", "NTRK", "RET", "MYC",
    "CAR", "ADC", "IO", "TKI", "CART", "TCR",
    "PARP", "BTK", "SYK", "MDM",
    "RNA", "DNA", "PCR", "IHC", "ISH", "NGS", "WGS", "WES",
    "CTC", "FISH",
    "NSCLC", "SCLC", "TNBC", "CRPC", "HCC", "CRC", "CLL", "AML",
    "DLBCL", "MCL", "MDS", "GBM", "GIST", "BPDCN",
    "GI", "GU", "CNS", "HPV", "EBV",
    "SCC", "ACC", "NEC", "NET", "LCNEC",
    "NDA", "BLA", "SNDA", "SBLA", "IND", "EUA", "MAA",
    "CEO", "CMO", "CTO", "CSO", "VP", "MD", "PHD", "MBA",
    "PHASE", "TRIAL", "STUDY", "DATA", "NEWS", "UPDATE", "RESULTS",
    "OPEN", "LABEL", "BLINDED", "DOSE", "COHORT", "ARMS", "ARM",
    "ABSTRACT", "PLENARY", "POSTER", "ORAL",
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII",
    "SBRT", "SABR", "IMRT", "VMAT", "SRS", "TBI", "TACE",
    "CRT", "CCRT", "RT", "XRT",
    "QOL", "PRO", "ECOG", "KPS", "RECIST", "PERCIST",
})


def extract_trial_names(text: str) -> list[str]:
    """
    Extract candidate clinical trial names and NCT IDs from free text.
    Returns a deduplicated sorted list of plausible trial names.
    """
    candidates: set[str] = set()
    for m in _TRIAL_NAME_RE.finditer(text):
        name = m.group(0).strip()
        if name.upper() in _TRIAL_NAME_STOPWORDS:
            continue
        if len(re.sub(r"[\s\-]", "", name)) < 3:
            continue
        if re.fullmatch(r"[\d\s-]+", name):
            continue
        candidates.add(name)
    return sorted(candidates)


# ── HTTP / RSS HELPERS ────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "CarcinoS/1.0 (oncology research pipeline)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Encoding": "gzip, deflate",
}


def _fetch_rss(url: str, source_key: str = "", timeout: int = 15) -> list:
    """
    Fetch an RSS feed. Returns feedparser entries or [].

    IMPORTANT: passes resp.content (bytes) to feedparser — not resp.text.
    RSS feeds often return gzip-compressed content. If we decode first with
    resp.text, Python may use the wrong encoding and corrupt the XML before
    feedparser sees it. feedparser handles all encoding detection natively
    when given raw bytes.
    """
    try:
        import feedparser  # type: ignore
    except ImportError:
        log.warning(
            "feedparser not installed — RSS primary feeds disabled. "
            "Run: pip install feedparser"
        )
        return []

    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        # ↓ KEY: pass bytes, not decoded string
        feed = feedparser.parse(resp.content)
        entries = feed.entries
        if not entries:
            log.warning(
                "[Lane6] %s: RSS returned 0 entries — feed may have moved or "
                "require auth. URL: %s",
                source_key or "unknown", url,
            )
        return entries
    except Exception as exc:
        log.warning("[Lane6] %s: RSS fetch failed (%s): %s", source_key or "unknown", url, exc)
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
    """Fetch a page and return a plain-text excerpt of the body."""
    if not url or "feedburner" in url:
        return ""
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
        plain = re.sub(r"<[^>]+>", " ", resp.text)
        plain = " ".join(plain.split())
        match = re.search(_CLINICAL_SIGNAL_RE, plain)
        if match:
            start = max(0, match.start() - 200)
            return plain[start: start + max_chars].strip()
        return plain[:max_chars].strip()
    except Exception as exc:
        log.debug("Page fetch failed (%s): %s", url, exc)
        return ""


# ── LLM WEB SEARCH HELPERS ───────────────────────────────────────────────────

def _run_llm_web_search(
    openai_api_key: str,
    prompt: str,
    model: str,
    context_label: str,
) -> str:
    """
    Run a web search via OpenAI Responses API.
    Returns the output text string, or "" on failure.

    Uses the web_search_preview tool which causes the model to search
    the web before responding — no separate search API needed.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search_preview"}],
            input=prompt,
        )
        text = response.output_text or ""
        log.info("[Lane6] %s: LLM web search returned %d chars", context_label, len(text))
        return text
    except Exception as exc:
        log.warning("[Lane6] %s: LLM web search failed: %s", context_label, exc)
        return ""


# ── SOCIETY NEWS — LLM SEARCH ────────────────────────────────────────────────

_SOCIETY_ITEM_RE = re.compile(
    r"TITLE:\s*(.+?)\s*\n"
    r"DATE:\s*(\S+)\s*\n"
    r"SOURCE:\s*(\S+)\s*\n"
    r"SUMMARY:\s*(.+?)(?=\nTITLE:|\Z)",
    re.DOTALL,
)


def fetch_society_news_via_llm(
    lookback_days: int,
    openai_api_key: str,
    model: str,
    reference_date: Optional[date] = None,
) -> list[PubMedRecord]:
    """
    Retrieve ASCO, ESMO, AACR, and other society press releases via LLM web search.

    Returns PubMedRecord objects that can become cards if they earn a
    qualifying signal through the normal Gate 1 → Gate 2 pipeline.
    """
    if reference_date is None:
        reference_date = date.today()

    sources = ", ".join(_SOCIETY_SEARCH_SOURCES)
    prompt = (
        f"Search for press releases and news from {sources} published in the "
        f"last {lookback_days} days (on or after "
        f"{(reference_date - timedelta(days=lookback_days)).isoformat()}). "
        f"Focus on: clinical trial results, FDA approvals, guideline updates, "
        f"and late-breaking abstracts. "
        f"For each relevant item, output EXACTLY this format:\n\n"
        f"TITLE: [exact headline]\n"
        f"DATE: [YYYY-MM-DD or approximate]\n"
        f"SOURCE: [ASCO/ESMO/AACR/etc]\n"
        f"SUMMARY: [2-3 sentences describing the clinical finding, including drug names, "
        f"cancer type, and key result]\n\n"
        f"Output only items with direct clinical oncology relevance. "
        f"Skip administrative announcements, award notices, and membership news."
    )

    raw = _run_llm_web_search(openai_api_key, prompt, model, "society-news")
    if not raw:
        return []

    records: list[PubMedRecord] = []
    for m in _SOCIETY_ITEM_RE.finditer(raw):
        title   = m.group(1).strip()
        raw_date = m.group(2).strip()
        source  = m.group(3).strip().upper()
        summary = m.group(4).strip()

        if not title or not summary:
            continue
        if not _ONCO_RE.search(f"{title} {summary}"):
            continue

        # Normalise date string
        pub_date_str = ""
        try:
            from datetime import datetime
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
                try:
                    pub_date_str = datetime.strptime(raw_date, fmt).date().isoformat()
                    break
                except ValueError:
                    pass
        except Exception:
            pass

        raw_text = f"NEWS|{source}|{title}"
        text_hash = hashlib.sha256(raw_text.encode()).hexdigest()

        _source_journal_map = {
            "ASCO": "ASCO News",
            "ESMO": "ESMO News",
            "AACR": "AACR News",
        }

        # Use the specific society name as conference_source so the signal scorer
        # can apply QS_MAJOR_CONFERENCE rules. "SOCIETY_NEWS" is not in
        # _MAJOR_CONFERENCES, so ASCO/ESMO/AACR press releases would otherwise
        # fall to qs_none and miss conference scoring entirely.
        _KNOWN_MAJOR = {"ASCO", "ESMO", "AACR", "ASH", "ASTRO", "SITC", "SABCS", "ESGO"}
        conf_source = source if source in _KNOWN_MAJOR else "SOCIETY_NEWS"

        records.append(PubMedRecord(
            pmid="",
            title=title,
            abstract=summary,
            journal=_source_journal_map.get(source, f"{source} News"),
            pub_date=pub_date_str,
            publication_types=["Journal Article"],
            doi=None,
            pmc_id=None,
            nct_ids=[],
            mesh_terms=[],
            authors=[],
            language="eng",
            raw_xml=raw_text,
            text_hash=text_hash,
            conference_source=conf_source,
        ))

    log.info(
        "[Lane6] society news (LLM): %d clinical records from %s",
        len(records), sources,
    )
    return records


# ── SECONDARY — LLM SEARCH ───────────────────────────────────────────────────

def fetch_secondary_via_llm(
    lookback_days: int,
    openai_api_key: str,
    model: str,
    reference_date: Optional[date] = None,
) -> list[str]:
    """
    Scan oncology trade press for trial names via a single LLM web search call.

    Returns a deduplicated list of trial name strings to inject into
    effective_watched_trials. No PubMedRecord objects are created.
    """
    if reference_date is None:
        reference_date = date.today()

    sources = ", ".join(_SECONDARY_SEARCH_SOURCES)
    cutoff = (reference_date - timedelta(days=lookback_days)).isoformat()
    prompt = (
        f"Search the following oncology news sources for articles published "
        f"in the last {lookback_days} days (on or after {cutoff}): {sources}.\n\n"
        f"Your task: identify every named clinical trial mentioned in oncology "
        f"news. Include:\n"
        f"- Named trials (e.g. KEYNOTE-522, PEACE-3, CheckMate 816, LAURA, POLO)\n"
        f"- NCT identifiers (e.g. NCT04516746)\n"
        f"- Phase III and Phase II trials with results or readouts\n\n"
        f"Output ONLY a plain list, one trial name per line, no explanations. "
        f"Example output:\n"
        f"KEYNOTE-522\n"
        f"PEACE-3\n"
        f"NCT04516746\n"
        f"CheckMate 816\n\n"
        f"Do not include drug names, cancer types, genes, or other abbreviations "
        f"unless they ARE the trial name."
    )

    raw = _run_llm_web_search(openai_api_key, prompt, model, "secondary-trial-names")
    if not raw:
        return []

    # Parse the line-by-line list, then run regex extractor for any embedded names
    candidate_names: set[str] = set()

    # Direct line extraction
    for line in raw.splitlines():
        line = line.strip().lstrip("•-*·0123456789. ")
        if not line:
            continue
        # Skip lines that are clearly headers/explanations (contain spaces indicating sentences)
        if len(line.split()) > 4:
            # Long line — run regex extraction instead of taking whole line
            for name in extract_trial_names(line):
                candidate_names.add(name)
            continue
        # Short token — validate it looks like a trial name
        if re.search(r"[A-Z]{3}", line):
            candidate_names.add(line)

    # Also run regex on full response to catch anything in prose
    for name in extract_trial_names(raw):
        candidate_names.add(name)

    result = sorted(candidate_names)
    log.info(
        "[Lane6] secondary (LLM): %d trial name(s) extracted from trade press: %s",
        len(result), result,
    )
    return result


# ── PRIMARY FEED RETRIEVAL (RSS) ─────────────────────────────────────────────

@dataclass
class NewsRecord:
    source_key: str
    conference_source_tag: str
    title: str
    abstract: str
    url: str
    pub_date: str


_JOURNAL_MAP = {
    "NEJM":        "New England Journal of Medicine",
    "LANCET_ONCO": "Lancet Oncology",
    "JCO":         "Journal of Clinical Oncology",
    "JAMA_ONCO":   "JAMA Oncology",
    "IJROBP":      "International Journal of Radiation Oncology Biology Physics",
    "ANN_ONCO":    "Annals of Oncology",
    "ASTRO_NEWS":  "ASTRO News",
    "NCCN_NEWS":   "NCCN News",
}


def fetch_primary_records(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
) -> list[PubMedRecord]:
    """
    Fetch journal eTOC and society RSS primary records.
    Returns PubMedRecord objects ready to merge into the pipeline.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    records: list[PubMedRecord] = []
    seen_urls: set[str] = set()

    for source_key, (feed_url, conf_tag) in PRIMARY_FEEDS.items():
        entries = _fetch_rss(feed_url, source_key=source_key)
        if not entries:
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
            if not _ONCO_RE.search(combined):
                continue
            if not _CLINICAL_SIGNAL_RE.search(combined):
                continue

            abstract = summary
            if enrich_abstracts and url and len(summary) < 200:
                page_text = _fetch_page_text(url)
                if len(page_text) > len(abstract):
                    abstract = page_text

            raw_text = f"NEWS|{source_key}|{url}|{title}"
            records.append(PubMedRecord(
                pmid="",
                title=title,
                abstract=abstract,
                journal=_JOURNAL_MAP.get(source_key, source_key),
                pub_date=pub_date_str,
                publication_types=["Journal Article"],
                doi=None,
                pmc_id=None,
                nct_ids=[],
                mesh_terms=[],
                authors=[],
                language="eng",
                raw_xml=raw_text,
                text_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
                conference_source=conf_tag,
            ))
            site_count += 1

        if site_count:
            log.info(
                "[Lane6] %s: %d clinical records (lookback=%dd)",
                source_key, site_count, lookback_days,
            )

    log.info("[Lane6] primary RSS total: %d records", len(records))
    return records


# ── COMBINED ENTRY POINT ─────────────────────────────────────────────────────

def run_news_lane(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
    openai_api_key: Optional[str] = None,
    llm_model: str = "gpt-4o-mini",
) -> tuple[list[PubMedRecord], list[str]]:
    """
    Run the full Lane 6 hybrid monitoring layer.

    Args:
        lookback_days:    Days to look back.
        reference_date:   Window end date (default today).
        enrich_abstracts: Fetch article pages to enrich thin RSS abstracts.
        openai_api_key:   OpenAI API key for LLM web search. If None, LLM
                          search steps are skipped with a warning.
        llm_model:        Model to use for LLM web search (default gpt-4o-mini).

    Returns:
        primary_records:   PubMedRecord objects from RSS + LLM society search.
                           Merge into the record pool before Gate 1.
        secondary_signals: Trial name strings from LLM trade press search.
                           Merge into effective_watched_trials.
    """
    # 1. Journal eTOC + ASTRO/NCCN RSS
    rss_records = fetch_primary_records(
        lookback_days=lookback_days,
        reference_date=reference_date,
        enrich_abstracts=enrich_abstracts,
    )

    society_records: list[PubMedRecord] = []
    secondary_signals: list[str] = []

    if not openai_api_key:
        log.warning(
            "[Lane6] No openai_api_key provided — ASCO/ESMO/AACR society news "
            "and trade press trial-name discovery are disabled. "
            "Pass openai_api_key to run_news_lane() to enable LLM web search."
        )
    else:
        # 2. ASCO / ESMO / AACR via LLM web search
        society_records = fetch_society_news_via_llm(
            lookback_days=lookback_days,
            openai_api_key=openai_api_key,
            model=llm_model,
            reference_date=reference_date,
        )

        # 3. Trade press trial-name discovery via LLM web search
        secondary_signals = fetch_secondary_via_llm(
            lookback_days=lookback_days,
            openai_api_key=openai_api_key,
            model=llm_model,
            reference_date=reference_date,
        )

    all_primary = rss_records + society_records
    log.info(
        "[Lane6] total primary: %d records (rss=%d, llm-society=%d), "
        "secondary signals: %d trial names",
        len(all_primary), len(rss_records), len(society_records),
        len(secondary_signals),
    )
    return all_primary, secondary_signals
