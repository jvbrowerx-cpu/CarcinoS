"""Prompts and strict JSON schemas for the care-team step."""

from __future__ import annotations

from .fields import FIELDS, LABEL_SECTIONS, MAX_QUOTES_PER_ROW, MAX_ROW_CHARS, MAX_ROW_CHARS_ANY, MAX_ROWS, SECTION_TITLES

# ---------------------------------------------------------------------------
# Call 1: list the drugs so we can fetch official FDA labels.
# The label text itself comes from openFDA, never from the model.
# ---------------------------------------------------------------------------

DRUG_NAMES_SCHEMA = {
    "name": "care_team_drug_names",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "generic_names": {
                "type": "array",
                "items": {"type": "string", "maxLength": 80},
                "maxItems": 4,
                "description": "Generic (non-proprietary) names of the anticancer drugs in the experimental arm, exactly as the product is named (e.g. 'amivantamab and hyaluronidase' for the subcutaneous form, 'ribociclib'). Lowercase. Empty if none (e.g. radiation-only or surgical studies).",
            },
        },
        "required": ["generic_names"],
    },
}

DRUG_NAMES_SYSTEM = (
    "List the generic names of the anticancer drugs given in the experimental "
    "arm of this study, naming the exact product including its formulation "
    "(e.g. 'amivantamab and hyaluronidase' for subcutaneous amivantamab; "
    "'ribociclib'). Do not include comparator drugs, radiation, or surgery. "
    "Return an empty list if there are none."
)

# ---------------------------------------------------------------------------
# Call 2: the care-team rows, each backed by exact quotes from allowed sources.
# ---------------------------------------------------------------------------

SOURCE_ENUM = ["paper", "registry", "web"] + LABEL_SECTIONS

ROWS_SCHEMA = {
    "name": "care_team_rows",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "include_section": {
                "type": "boolean",
                "description": "False when the sources contain nothing practical for the care team.",
            },
            "omit_reason": {
                "type": ["string", "null"],
                "maxLength": 200,
                "description": "Short reason when include_section is false; otherwise null.",
            },
            "rows": {
                "type": "array",
                "maxItems": MAX_ROWS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string", "enum": list(FIELDS)},
                        "text": {"type": "string", "maxLength": MAX_ROW_CHARS_ANY},
                        "label_drug": {
                            "type": ["string", "null"],
                            "maxLength": 80,
                            "description": "Generic name of the FDA label used, for label rows; null for paper rows.",
                        },
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": MAX_QUOTES_PER_ROW,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "source": {"type": "string", "enum": SOURCE_ENUM},
                                    "url": {
                                        "type": ["string", "null"],
                                        "maxLength": 500,
                                        "description": "For registry or web quotes: the URL shown with that source block. Null otherwise.",
                                    },
                                    "quote": {"type": "string", "maxLength": 400},
                                },
                                "required": ["source", "url", "quote"],
                            },
                        },
                    },
                    "required": ["field", "text", "label_drug", "evidence"],
                },
            },
        },
        "required": ["include_section", "omit_reason", "rows"],
    },
}


def _field_table() -> str:
    lines = []
    for key, f in FIELDS.items():
        srcs = ", ".join(f["sources"])
        lines.append(f'  • {key} ("{f["label"]}") — allowed sources: {srcs}. {f["help"]}')
    return "\n".join(lines)


