"""Generate mode: the model writes every row itself (the default).

The model gets web search plus the FDA label and ClinicalTrials.gov text that
code already downloaded, and writes the rows in its own words, naming a source
for each one. Quotes are NOT required.

What code still enforces (a row failing these is removed):
  * a known row type, used once;
  * at least one named source per row;
  * report-don't-instruct wording and no drug doses (style.py);
  * length.

What code flags for the editor but does not remove ("check" warnings in the
admin portal):
  * any number in the row that is not found in the label, registry or paper
    text CarcinoS downloaded (it may be right, from web search, but it is
    not verified);
  * source links outside the primary-source list (kept for the editor, never
    shown to readers).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from .fields import FIELDS, SECTION_TITLES, is_label_field
from .labels import DrugLabel
from .sources import domain_allowed
from .style import style_issues
from .text import normalize, numbers_in

log = logging.getLogger("carcinos.care_team.write_free")

GEN_MAX_ROWS = 6
GEN_MAX_CHARS = 200

# Display order for nurses/APPs: what the visit looks like, then side effects,
# then the label warnings and monitoring, then the rest.
GEN_ORDER = ["schedule", "toxicity", "warnings", "monitoring", "sequencing", "interactions", "patient_reported"]

FIELD_GUIDE = {
    "schedule": "Schedule: route, how often, loading phase, cycle length, duration, partners; "
                "RT fractionation. No drug doses. e.g. \"Subcutaneous injection weekly for 3 doses (cycle 1), then every 3 weeks until progression or intolerance\"",
    "toxicity": "Side effects in the trial: most common with rates; serious ones named; grade ≥3 rate when "
                "notable; both arms when compared. e.g. \"Rash 81% (grade 3: 11%); fatigue, nail changes, "
                "mouth sores, swelling each ≥20%; injection reactions 16%; ILD, including 1 fatal case\"",
    "warnings": "Label warnings, boxed first, as short condition names joined by ' · '. e.g. "
                "\"Injection/allergic reactions · ILD/pneumonitis · severe skin reactions · eye toxicity · harm to a pregnancy\"",
    "monitoring": "Label monitoring: what is assessed and when. e.g. \"Observation during each injection and 2–4 hours "
                  "after the first; new or worsening breathing or eye symptoms; pregnancy status before starting\"",
    "sequencing": "Sequencing: timing relative to surgery, radiation or other therapy.",
    "interactions": "Label interactions: drugs, classes or foods, joined by ' · '.",
    "patient_reported": "Patient-reported outcomes: quality-of-life or symptom results as reported.",
}

GEN_PROMPT = """You write the "Care team" section of a CarcinoS card: a short,
factual reference for oncology nurses and advanced practice providers about
ONE study. Physicians already see a "So what" line; do not repeat it.

Search the web for this study (publication, PubMed/PMC abstract, meeting
abstract, ClinicalTrials.gov, FDA label/approval documents) and use the source
text supplied below. Write what the sources REPORT. Never invent a number; if
you are not confident a figure is from this study or this label, leave it out.

CARD
Title: {title}
Journal / source: {journal}
Population: {population}
Study / regimen: {regimen}
So what (do not repeat): {so_what}
Trial IDs: {ncts}

ROW TYPES (fill every one the sources support, up to {max_rows}, in this order):
{guide}

The examples show STYLE only; never copy their content or numbers — use only what the sources for THIS study say.
Priorities: serious or common toxicities with rates; label warnings (boxed
first); monitoring; schedule including any loading phase; then the rest.
Radiation, surgery and de-escalation trials have no label rows.

