"""Official FDA label lookup via openFDA (free, no key required for low volume).

Label text used for grounding always comes from this retrieval, never from the
model. Each label section is kept separately so the validator can check that a
row's quote comes from a section that row is allowed to use (see fields.py).

Deterministic safeguards:
  * a label is accepted only if openFDA lists the requested generic name on it;
  * the generic name must also appear in the card's own title or paper text
    (checked in generate.py), so a model slip cannot pull in an unrelated drug.
"""

from __future__ import annotations

import json
import re
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from .fields import LABEL_SECTIONS, SECTION_TITLES
from .text import clean_source_text

log = logging.getLogger("carcinos.care_team.labels")

OPENFDA_URL = "https://api.fda.gov/drug/label.json"
# Generous: Warnings and Adverse Reactions often run 15,000-45,000 characters, and the
# data for a newer indication can sit far into the section.
SECTION_CHAR_LIMIT = 45000


@dataclass
class DrugLabel:
    drug: str                       # generic name as requested, lowercase
    set_id: str
    brand: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    route: str = ""                 # e.g. "intravenous", "subcutaneous" (from openFDA)
    other_formulation: bool = False  # True when the exact product's label wasn't found
    label_generic: str = ""          # generic name printed on the label used

    @property
    def url(self) -> str:
        return f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={self.set_id}" if self.set_id else ""

    @property
    def display_brand(self) -> str:
        """Brand shown to readers; names the route when it's another formulation."""
        b = self.brand or self.label_generic or self.drug
        if self.other_formulation and self.route:
            return f"{b} ({self.route})"
        return b

    @property
    def display_name(self) -> str:
        return f"{self.display_brand} ({self.drug})" if self.brand else self.drug

    def to_dict(self) -> dict:
        return {"drug": self.drug, "brand": self.display_brand, "set_id": self.set_id, "url": self.url,
                "sections": sorted(self.sections), "route": self.route,
                "other_formulation": self.other_formulation, "label_generic": self.label_generic}

    def prompt_block(self, max_chars: int = 0) -> str:
        head = f"FDA LABEL — {self.drug} (label: {self.label_generic or self.drug}"
        head += f", {self.route})" if self.route else ")"
        if self.other_formulation:
            head += (" — NOTE: label for another formulation of the same drug; the exact product's "
                     "label was not found. Drug-level warnings and interactions may still apply.")
        parts = [head]
        present = [sec for sec in LABEL_SECTIONS if sec in self.sections]
        per = max(4000, max_chars // len(present)) if (max_chars and present) else 0
        for sec in present:
            body = self.sections[sec][:per] if per else self.sections[sec]
            parts.append(f"[SECTION: {sec}] ({SECTION_TITLES[sec]})\n<<<\n{body}\n>>>")
        return "\n".join(parts)


def _http_get_json(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # 404 = no label; anything else = skip quietly
        log.info("openFDA lookup failed for %s: %s", url, e)
        return None


_PAREN = re.compile(r"\([^)]*\)")
_FORMULATION_SUFFIX = re.compile(
    r"\s+and\s+hyaluronidase(?:-[a-z]{4})?$|-[a-z]{4}$|\s+(?:subcutaneous|intravenous|oral|injection|tablets?|capsules?)$")
ROUTE_WORDS = {"subcutaneous": ["subcutaneous", "subcutaneously", "sc ", "faspro", "hyaluronidase"],
               "intravenous": ["intravenous", "intravenously", "infusion", " iv "],
               "oral": ["oral", "orally", "tablet", "capsule"]}


def clean_name(name: str) -> str:
    """'Amivantamab-hyaluronidase (SC)' -> 'amivantamab-hyaluronidase'."""
    n = _PAREN.sub(" ", (name or "").lower())
    n = re.sub(r"[^a-z0-9\- ]+", " ", n)
    return " ".join(n.split())


def base_ingredient(name: str) -> str:
    """'amivantamab and hyaluronidase-lpuj' -> 'amivantamab'; 'trastuzumab-dkst' -> 'trastuzumab'."""
    n = clean_name(name).replace("-hyaluronidase", " and hyaluronidase")
    prev = None
    while prev != n:
        prev, n = n, _FORMULATION_SUFFIX.sub("", n).strip()
    return n.split(" and ")[0].strip()


def route_hint(text: str) -> str:
    t = f" {(text or '').lower()} "
    for route, words in ROUTE_WORDS.items():
        if any(w in t for w in words):
            return route
    return ""


def _label_from_record(rec: dict, requested: str) -> Optional[DrugLabel]:
    ofda = rec.get("openfda") or {}
    sections: dict[str, str] = {}
    for sec in LABEL_SECTIONS:
        val = rec.get(sec)
        if val:
            body = clean_source_text(" ".join(val))[:SECTION_CHAR_LIMIT]
            if body:
                sections[sec] = body
    if not sections:
        return None
    set_id = rec.get("set_id") or (ofda.get("spl_set_id") or [""])[0]
    brand = ((ofda.get("brand_name") or [""])[0] or "").strip().title()
    route = ((ofda.get("route") or [""])[0] or "").strip().lower()
    label_generic = ((ofda.get("generic_name") or [""])[0] or "").strip().lower()
    return DrugLabel(drug=requested, set_id=set_id or "", brand=brand, sections=sections,
                     route=route, label_generic=label_generic)


def fetch_label(drug: str, getter: Callable[[str], Optional[dict]] = _http_get_json,
                context: str = "") -> Optional[DrugLabel]:
    """Find the best FDA label for a drug named on the card.

    Searches openFDA by the core ingredient (so 'amivantamab-hyaluronidase',
    'amivantamab and hyaluronidase-lpuj' and 'amivantamab' all find the same
    labels), then picks among them by fixed rules: the label must list the
    ingredient; prefer the route the card describes (e.g. subcutaneous), a label
    whose indications mention the card's cancer, and the newest version.
    """
    requested = clean_name(drug)
    base = base_ingredient(requested)
    if not base or not base.replace("-", "").replace(" ", "").isalnum():
        return None
    query = urllib.parse.quote(f'openfda.generic_name:"{base}"')
    data = getter(f"{OPENFDA_URL}?search={query}&limit=10")
    results = [r for r in ((data or {}).get("results") or [])
               if base in " | ".join((r.get("openfda") or {}).get("generic_name") or []).lower()]
    if not results:
        return None

    ctx = (context or "").lower()
    want_route = route_hint(requested + " " + ctx)
    extra_words = [w for w in requested.replace("-", " ").split() if w not in (base, "and") and len(w) > 3]
    disease_words = [w for w in re.findall(r"[a-z]{5,}", ctx)
                     if w not in {"cancer", "patients", "advanced", "metastatic", "approval", "accelerated",
                                  "grants", "approves", "treatment", "recurrent", "therapy", "adult"}][:12]

    def score(r: dict) -> tuple:
        o = r.get("openfda") or {}
        gen = " ".join(o.get("generic_name") or []).lower()
        rt = " ".join(o.get("route") or []).lower()
        ind = " ".join(r.get("indications_and_usage") or [])[:20000].lower()
        return (
            sum(w in gen for w in extra_words),                    # exact product (e.g. hyaluronidase form)
            1 if want_route and want_route in rt else 0,           # route the card describes
            sum(w in ind for w in disease_words),                  # label covers the card's cancer
            r.get("effective_time") or "",                         # newest
        )

    best = max(results, key=score)
    lab = _label_from_record(best, requested)
    if lab is None:
        return None
    gen = lab.label_generic
    lab.other_formulation = bool(
        (extra_words and not all(w in gen for w in extra_words))
        or (want_route and lab.route and want_route not in lab.route)
    )
    return lab


def fetch_labels(drugs: list[str], getter: Callable[[str], Optional[dict]] = _http_get_json,
                 context: str = "") -> list[DrugLabel]:
    out: list[DrugLabel] = []
    seen: set[str] = set()
    for d in drugs[:4]:
        key = clean_name(d)
        base = base_ingredient(key)
        if not key or base in seen:
            continue
        seen.add(base)
        lab = fetch_label(key, getter, context)
        if lab:
            out.append(lab)
    return out
