"""
PubMed E-utilities client (deterministic retrieval).

Uses the official NCBI E-utilities API:
  - esearch.fcgi → returns PMIDs for a query
  - efetch.fcgi  → returns structured XML with title/abstract/journal/authors/IDs

Why this and not WebSearch:
  - Stable, paginatable, reproducible
  - Returns PMIDs we can hash and dedupe by
  - Returns DOI / PMC ID / NCT ID directly
  - Captures full XML so we can sha256 the canonical bytes (spec §2.6 / schema text_hash)

Usage:
    client = PubMedClient(email="you@example.com", api_key=os.getenv("NCBI_API_KEY"))
    pmids = client.esearch(query, retmax=200)
    records = client.efetch(pmids)  # list[PubMedRecord]
"""

from __future__ import annotations
import hashlib
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

import requests

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# NCBI rate limits: 3 req/sec without API key, 10 req/sec with key.
DEFAULT_DELAY_NO_KEY = 0.34
DEFAULT_DELAY_WITH_KEY = 0.11


@dataclass
class PubMedRecord:
    """One canonical PubMed article — provenance-bound."""
    pmid: str
    title: str
    abstract: str
    journal: str
    pub_date: str                          # ISO 8601 where possible (YYYY-MM-DD or YYYY-MM)
    publication_types: list[str] = field(default_factory=list)
    doi: Optional[str] = None
    pmc_id: Optional[str] = None
    nct_ids: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    language: Optional[str] = None
    raw_xml: str = ""                      # exact bytes used for extraction
    text_hash: str = ""                    # sha256 of raw_xml (spec audit guarantee)
    conference_source: Optional[str] = None  # e.g. "ASCO", "ASTRO" — set by conference lane
    url_override: Optional[str] = None       # set by non-PubMed lanes (web search) to carry real URL

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    def matches_journal_whitelist(self, whitelist: Iterable[str]) -> bool:
        """Loose case-insensitive contains match — PubMed journal names vary."""
        j = (self.journal or "").lower()
        return any(w.lower() in j or j in w.lower() for w in whitelist)


class PubMedClient:
    def __init__(
        self,
        email: str,
        api_key: Optional[str] = None,
        tool: str = "carcinos",
        timeout: int = 30,
    ):
        if not email:
            raise ValueError(
                "NCBI requires an email address for E-utilities queries. "
                "Set CARCINOS_NCBI_EMAIL in your environment."
            )
        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.timeout = timeout
        self._delay = DEFAULT_DELAY_WITH_KEY if api_key else DEFAULT_DELAY_NO_KEY
        self._last_call = 0.0

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_call = time.monotonic()

    def _params(self, **extra) -> dict:
        p = {"tool": self.tool, "email": self.email}
        if self.api_key:
            p["api_key"] = self.api_key
        p.update(extra)
        return p

    # ------------------------------------------------------------------
    # esearch
    # ------------------------------------------------------------------

    def esearch(self, query: str, retmax: int = 500) -> list[str]:
        """Return a list of PMIDs (deduped, ordered by PubMed relevance)."""
        self._throttle()
        params = self._params(
            db="pubmed",
            term=query,
            retmax=str(retmax),
            retmode="xml",
        )
        r = requests.get(ESEARCH_URL, params=params, timeout=self.timeout)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        pmids = [el.text for el in root.findall(".//IdList/Id") if el.text]
        return pmids

    # ------------------------------------------------------------------
    # efetch
    # ------------------------------------------------------------------

    def efetch(self, pmids: list[str], batch_size: int = 100) -> list[PubMedRecord]:
        """Fetch full PubMed records for a list of PMIDs."""
        records: list[PubMedRecord] = []
        for i in range(0, len(pmids), batch_size):
            batch = pmids[i : i + batch_size]
            records.extend(self._efetch_batch(batch))
        return records

    def _efetch_batch(self, pmids: list[str]) -> list[PubMedRecord]:
        if not pmids:
            return []
        self._throttle()
        params = self._params(
            db="pubmed",
            id=",".join(pmids),
            retmode="xml",
            rettype="abstract",
        )
        r = requests.get(EFETCH_URL, params=params, timeout=self.timeout)
        r.raise_for_status()
        return parse_pubmed_xml(r.text)


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

