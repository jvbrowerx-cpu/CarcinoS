"""Extra trial sources beyond the stored abstract, all fetched and read by code.

Two kinds:

1. REGISTRY — ClinicalTrials.gov, fetched directly from its public API for any
   NCT number on the card. No model involved. Arm descriptions and adverse-event
   totals are written out as plain text so quotes can be checked against it.

2. WEB — pages the source finder (finder.py) suggests. CarcinoS downloads each
   page itself; a page counts only if its domain is on the allowlist below
   (primary sources: registries, PubMed/PMC, journals, meeting abstracts, FDA).
   Press releases, company sites and trade news are never accepted, matching
   the rest of CarcinoS.

Nothing here decides what a card says. These functions only supply text that
the validator checks quotes against.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .text import clean_source_text

log = logging.getLogger("carcinos.care_team.sources")

UA = "CarcinoS/1.0 (care-team source check; https://carcino-s.com)"
MAX_BYTES = 3_000_000
PAGE_CHAR_LIMIT = 60_000

# Primary sources only. A page on any other domain is ignored without fetching.
ALLOWED_DOMAINS = [
    # registries, NIH, FDA
    "clinicaltrials.gov", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "europepmc.org",
    "fda.gov", "accessdata.fda.gov", "dailymed.nlm.nih.gov", "cancer.gov",
    # journals and publishers
    "nejm.org", "thelancet.com", "ascopubs.org", "jamanetwork.com", "bmj.com",
    "annalsofoncology.org", "redjournal.org", "practicalradonc.org", "advancesradonc.org",
    "jto.org", "esmoopen.com", "nature.com", "sciencedirect.com", "cell.com",
    "academic.oup.com", "onlinelibrary.wiley.com", "acsjournals.onlinelibrary.wiley.com",
    "springer.com", "link.springer.com", "aacrjournals.org", "ashpublications.org",
    "tandfonline.com", "karger.com", "frontiersin.org", "mdpi.com", "biomedcentral.com",
    "jnccn.org", "gynecologiconcology-online.net", "ejcancer.com", "thegreenjournal.com",
    "radiotherapyandoncology.com", "eurourology.com", "ijgc.bmj.com",
    # meeting abstracts
    "meetings.asco.org", "asco.org", "esmo.org", "oncologypro.esmo.org", "astro.org",
]


def domain_allowed(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host or not url.lower().startswith("https://"):
        return False
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def domain_of(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


@dataclass
class SourceDoc:
    kind: str          # "web" or "registry"
    url: str
    name: str          # shown to readers, e.g. "ClinicalTrials.gov NCT01234567" or "nejm.org"
    text: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "url": self.url, "name": self.name, "chars": len(self.text)}


# ── fetching ──────────────────────────────────────────────────────────────────

_SCRIPT = re.compile(r"<(script|style|noscript|svg|nav|footer|header)\b.*?</\1>", re.S | re.I)


def html_to_text(html: str) -> str:
    return clean_source_text(_SCRIPT.sub(" ", html or ""))


def _http_get(url: str, accept: str = "text/html,application/json") -> tuple[str, str]:
    """Return (content_type, body_text). Raises on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=20) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("page too large")
    return ctype, body.decode("utf-8", errors="replace")


def fetch_page(url: str, getter: Optional[Callable[[str], tuple[str, str]]] = None) -> Optional[SourceDoc]:
    """Download an allowed page and return its visible text, or None."""
    if not domain_allowed(url):
        return None
    try:
        ctype, body = (getter or _http_get)(url)
    except Exception as e:
        log.info("care-team: could not fetch %s: %s", url, e)
        return None
    if "pdf" in ctype:
        return None  # PDFs are skipped (no reliable text extraction without extra packages)
    text = html_to_text(body) if ("html" in ctype or "<html" in body[:500].lower()) else clean_source_text(body)
    if len(text) < 200:
        return None
    return SourceDoc(kind="web", url=url, name=domain_of(url), text=text[:PAGE_CHAR_LIMIT])


# ── ClinicalTrials.gov (deterministic) ────────────────────────────────────────

NCT_RE = re.compile(r"\bNCT\d{8}\b")
CTGOV_API = "https://clinicaltrials.gov/api/v2/studies/{nct}"


def nct_ids_for(alert: dict, paper_text: str) -> list[str]:
    s = alert.get("summary_json") or {}
    ids = list((s.get("trial") or {}).get("nct_ids") or [])
    ids += NCT_RE.findall(paper_text or "")
    out: list[str] = []
    for i in ids:
        i = (i or "").strip().upper()
        if NCT_RE.fullmatch(i) and i not in out:
            out.append(i)
    return out[:2]


def render_registry(study: dict) -> str:
    """Write the parts of a ClinicalTrials.gov record a care team needs as plain text.

    The wording comes from the registry record itself (arm and intervention
    descriptions are copied as written); adverse-event counts are written out in
    a fixed sentence pattern so quotes can be checked against them.
    """
    ps = study.get("protocolSection") or {}
    rs = study.get("resultsSection") or {}
    parts: list[str] = []

    arms = (ps.get("armsInterventionsModule") or {})
    for a in arms.get("armGroups") or []:
        label, desc = a.get("label") or "", a.get("description") or ""
        if label or desc:
            parts.append(f"Arm {label}: {desc}".strip())
    for iv in arms.get("interventions") or []:
        if iv.get("description"):
            parts.append(f"Intervention {iv.get('name') or ''}: {iv['description']}")

    ae = rs.get("adverseEventsModule") or {}
    groups = {g.get("id"): g.get("title") or g.get("id") for g in ae.get("eventGroups") or []}
    for g in ae.get("eventGroups") or []:
        t = g.get("title") or g.get("id")
        sn, sr = g.get("seriousNumAffected"), g.get("seriousNumAtRisk")
        on, orr = g.get("otherNumAffected"), g.get("otherNumAtRisk")
        if sn is not None and sr:
            parts.append(f"Serious adverse events, {t}: {sn} of {sr} participants affected.")
        if on is not None and orr:
            parts.append(f"Other adverse events, {t}: {on} of {orr} participants affected.")
    for kind in ("seriousEvents", "otherEvents"):
        events = sorted(ae.get(kind) or [], key=lambda e: -max((s.get("numAffected") or 0) for s in (e.get("stats") or [{}])))[:15]
        for e in events:
            term = e.get("term") or ""
            for st in e.get("stats") or []:
                if st.get("numAtRisk"):
                    parts.append(f"{'Serious' if kind == 'seriousEvents' else 'Other'} adverse event {term}, "
                                 f"{groups.get(st.get('groupId'), st.get('groupId'))}: {st.get('numAffected', 0)} of {st['numAtRisk']} participants affected.")
    return clean_source_text(" ".join(p.rstrip(".") + "." for p in parts if p))


def fetch_registry(nct: str, getter: Optional[Callable[[str], tuple[str, str]]] = None) -> Optional[SourceDoc]:
    url = CTGOV_API.format(nct=nct)
    try:
        _, body = (getter or (lambda u: _http_get(u, "application/json")))(url)
        study = json.loads(body)
    except Exception as e:
        log.info("care-team: ClinicalTrials.gov lookup failed for %s: %s", nct, e)
        return None
    text = render_registry(study)
    if len(text) < 80:
        return None
    return SourceDoc(kind="registry", url=f"https://clinicaltrials.gov/study/{nct}",
                     name=f"ClinicalTrials.gov {nct}", text=text[:PAGE_CHAR_LIMIT])
