"""
Deterministic relevance score (spec §2.5).

Per spec, this runs BEFORE the LLM and assigns 0–100 based on cheap
keyword presence. Thresholds:
  - >= 50 → KEEP
  - 30..49 → KEEP, mark low-confidence
  - < 30 → DROP

Note: this is intentionally generic and not tuned per site. Per-site
behavior comes from the modality_terms and core terms in the site config,
which are passed in.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..retrieval.pubmed import PubMedRecord
from ..disease_sites.base import DiseaseSiteConfig

# Spec §2.5 — endpoint vocabulary
ENDPOINT_TERMS = (
    "overall survival", "OS", "PFS", "progression-free survival",
    "DFS", "disease-free survival", "EFS", "event-free survival",
    "RFS", "recurrence-free", "MFS", "metastasis-free",
    "objective response", "ORR", "complete response", "partial response",
    "toxicity", "adverse event", "grade 3", "grade 4",
    "quality of life", "QoL", "patient-reported outcome", "PRO",
    "non-inferior", "non-inferiority", "noninferior",
    "hazard ratio", "HR ", "95% CI",
)

TRIAL_GUIDELINE_TERMS = (
    "randomized", "randomised",
    "phase 2", "phase II", "phase 3", "phase III",
    "noninferiority", "non-inferiority",
    "meta-analysis", "systematic review", "pooled analysis",
    "guideline", "consensus", "recommendation",
    "FDA approval", "label change", "regulatory",
)


@dataclass
class RelevanceResult:
    score: int
    keep: bool
    low_confidence: bool
    rationale: list[str]


def score_relevance(
    record: PubMedRecord,
    config: DiseaseSiteConfig,
    keep_threshold: int = 50,
    low_confidence_floor: int = 30,
) -> RelevanceResult:
    title = record.title or ""
    abstract = record.abstract or ""
    text = f"{title}\n{abstract}"

    score = 0
    notes: list[str] = []

    # +30 cancer-site core in TITLE (stronger than just abstract)
    if _any_match(title, config.free_text_core):
        score += 30
        notes.append("+30 site term in title")
    elif _any_match(abstract, config.free_text_core):
        score += 15
        notes.append("+15 site term in abstract")

    # +15 MeSH match (stronger signal than free text)
    if _any_match_lower(record.mesh_terms, config.mesh_headings):
        score += 15
        notes.append("+15 MeSH neoplasm match")

    # +20 trial / guideline keyword present
    if _any_match(text, TRIAL_GUIDELINE_TERMS):
        score += 20
        notes.append("+20 trial/guideline keyword")

    # +15 modality keyword present
    if _any_match(text, config.modality_terms):
        score += 15
        notes.append("+15 modality keyword")

    # +15 endpoint vocabulary present
    if _any_match(text, ENDPOINT_TERMS):
        score += 15
        notes.append("+15 endpoint vocabulary")

    # Negative signals
    if _looks_purely_preclinical(text):
        score -= 30
        notes.append("-30 preclinical-only signal")
    if _looks_benign_only(text, config):
        score -= 20
        notes.append("-20 non-oncology signal")
    if _looks_pediatric_only(text) and not _is_pediatric_oncology(text):
        score -= 15
        notes.append("-15 pediatric-only non-oncology")

    score = max(0, min(100, score))

    if score >= keep_threshold:
        return RelevanceResult(score, True, False, notes)
    if score >= low_confidence_floor:
        return RelevanceResult(score, True, True, notes)
    return RelevanceResult(score, False, False, notes)


# ---------------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------------

def _word_re(term: str) -> re.Pattern:
    # Token-aware: word-boundary on alphanumeric edges
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


_PRECLINICAL_HINTS = re.compile(
    r"\b(in vitro|in vivo|cell line|xenograft|mouse model|murine model|"
    r"organoid|preclinical|knockout mice|transgenic mice)\b",
    re.IGNORECASE,
)
_CLINICAL_BRIDGE = re.compile(
    r"\b(patient|clinical trial|cohort|biopsy|circulating tumor|ctDNA|"
    r"clinical|prognostic|predictive)\b",
    re.IGNORECASE,
)
_BENIGN_GYN = re.compile(
    r"\b(endometriosis|fibroid|leiomyoma|polycystic ovary|infertility)\b",
    re.IGNORECASE,
)
_PEDIATRIC_HINTS = re.compile(
    r"\b(pediatric|paediatric|child|children|adolescent|infant)\b",
    re.IGNORECASE,
)
_PED_ONC_HINTS = re.compile(
    r"\b(neuroblastoma|medulloblastoma|Wilms|hepatoblastoma|retinoblastoma|"
    r"rhabdomyosarcoma|Ewing|DIPG|childhood leukemia|childhood lymphoma)\b",
    re.IGNORECASE,
)


def _any_match(text: str, terms: Sequence[str]) -> bool:
    return any(_word_re(t).search(text) for t in terms)


def _any_match_lower(values: Sequence[str], terms: Sequence[str]) -> bool:
    lower_vals = [v.lower() for v in values]
    return any(t.lower() in lower_vals for t in terms)


def _looks_purely_preclinical(text: str) -> bool:
    return bool(_PRECLINICAL_HINTS.search(text)) and not _CLINICAL_BRIDGE.search(text)


def _looks_benign_only(text: str, config: DiseaseSiteConfig) -> bool:
    if config.code != "gynecologic":
        return False
    return bool(_BENIGN_GYN.search(text)) and not _any_match(
        text, ("cancer", "carcinoma", "neoplasm", "malignancy", "tumor", "tumour")
    )


def _looks_pediatric_only(text: str) -> bool:
    return bool(_PEDIATRIC_HINTS.search(text))


def _is_pediatric_oncology(text: str) -> bool:
    return bool(_PED_ONC_HINTS.search(text))


# ---------------------------------------------------------------------------
# Batch entry
# ---------------------------------------------------------------------------

def score_batch(
    records: Iterable[PubMedRecord],
    config: DiseaseSiteConfig,
) -> list[tuple[PubMedRecord, RelevanceResult]]:
    return [(r, score_relevance(r, config)) for r in records]
