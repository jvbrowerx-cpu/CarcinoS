"""Code-only checks on the model's rows. No model is involved.

Per row, all of these must hold or the row is removed from what readers see:
  * the row type is known and appears only once;
  * every quote is tagged with a source that row type is allowed to use;
  * label quotes name a label that was actually retrieved, and the quote is
    found word for word in that exact section of that label;
  * paper quotes are found word for word in the paper text;
  * registry / web quotes name a page CarcinoS downloaded itself, and are found
    word for word in that downloaded page;
  * every number in the row text appears in that row's own quotes;
  * the text passes the style checks (no instructions, no dosing) and fits.

Card outcome:
  ready         at least one row passed; only passing rows are shown
  needs_review  rows were proposed but none passed; held for the editor
  omitted       the model found nothing practical in the sources
"""

from __future__ import annotations

import re

from .fields import FIELDS, LABEL_SECTIONS, MAX_ROWS, SECTION_TITLES, is_label_field, max_chars
from .labels import DrugLabel
from .style import style_issues
from .text import normalize, numbers_in, quote_in

# Small numbers that are harmless in prose ("2 cycles" still needs a quote containing 2).
_ALLOWED_NUMBERS: set[str] = set()


def _check_row(row: dict, paper_text: str, labels: dict[str, DrugLabel], external: dict) -> tuple[list[str], dict]:
    issues: list[str] = []
    field = row.get("field")
    text = (row.get("text") or "").strip()
    spec = FIELDS.get(field)
    meta: dict = {"label_drug": None, "url": None, "sections": [], "links": []}

    if spec is None:
        return [f"unknown row type {field!r}"], meta
    if not text:
        issues.append("empty text")
    if len(text) > max_chars(field):
        issues.append(f"longer than {max_chars(field)} characters")

    lab = None
    uses_label = is_label_field(field) or any(
        (ev.get("source") or "") in LABEL_SECTIONS for ev in (row.get("evidence") or []))
    if uses_label:
        drug = normalize(row.get("label_drug") or "")
        lab = labels.get(drug)
        if lab is None:
            issues.append(f"cites an FDA label that was not retrieved: {row.get('label_drug')!r}")
        else:
            meta.update(label_drug=lab.drug, brand=lab.display_brand, url=lab.url)

    evidence = row.get("evidence") or []
    if not evidence:
        issues.append("no supporting quote")
    quote_text = []
    for ev in evidence:
        src = ev.get("source")
        quote = ev.get("quote") or ""
        if src not in spec["sources"]:
            issues.append(f"source '{src}' is not allowed for {spec['label']}")
            ev["verified"] = False
            continue
        doc = None
        if src == "paper":
            ok = quote_in(quote, paper_text)
        elif src in ("registry", "web"):
            doc = external.get(ev.get("url") or "")
            ok = bool(doc) and doc.kind == src and quote_in(quote, doc.text)
        else:
            ok = bool(lab) and quote_in(quote, lab.sections.get(src, ""))
        ev["verified"] = ok
        if ok:
            quote_text.append(quote)
            if src not in meta["sections"]:
                meta["sections"].append(src)
            if doc and not any(l["url"] == doc.url for l in meta["links"]):
                meta["links"].append({"name": doc.name, "url": doc.url})
        else:
            if src == "paper":
                where = "the paper"
            elif src in ("registry", "web"):
                where = f"a downloaded {src} page ({ev.get('url') or 'no URL given'})"
            else:
                where = f"{SECTION_TITLES.get(src, src)} of the {row.get('label_drug')} label"
            issues.append(f"quote not found in {where}: {quote[:100]!r}")

    for n in sorted(numbers_in(text) - _ALLOWED_NUMBERS):
        if n not in numbers_in(" ".join(quote_text)):
            issues.append(f"number {n} is not in this row's quotes")

    # Comparative toxicity must show both arms: if the quotes give two or more
    # percentages but the row shows only one, the comparison has been dropped.
    if field == "toxicity":
        pct_quotes = re.findall(r"\d+(?:\.\d+)?\s*%", " ".join(quote_text))
        pct_text = re.findall(r"\d+(?:\.\d+)?\s*%", text)
        if len(pct_quotes) >= 2 and len(pct_text) == 1:
            issues.append("shows only one arm; the quotes compare arms")

    issues.extend(style_issues(text))
    return issues, meta


def validate(parsed: dict, paper_text: str, labels: list[DrugLabel], external: dict | None = None) -> dict:
    if not parsed.get("include_section"):
        return {"status": "omitted", "omit_reason": parsed.get("omit_reason") or "nothing practical in the sources",
                "rows": [], "display_rows": []}

    label_map = {lab.drug: lab for lab in labels}
    seen: set[str] = set()
    rows_out: list[dict] = []
    for row in (parsed.get("rows") or [])[:MAX_ROWS]:
        issues, meta = _check_row(row, paper_text, label_map, external or {})
        if row.get("field") in seen:
            issues.append("duplicate row type")
        seen.add(row.get("field"))
        rows_out.append({**row, **meta, "issues": issues, "passed": not issues})

    # Display order follows FIELDS, not the model's order.
    order = {k: i for i, k in enumerate(FIELDS)}
    passing = sorted((r for r in rows_out if r["passed"]), key=lambda r: order.get(r["field"], 99))
    display = [display_row(r) for r in passing]

    if display:
        status = "ready"
    elif rows_out:
        status = "needs_review"
    else:
        status = "omitted"
    return {"status": status, "omit_reason": None if rows_out else "no rows proposed",
            "rows": rows_out, "display_rows": display}


def display_row(r: dict) -> dict:
    """The minimal record readers see (and the editor can edit)."""
    return {
        "field": r["field"],
        "label": FIELDS[r["field"]]["label"],
        "text": (r.get("text") or "").strip(),
        "source": "label" if (is_label_field(r["field"]) or r.get("label_drug")) else "trial",
        "drug": r.get("label_drug"),
        "brand": r.get("brand") or "",
        "url": r.get("url"),
        "sections": [SECTION_TITLES.get(s, s) for s in r.get("sections", [])],
        "links": r.get("links") or [],
    }
