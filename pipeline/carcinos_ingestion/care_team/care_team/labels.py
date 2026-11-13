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
SECTION_CHAR_LIMIT = 6000


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

    def prompt_block(self) -> str:
        head = f"FDA LABEL — {self.drug} (label: {self.label_generic or self.drug}"
        head += f", {self.route})" if self.route else ")"
        if self.other_formulation:
            head += (" — NOTE: label for another formulation of the same drug; the exact product's "
                     "label was not found. Drug-level warnings and interactions may still apply.")
        parts = [head]
        for sec in LABEL_SECTIONS:
            if sec in self.sections:
                parts.append(f"[SECTION: {sec}] ({SECTION_TITLES[sec]})\n<<<\n{self.sections[sec]}\n>>>")
        return "\n".join(parts)


def _http_get_json(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # 404 = no label; anything else = skip quietly
        log.info("openFDA lookup failed for %s: %s", url, e)
        return None


def fetch_label(drug: str, getter: Callable[[str], Optional[dict]] = _http_get_json) -> Optional[DrugLabel]:
    name = (drug or "").strip().lower()
    if not name or not name.replace("-", "").replace(" ", "").isalnum():
        return None
    query = urllib.parse.quote(f'openfda.generic_name:"{name}"')
    data = getter(f"{OPENFDA_URL}?search={query}&limit=1")
    results = (data or {}).get("results") or []
    if not results:
        return None
    rec = results[0]
    ofda = rec.get("openfda") or {}

    # Deterministic check: the label must actually list this generic name.
    generic_names = " | ".join(ofda.get("generic_name") or []).lower()
    if name not in generic_names:
        return None

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
    return DrugLabel(drug=name, set_id=set_id or "", brand=brand, sections=sections,
                     route=route, label_generic=label_generic)


_FORMULATION_SUFFIX = re.compile(r"\s+and\s+hyaluronidase(?:-[a-z]{4})?$|-[a-z]{4}$|\s+(?:subcutaneous|intravenous|oral)$")


def base_ingredient(name: str) -> str:
    """'amivantamab and hyaluronidase-lpuj' -> 'amivantamab'; 'trastuzumab-dkst' -> 'trastuzumab'."""
    n = (name or "").strip().lower()
    prev = None
    while prev != n:
        prev, n = n, _FORMULATION_SUFFIX.sub("", n).strip()
    return n


def fetch_labels(drugs: list[str], getter: Callable[[str], Optional[dict]] = _http_get_json) -> list[DrugLabel]:
    out: list[DrugLabel] = []
    seen: set[str] = set()
    for d in drugs[:4]:
        key = (d or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        lab = fetch_label(key, getter)
        if lab is None:
            # Exact product not found (e.g. a new subcutaneous form): use the same
            # drug's label, clearly named as another formulation.
            base = base_ingredient(key)
            if base and base != key and base not in seen:
                lab = fetch_label(base, getter)
                if lab:
                    lab.drug = key            # rows still refer to the card's product
                    lab.other_formulation = True
        if lab:
            out.append(lab)
    return out