def parse_pubmed_xml(xml_text: str) -> list[PubMedRecord]:
    """Parse a PubmedArticleSet XML payload into PubMedRecord objects."""
    root = ET.fromstring(xml_text)
    out: list[PubMedRecord] = []

    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        title = _text(art, ".//Article/ArticleTitle") or ""

        # Abstract may be split into <AbstractText Label="..."> sections
        abstract_parts = []
        for ab in art.findall(".//Article/Abstract/AbstractText"):
            label = ab.attrib.get("Label")
            txt = "".join(ab.itertext()).strip()
            if label and txt:
                abstract_parts.append(f"{label}: {txt}")
            elif txt:
                abstract_parts.append(txt)
        abstract = "\n".join(abstract_parts)

        journal = (
            _text(art, ".//Article/Journal/Title")
            or _text(art, ".//Article/Journal/ISOAbbreviation")
            or ""
        )

        pub_date = _extract_pub_date(art)

        pub_types = [
            (el.text or "").strip()
            for el in art.findall(".//Article/PublicationTypeList/PublicationType")
            if el.text
        ]

        # IDs
        doi = None
        pmc_id = None
        for id_el in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
            id_type = id_el.attrib.get("IdType", "")
            value = (id_el.text or "").strip()
            if id_type == "doi" and value:
                doi = value
            elif id_type == "pmc" and value:
                pmc_id = value

        nct_ids = []
        for db in art.findall(".//DataBankList/DataBank"):
            name_el = db.find("DataBankName")
            if name_el is not None and (name_el.text or "").strip().lower() == "clinicaltrials.gov":
                for acc in db.findall(".//AccessionNumberList/AccessionNumber"):
                    if acc.text:
                        nct_ids.append(acc.text.strip())

        mesh = []
        for m in art.findall(".//MeshHeadingList/MeshHeading/DescriptorName"):
            if m.text:
                mesh.append(m.text.strip())

        authors = []
        for a in art.findall(".//AuthorList/Author"):
            last = _text(a, "LastName")
            initials = _text(a, "Initials")
            if last and initials:
                authors.append(f"{last} {initials}")
            elif last:
                authors.append(last)
            else:
                collective = _text(a, "CollectiveName")
                if collective:
                    authors.append(collective)

        language = _text(art, ".//Article/Language") or None

        raw = ET.tostring(art, encoding="unicode")
        text_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        out.append(PubMedRecord(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            pub_date=pub_date,
            publication_types=pub_types,
            doi=doi,
            pmc_id=pmc_id,
            nct_ids=nct_ids,
            mesh_terms=mesh,
            authors=authors,
            language=language,
            raw_xml=raw,
            text_hash=text_hash,
        ))

    return out


def _text(parent: ET.Element, path: str) -> str:
    el = parent.find(path)
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

def _extract_pub_date(art: ET.Element) -> str:
    """
    PubMed date logic: prefer ArticleDate (electronic publication date),
    fall back to PubDate inside JournalIssue. Returns 'YYYY-MM-DD' if available
    else 'YYYY-MM' or 'YYYY'.
    """
    # 1) ArticleDate
    ad = art.find(".//Article/ArticleDate")
    if ad is not None:
        y = _text(ad, "Year"); m = _text(ad, "Month"); d = _text(ad, "Day")
        if y and m and d:
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # 2) Journal issue PubDate
    pd = art.find(".//Article/Journal/JournalIssue/PubDate")
    if pd is not None:
        y = _text(pd, "Year")
        m = _text(pd, "Month")
        d = _text(pd, "Day")
        medline = _text(pd, "MedlineDate")
        if y:
            mm = _normalize_month(m) if m else ""
            if mm and d:
                return f"{y}-{mm}-{d.zfill(2)}"
            if mm:
                return f"{y}-{mm}"
            return y
        if medline:
            return medline
    return ""


def _normalize_month(value: str) -> str:
    v = value.strip().lower()[:3]
    if v.isdigit():
        return value.zfill(2)
    return _MONTHS.get(v, "")
