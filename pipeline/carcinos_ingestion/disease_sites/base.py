"""
Per-site query builder base class.

Encodes the 6-block PubMed query structure from CarcinoS spec §1:
  1. Cancer-site core (free text)
  2. MeSH augmentation
  3. Study-type expansion (shared)
  4. Modality expansion (per-site)
  5. Journal/authority whitelist (force-include)
  6. Date window
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Sequence


# ---------------------------------------------------------------------------
# SHARED BLOCKS — same across all sites per spec §1.2 and §1.4
# ---------------------------------------------------------------------------

# Spec §1.2 — study-type expansion (volume driver, not vibes)
STUDY_TYPE_TERMS: Sequence[str] = (
    "randomized", "randomised",
    "phase 2", "phase II", "phase 3", "phase III",
    "trial", "noninferiority", "superiority", "equivalence",
    "meta-analysis", "systematic review", "pooled analysis",
    "guideline", "consensus", "recommendation",
    "cohort", "registry", "population-based", "epidemiology",
    "survival", "progression-free", "overall survival",
    "toxicity", "quality of life",
)

# Spec §1.4 — top-tier oncology / multidisciplinary journals shared across sites.
# Site modules append site-specific journals to this list.

# Tier 1: Guaranteed retrieval — never capped. These are the journals most
# likely to contain practice-changing results. Retrieved in a dedicated lane
# with a higher PMID budget so NEJM/Lancet/JCO papers are never crowded out.
TIER1_JOURNAL_WHITELIST: Sequence[str] = (
    "New England Journal of Medicine",
    "NEJM",
    "NEJM Evidence",
    "Lancet",
    "Lancet Oncology",
    "Journal of Clinical Oncology",
    "JAMA",
    "JAMA Oncology",
)

# Tier 2: Standard whitelist — shared across all sites, included in the
# force-include lane alongside site-specific journals.
SHARED_JOURNAL_WHITELIST: Sequence[str] = (
    # Tier 1 journals also included here so whitelist() returns the full set
    "New England Journal of Medicine",
    "NEJM",
    "NEJM Evidence",
    "Lancet",
    "Lancet Oncology",
    "Journal of Clinical Oncology",
    "JAMA",
    "JAMA Oncology",
    # High-impact multidisciplinary
    "JNCI",
    "Journal of the National Cancer Institute",
    "CA: A Cancer Journal for Clinicians",
    "Nature Medicine",
    "Nature Cancer",
    # ESMO flagship → covers ESMO Congress supplements
    "Annals of Oncology",
    # ASTRO flagship → covers ASTRO Annual Meeting supplements
    "International Journal of Radiation Oncology Biology Physics",
    # AACR conference supplements only — Cancer Discovery removed from
    # general whitelist as it pulls high volumes of translational/early-phase
    # content; the conference lane handles AACR abstracts directly.
    "Cancer Research",
    # Immunotherapy / IO
    "Journal for ImmunoTherapy of Cancer",
    # JCO subspecialty journals
    "JCO Precision Oncology",
    "JCO Oncology Practice",
)

# Authority bodies (spec §1.4) — these are not journal names but appear in
# titles/abstracts of guideline updates we want to force-include.
SHARED_AUTHORITY_TERMS: Sequence[str] = (
    "NCCN", "ASCO", "ESMO", "ACS",
)


# ---------------------------------------------------------------------------
# QUERY HELPERS
# ---------------------------------------------------------------------------

def _or_block(terms: Sequence[str], wrap: bool = True) -> str:
    """OR-join a list of free-text terms. Quotes any multi-word term."""
    parts = []
    for t in terms:
        t = t.strip()
        if " " in t and not (t.startswith('"') and t.endswith('"')):
            parts.append(f'"{t}"')
        else:
            parts.append(t)
    joined = " OR ".join(parts)
    return f"({joined})" if wrap else joined


def _mesh_block(headings: Sequence[str]) -> str:
    """OR-join a list of MeSH headings using PubMed [MeSH] tag."""
    parts = [f'"{h}"[MeSH]' for h in headings]
    return "(" + " OR ".join(parts) + ")"


def _journal_block(journals: Sequence[str]) -> str:
    """OR-join a list of journal names using PubMed [Journal] tag."""
    parts = [f'"{j}"[Journal]' for j in journals]
    return "(" + " OR ".join(parts) + ")"


def _date_block(start: date, end: date) -> str:
    """
    PubMed date filter covering BOTH electronic publication date and Entrez
    (indexing) date. This is critical: NEJM/Lancet papers are published
    electronically weeks before the print issue date that [Date - Publication]
    uses. Without [Date - Entrez], epub-ahead-of-print papers are invisible
    until the print issue ships — causing high-impact papers to be missed.
    """
    fmt = "%Y/%m/%d"
    s = start.strftime(fmt)
    e = end.strftime(fmt)
    pub_range   = f'("{s}"[Date - Publication] : "{e}"[Date - Publication])'
    entrez_range = f'("{s}"[Date - Entrez] : "{e}"[Date - Entrez])'
    return f"({pub_range} OR {entrez_range})"


# ---------------------------------------------------------------------------
# SITE CONFIG
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiseaseSiteConfig:
    """
    Per-site search configuration. Each subclass under disease_sites/ instantiates this.

    The query is built as:

        ( CORE_FREE_TEXT_BLOCK AND TUMOR_TERMS )  OR  MESH_BLOCK
        AND STUDY_TYPE_BLOCK
        AND MODALITY_BLOCK
        AND DATE_BLOCK

    Journal whitelist is applied as a *separate* force-include query
    (spec §1.4 — these get retrieved even when keywords are weak) and unioned
    after retrieval, not AND-ed into the main query.
    """

    code: str                              # matches disease_site_code enum in 01_schema.sql
    name: str                              # human-readable, e.g. "Head and Neck"
    free_text_core: Sequence[str]          # anatomic/disease terms
    tumor_terms: Sequence[str] = (         # spec §1.1 — almost universal
        "cancer", "carcinoma", "malignancy", "neoplasm", "tumor", "tumour",
    )
    mesh_headings: Sequence[str] = field(default_factory=tuple)
    modality_terms: Sequence[str] = field(default_factory=tuple)
    site_journals: Sequence[str] = field(default_factory=tuple)

    # ----- query construction ---------------------------------------------

    def core_block(self) -> str:
        free = _or_block(self.free_text_core)
        tumor = _or_block(self.tumor_terms)
        free_text = f"({free} AND {tumor})"
        if self.mesh_headings:
            return f"({free_text} OR {_mesh_block(self.mesh_headings)})"
        return free_text

    def study_type_block(self) -> str:
        return _or_block(STUDY_TYPE_TERMS)

    def modality_block(self) -> str:
        return _or_block(self.modality_terms)

    def journal_whitelist(self) -> Sequence[str]:
        # Site-specific journals first so per-site results outrank generic ones
        # when both match, then the shared multidisciplinary tier.
        return tuple(self.site_journals) + tuple(SHARED_JOURNAL_WHITELIST)

    # ----- public API -----------------------------------------------------

    def build_main_query(self, start: date, end: date) -> str:
        """The high-recall keyword-driven query (spec §1.6)."""
        return " AND ".join([
            self.core_block(),
            self.study_type_block(),
            self.modality_block(),
            _date_block(start, end),
        ])

    def build_journal_force_query(self, start: date, end: date) -> str:
        """
        Force-include lane (spec §1.4). Anything published in a whitelisted
        venue within the window, narrowed only by the cancer-site core so we
        don't pull non-oncology content from broad journals like Lancet.
        """
        return " AND ".join([
            self.core_block(),
            _journal_block(self.journal_whitelist()),
            _date_block(start, end),
        ])

    def build_default_window(self, days: int = 7) -> tuple[date, date]:
        """Rolling N-day window (spec §1.5). Default 7 days."""
        end = date.today()
        start = end - timedelta(days=days)
        return start, end