WORDING RULES (strict; a row that breaks them is removed):
  • Quick-reference style a nurse or APP can scan in a few seconds: about
    110-140 characters per row (hard limit {max_chars}). Fragments, not full
    sentences; ' · ' or ';' between items; no final period.
  • Spell out schedules and routes in plain words ("subcutaneous", "IV",
    "every 3 weeks", "weekly for 3 doses"); no order-set shorthand (no q3w,
    SC, PO, BID, "monotherapy"). Keep standard oncology terms and symbols:
    ILD, CRS, grade 3, ≥, %.
  • Keep only what changes care: no sample sizes (n=), no cohort names, no
    grade 4 or rare-percentage detail, no trial name, no "per the label".
  • Plain clinic terms when equally precise ("injection reactions", "severe
    skin reactions", "eye toxicity", "mouth sores", "harm to a pregnancy").
  • Never instruct: no imperatives (monitor, check, give, hold, avoid, consider,
    watch...), no "should", "must", "need to", "you", "patients should".
  • No drug doses or dose changes (no mg, mg/kg, mg/m2, units, dose reductions,
    premedication). Schedule words and radiation Gy/fractions are fine.
  • Each row names its source(s): for FDA label rows use "FDA label" with the
    DailyMed link if known; for trial rows give the page you used (journal,
    PubMed, ClinicalTrials.gov, meeting abstract).
If the study is negative, purely prognostic/biomarker/imaging, or nothing
practical exists, return no rows.

{source_blocks}

Reply with ONLY this JSON, nothing else:
{{"rows": [{{"field": "<row type>", "text": "...", "label_drug": "<generic name or null>",
  "sources": [{{"name": "e.g. JCO 2026 publication / FDA label / NCT06385080", "url": "https://... or null"}}]}}],
  "omit_reason": null}}
"""


def default_writer(model: str, fallback: str = "") -> Callable[[str], str]:
    """OpenAI Responses API with web search (same call the finder uses)."""
    def _write(prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI()
        last = None
        for m in [model] + ([fallback] if fallback and fallback != model else []):
            try:
                resp = client.responses.create(model=m, tools=[{"type": "web_search_preview"}], input=prompt)
                return resp.output_text or ""
            except Exception as e:
                last = e
                log.info("care-team writer: %s failed (%s)", m, e)
        raise last if last else RuntimeError("care-team writer failed")
    return _write


def build_prompt(alert: dict, ncts: list[str], source_blocks: str) -> str:
    s = alert.get("summary_json") or {}
    guide = "\n".join(f"  • {k}: {FIELD_GUIDE[k]}" for k in GEN_ORDER)
    return GEN_PROMPT.format(
        title=alert.get("title") or "", journal=s.get("journal") or "",
        population=s.get("population") or "",
        regimen=s.get("regimen_description") or s.get("intervention") or "",
        so_what=s.get("carcinos_one_liner") or "", ncts=", ".join(ncts) or "none listed",
        max_rows=GEN_MAX_ROWS, guide=guide, max_chars=GEN_MAX_CHARS,
        source_blocks=source_blocks or "(No downloaded source text; rely on web search.)",
    )


def parse_rows(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"rows": [], "omit_reason": "model reply was not readable"}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {"rows": [], "omit_reason": "model reply was not readable"}
    rows = [r for r in (data.get("rows") or []) if isinstance(r, dict)]
    return {"rows": rows, "omit_reason": data.get("omit_reason")}


def validate_free(parsed: dict, known_text: str, labels: list[DrugLabel]) -> dict:
    label_map = {normalize(l.drug): l for l in labels}
    label_by_base = {normalize(l.drug).split(" and ")[0]: l for l in labels}
    known_numbers = numbers_in(known_text)
    order = {k: i for i, k in enumerate(GEN_ORDER)}
    seen: set[str] = set()
    rows_out: list[dict] = []

    for row in (parsed.get("rows") or [])[:GEN_MAX_ROWS]:
        field = row.get("field")
        text = (row.get("text") or "").strip()
        issues: list[str] = []
        warnings: list[str] = []
        if field not in FIELDS:
            issues.append(f"unknown row type {field!r}")
        if field in seen:
            issues.append("duplicate row type")
        seen.add(field)
        if not text:
            issues.append("empty text")
        if len(text) > GEN_MAX_CHARS:
            issues.append(f"longer than {GEN_MAX_CHARS} characters")
        elif len(text) > 160:
            warnings.append(f"long for a quick scan ({len(text)} characters)")
        issues.extend(style_issues(text))

        srcs = [s for s in (row.get("sources") or []) if isinstance(s, dict) and (s.get("name") or s.get("url"))]
        if not srcs:
            issues.append("no source named")

        meta: dict = {"label_drug": None, "brand": "", "url": None, "sections": [], "links": []}
        drug = normalize(row.get("label_drug") or "")
        lab = label_map.get(drug) or label_by_base.get(drug.split(" and ")[0]) if drug else None
        if lab is None and field in FIELDS and is_label_field(field) and len(labels) == 1:
            lab = labels[0]
        if lab is not None:
            meta.update(label_drug=lab.drug, brand=lab.display_brand, url=lab.url, sections=["FDA label"])
        elif field in FIELDS and is_label_field(field):
            warnings.append("label row, but no FDA label was downloaded — check against the label")

        for s in srcs:
            url = (s.get("url") or "").strip()
            name = (s.get("name") or url)[:120]
            if url and url.startswith("https://") and domain_allowed(url):
                if not any(l["url"] == url for l in meta["links"]) and "dailymed" not in url:
                    meta["links"].append({"name": name, "url": url})
            elif url:
                warnings.append(f"source not on the primary-source list (hidden from readers): {url[:120]}")

        missing = sorted(n for n in numbers_in(text) if n not in known_numbers)
        if missing:
            warnings.append("not found in downloaded sources, check: " + ", ".join(missing))

        rows_out.append({**row, **meta, "text": text, "issues": issues, "warnings": warnings,
                         "passed": not issues, "ai_written": True})

    passing = sorted((r for r in rows_out if r["passed"]), key=lambda r: order.get(r["field"], 99))
    display = [_display(r) for r in passing]
    if display:
        status = "ready"
    elif rows_out:
        status = "needs_review"
    else:
        status = "omitted"
    return {"status": status, "omit_reason": None if rows_out else (parsed.get("omit_reason") or "nothing practical found"),
            "rows": rows_out, "display_rows": display}


def _display(r: dict) -> dict:
    return {
        "field": r["field"],
        "label": FIELDS[r["field"]]["label"],
        "text": r["text"],
        "source": "label" if r.get("label_drug") else "trial",
        "drug": r.get("label_drug"),
        "brand": r.get("brand") or "",
        "url": r.get("url"),
        "sections": r.get("sections") or [],
        "links": r.get("links") or [],
        "ai_written": True,
    }