ROWS_SYSTEM = f"""You extract a short "Care team" reference section for CarcinoS, a
physician-edited oncology literature service. Readers are oncology nurses and
advanced practice providers. The card already has a physician-facing "So what";
do not repeat it.

You are an EXTRACTOR, not an advisor. Every row restates what one source says.
You may only use the sources provided below: the PAPER TEXT, FDA LABEL sections,
the CLINICALTRIALS.GOV record, and VERIFIED EXCERPTS from trial source pages
(already checked word for word against pages CarcinoS downloaded). Nothing from general medical knowledge, drug-class knowledge or
your own inference is allowed. Code checks every quote word for word against the
exact source you name; anything that fails is removed.

ROWS (at most {MAX_ROWS}; each row type at most once; pick the rows most useful to the care
team for THIS study; leave out any row you cannot support):
{_field_table()}

WHAT MATTERS MOST (choose and fill rows in this order of importance):
  1. Serious or common toxicities that shape care: the most common adverse
     reactions with their rates, and any serious ones (e.g. interstitial lung
     disease, cytokine release syndrome, severe rash, cardiac or ocular toxicity).
  2. Label warnings, boxed warning first, whenever an FDA label is provided.
  3. Monitoring the label specifies, and its timing.
  4. Schedule as given in the trial, including any loading or step-up phase,
     since that sets visit and chair-time burden.
  5. Interactions, sequencing, patient-reported outcomes when notable.
Use 3-4 rows when the sources support them. Do not fill a row with a minor
detail (e.g. administration-related reactions alone) when a more important one
the sources support is left out. Never pad: no row is better than a weak row.
If a label is marked as another formulation of the same drug, its drug-level
warnings and interactions may still be used; the card will name that label.

Each row's "evidence" lists 1-{MAX_QUOTES_PER_ROW} quotes, each tagged with the source
it was copied from. A quote tagged with a label section must come from that
section of that drug's label; "paper" from the paper; "registry" from the
ClinicalTrials.gov block (give its URL); "web" from a verified excerpt (give
that excerpt's URL). Prefer the paper when it says the same thing.
Use only sources allowed for that row. Label rows set label_drug.

QUOTES: copied character for character, 8 to 40 words, no ellipses, no edits.

ROW TEXT ({MAX_ROW_CHARS} characters at most; toxicity up to {MAX_ROW_CHARS_ANY}):
  • A short factual fragment, not a sentence of advice. The row label already
    names the source, so do not add "per the label" to the text.
      ✓ "ECG at baseline and around day 14 of cycle 1; liver tests every 2 weeks for the first 2 cycles"
      ✓ "QT prolongation, hepatotoxicity, neutropenia"
      ✓ "3 weeks on, 1 week off, for 3 years, with an aromatase inhibitor"
  • Say only what the quotes say. Every number in the text must appear in that
    row's quotes.
  • Never instruct. No imperatives (monitor, check, avoid, watch, give, hold,
    teach, consider...), no "should", "must", "need to", "you", "patients should".
  • Warnings: name the conditions (e.g. "interstitial lung disease"), not
    symptoms to look out for.
  • No drug doses or dose changes of any kind (no mg, mg/m2, mg/kg, units, dose
    reductions, premedication regimens), even if the source states them.
    Schedule words (every 3 weeks, 3 weeks on/1 week off, day 14) and radiation
    fractionation (e.g. 60 Gy in 20 fractions) are allowed.
  • Toxicity: when the trial compares arms, give both arms' figures.
  • Radiation, surgery and de-escalation trials have no FDA label rows; use the
    trial rows (schedule, sequencing, toxicity, patient-reported outcomes).
  • FDA approval cards often have no paper text. Then the label is the main
    source: schedule may quote the label's clinical_studies section and
    toxicity its adverse_reactions section (set label_drug), alongside the
    label monitoring, warnings and interactions rows.
  • Never refer to an individual patient.

WHEN TO RETURN NO ROWS (include_section false, rows []):
  • Negative or neutral trial; purely prognostic, biomarker, imaging or
    modelling study; or nothing practical that the sources support.
Returning nothing is a good outcome. CarcinoS values restraint. Never pad.
"""

DISCLAIMER = (
    "Summarizes the trial publication and FDA labeling; not a substitute for "
    "prescribing information or institutional protocols."
)

ROWS_USER_TEMPLATE = """CARD
Title: {title}
Journal / source: {journal}
Population: {population}
Study / regimen: {regimen}
So what (physician-facing, do not repeat): {so_what}

PAPER TEXT
<<<
{paper_text}
>>>

{label_blocks}

{external_blocks}
"""

NO_EXTERNAL_BLOCK = "CLINICALTRIALS.GOV / VERIFIED EXCERPTS\nNone found for this card."


def registry_block(doc) -> str:
    return f"CLINICALTRIALS.GOV — {doc.name} — URL: {doc.url}\n<<<\n{doc.text}\n>>>"


def excerpts_block(excerpts: list[dict]) -> str:
    by_url: dict[str, list[dict]] = {}
    for e in excerpts:
        by_url.setdefault(e["url"], []).append(e)
    parts = []
    for url, items in by_url.items():
        lines = "\n".join(f"- ({i['field']}) {i['quote']}" for i in items)
        parts.append(f"VERIFIED EXCERPTS — {items[0].get('name', '')} — URL: {url}\n<<<\n{lines}\n>>>")
    return "\n\n".join(parts)


NO_LABELS_BLOCK = "FDA LABELS\nNone available for this card. Only trial rows (schedule, sequencing, toxicity, patient_reported) are possible."

__all__ = [
    "DRUG_NAMES_SCHEMA", "DRUG_NAMES_SYSTEM", "ROWS_SCHEMA", "ROWS_SYSTEM",
    "ROWS_USER_TEMPLATE", "NO_LABELS_BLOCK", "NO_EXTERNAL_BLOCK", "registry_block", "excerpts_block", "DISCLAIMER", "SECTION_TITLES",
]
