"""The fixed rows a care-team section may contain, and where each may come from.

This table is the core safety rule. Each row type has a neutral, descriptive
label (never a command such as "Monitor" or "Watch for") and a fixed list of
allowed sources. Code checks that every quote behind a row was found in one of
that row's allowed sources, so a fact cannot be moved into a row it does not
belong to, and nothing can come from general knowledge.
"""

from __future__ import annotations

# Order here is the display order.
FIELDS: dict[str, dict] = {
    "schedule": {
        "label": "Schedule in the trial",
        "sources": ["paper", "registry", "web", "clinical_studies"],
        "help": "How and how often the regimen was given in the study (route, loading "
                "or step-up phase, cycle pattern, duration, combination partners; RT "
                "fractionation allowed). No drug doses.",
    },
    "sequencing": {
        "label": "Sequencing in the trial",
        "sources": ["paper", "registry", "web", "clinical_studies"],
        "help": "Timing relative to other treatment in the study (e.g. RT started within "
                "a set window after surgery; concurrent vs sequential).",
    },
    "monitoring": {
        "label": "Label monitoring",
        "sources": ["dosage_and_administration", "warnings_and_cautions", "boxed_warning"],
        "help": "Tests or assessments the FDA label specifies, and their timing.",
    },
    "warnings": {
        "label": "Label warnings",
        "sources": ["boxed_warning", "warnings_and_cautions"],
        "help": "Names of the conditions the FDA label warns about (boxed warning first; "
                "e.g. QT prolongation, hepatotoxicity, interstitial lung disease). "
                "Conditions only, not symptoms to watch for.",
    },
    "interactions": {
        "label": "Label interactions",
        "sources": ["drug_interactions"],
        "help": "Drugs, drug classes or foods the FDA label lists as interacting.",
    },
    "toxicity": {
        "label": "Toxicity in the trial",
        "sources": ["paper", "registry", "web", "adverse_reactions"],
        "help": "The adverse events that matter most for care: the most common ones with "
                "their rates, plus any serious ones. When the trial compares arms, give "
                "both arms (e.g. 'late grade >=2 GI toxicity 11% vs 6%').",
        "max_chars": 220,
    },
    "patient_reported": {
        "label": "Patient-reported outcomes",
        "sources": ["paper", "registry", "web", "clinical_studies"],
        "help": "Quality-of-life or symptom outcomes the trial measured, as reported.",
    },
}

MAX_ROWS = 4
MAX_ROW_CHARS = 170          # about 20-25 words (toxicity may use up to its own max_chars)
MAX_ROW_CHARS_ANY = 220      # schema limit across all rows


def max_chars(field: str) -> int:
    return FIELDS.get(field, {}).get("max_chars", MAX_ROW_CHARS)
MAX_QUOTES_PER_ROW = 3

# FDA label sections retrieved from openFDA (a superset of the label sources above).
# clinical_studies and adverse_reactions let FDA-approval cards (which have no paper
# text) show the pivotal trial's schedule and toxicity straight from the label.
LABEL_SECTIONS = ["boxed_warning", "dosage_and_administration", "warnings_and_cautions",
                  "drug_interactions", "clinical_studies", "adverse_reactions"]

SECTION_TITLES = {
    "boxed_warning": "Boxed Warning",
    "dosage_and_administration": "Dosage and Administration",
    "warnings_and_cautions": "Warnings and Precautions",
    "drug_interactions": "Drug Interactions",
    "clinical_studies": "Clinical Studies",
    "adverse_reactions": "Adverse Reactions",
    "paper": "Trial publication",
    "registry": "ClinicalTrials.gov",
    "web": "Trial source page",
}


def is_label_field(field: str) -> bool:
    return "paper" not in FIELDS[field]["sources"]


# Sources for trial rows besides the stored abstract:
#   registry — ClinicalTrials.gov record fetched by code (sources.py)
#   web      — a primary-source page found by the finder, downloaded by code,
#              with the quote checked against the downloaded page (finder.py)
EXTERNAL_SOURCES = ["registry", "web"]
