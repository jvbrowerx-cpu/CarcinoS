"""
Integration tests: ASTRO portal records through the pipeline.

Verifies that retrieve_astro_records() output:
  1. Is merged by _retrieve() alongside the unchanged PubMed conference lane
  2. Passes the date-freshness gate (_date_is_fresh)
  3. Is force-kept by filter_by_pubtype (conference_source bypass)
  4. Receives rel_bypass=True in the canonicalization loop
  5. Scores QS_MAJOR_CONFERENCE when the abstract contains trial language
  6. Falls to QS_NONE / mini-triage when abstract lacks trial language

No live network calls are made in any test.
"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Unstub the filter modules so real implementations are loaded.
# conftest.py stubs carcinos_ingestion.filters.{pubtype,signal_score} to
# no-ops so that pipeline.py imports cleanly; but these integration tests
# need the real code.  Removing the stubs here (before any test imports)
# lets Python find the real .py files on disk instead.
# ---------------------------------------------------------------------------
for _m in list(sys.modules.keys()):
    if _m in (
        "carcinos_ingestion.filters",
        "carcinos_ingestion.filters.pubtype",
        "carcinos_ingestion.filters.signal_score",
        "carcinos_ingestion.filters.dedupe",
        "carcinos_ingestion.filters.relevance",
    ):
        del sys.modules[_m]


# ---------------------------------------------------------------------------
# Shared fixture: a minimal ASTRO PubMedRecord
# ---------------------------------------------------------------------------

ASTRO_URL = "https://amportal.astro.org/sessions/ct-01-22948/maverick-114268"
RUN_DATE  = date(2026, 9, 28)   # inside the ASTRO window


def _make_astro_record(abstract: str = "") -> object:
    """Return a PubMedRecord as astro.py produces it."""
    from carcinos_ingestion.retrieval.pubmed import PubMedRecord
    return PubMedRecord(
        pmid="ASTRO2026-114268",
        title="MAVERICK: A Phase III Trial of Brain MRI Without PCI for SCLC",
        abstract=abstract or (
            "Purpose/Objective(s): To evaluate MRI surveillance vs PCI. "
            "Materials/Methods: Phase III randomized trial, 304 patients. "
            "Results: CFFS improved (HR 0.60, p=0.001); overall survival similar. "
            "Conclusion: MRI surveillance preferred."
        ),
        journal="International Journal of Radiation Oncology Biology Physics",
        pub_date="2026-09-27",
        publication_types=["Congress"],
        conference_source="ASTRO",
        url_override=ASTRO_URL,
    )


def _make_pubmed_conf_record() -> object:
    """Return a PubMedRecord as the PubMed conference lane produces."""
    from carcinos_ingestion.retrieval.pubmed import PubMedRecord
    return PubMedRecord(
        pmid="39123456",
        title="ESMO 2026: KEYNOTE-999 Updated OS in NSCLC",
        abstract="Phase III trial. Pembrolizumab vs chemo. OS HR 0.72.",
        journal="Annals of Oncology",
        pub_date="2026-09-20",
        publication_types=["Congress"],
        conference_source="ESMO",
    )


# ---------------------------------------------------------------------------
# Helper: inject the stubs _retrieve() needs for its lazy imports
# ---------------------------------------------------------------------------

def _inject_retrieve_deps(conf_records, astro_records):
    """
    _retrieve() does lazy `from .X import Y` calls for several heavy modules.
    Inject lightweight stubs so the function can run without live services.
    Returns a context-manager stack to clean up after the test.
    """
    # disease_sites.base needs _journal_block and _date_block in addition to
    # what conftest provides.  Extend the existing stub in place.
    import carcinos_ingestion.disease_sites.base as ds_base
    if not hasattr(ds_base, "_journal_block"):
        ds_base._journal_block = lambda *a, **kw: "journal_q"
    if not hasattr(ds_base, "_date_block"):
        ds_base._date_block = lambda *a, **kw: "date_q"

    # Inject a fake conferences module so `from .retrieval.conferences import ...` works
    fake_conf_mod = types.ModuleType("carcinos_ingestion.retrieval.conferences")
    fake_conf_mod.retrieve_conference_records = MagicMock(return_value=conf_records)
    sys.modules["carcinos_ingestion.retrieval.conferences"] = fake_conf_mod

    # Stub the FDA lane module so `from .retrieval.fda import ...` doesn't fail
    # when include_fda=True; we call with include_fda=False so this is just safety.
    fake_fda_mod = types.ModuleType("carcinos_ingestion.retrieval.fda")
    fake_fda_mod.retrieve_fda_records = MagicMock(return_value=[])
    sys.modules.setdefault("carcinos_ingestion.retrieval.fda", fake_fda_mod)

    # Patch retrieve_astro_records on the real astro module
    astro_patch = patch(
        "carcinos_ingestion.retrieval.astro.retrieve_astro_records",
        return_value=astro_records,
    )
    return astro_patch, fake_conf_mod


def _call_retrieve(astro_records, conf_records):
    from carcinos_ingestion.pipeline import _retrieve

    fake_pubmed = MagicMock()
    fake_pubmed.esearch.return_value = []
    fake_pubmed.efetch.return_value  = []

    fake_site = MagicMock()
    fake_site.code = "thoracic"
    fake_site.study_type_block.return_value        = "cancer"
    fake_site.build_journal_force_query.return_value = "journal_q"

    astro_patch, _ = _inject_retrieve_deps(conf_records, astro_records)
    with astro_patch:
        return _retrieve(
            fake_pubmed, fake_site,
            start=RUN_DATE - timedelta(days=7), end=RUN_DATE,
            max_pmids=200,
            include_conferences=True,
            include_fda=False,
        )


# ---------------------------------------------------------------------------
# 1. _retrieve() merges Lane 3 + Lane 3b; Lane 3 is not removed
# ---------------------------------------------------------------------------

class TestRetrieveMergesLanes:

    def test_astro_records_present_in_output(self):
        result = _call_retrieve([_make_astro_record()], [_make_pubmed_conf_record()])
        pmids  = [r.pmid for r in result]
        assert "ASTRO2026-114268" in pmids, "ASTRO direct record missing from _retrieve() output"

    def test_pubmed_conference_lane_records_present(self):
        """Lane 3 (PubMed conference) must NOT be removed."""
        result = _call_retrieve([_make_astro_record()], [_make_pubmed_conf_record()])
        pmids  = [r.pmid for r in result]
        assert "39123456" in pmids, \
            "PubMed conference lane record missing — Lane 3 is broken"

    def test_astro_records_prepended_before_pubmed_conf(self):
        result = _call_retrieve([_make_astro_record()], [_make_pubmed_conf_record()])
        astro_idx = next(i for i, r in enumerate(result) if r.pmid == "ASTRO2026-114268")
        conf_idx  = next(i for i, r in enumerate(result) if r.pmid == "39123456")
        assert astro_idx < conf_idx, \
            "ASTRO records should be prepended before PubMed conf records"

    def test_no_astro_records_outside_window(self):
        """When retrieve_astro_records returns [] (outside window), Lane 3 still works."""
        result = _call_retrieve([], [_make_pubmed_conf_record()])
        pmids  = [r.pmid for r in result]
        assert "39123456" in pmids
        assert not any("ASTRO" in p for p in pmids)

    def test_astro_lane_failure_does_not_crash_pipeline(self):
        """A scraper exception must not kill the whole run (non-fatal by design)."""
        from carcinos_ingestion.pipeline import _retrieve

        fake_pubmed = MagicMock()
        fake_pubmed.esearch.return_value = []
        fake_pubmed.efetch.return_value  = []

        fake_site = MagicMock()
        fake_site.code = "thoracic"
        fake_site.study_type_block.return_value        = "cancer"
        fake_site.build_journal_force_query.return_value = "journal_q"

        conf = _make_pubmed_conf_record()
        _, fake_conf_mod = _inject_retrieve_deps([conf], [conf])
        fake_conf_mod.retrieve_conference_records.return_value = [conf]

        with patch(
            "carcinos_ingestion.retrieval.astro.retrieve_astro_records",
            side_effect=RuntimeError("portal down"),
        ):
            result = _retrieve(
                fake_pubmed, fake_site,
                start=RUN_DATE - timedelta(days=7), end=RUN_DATE,
                max_pmids=200,
                include_conferences=True,
                include_fda=False,
            )

        # PubMed conference record still present despite ASTRO failure
        assert any(r.pmid == "39123456" for r in result), \
            "PubMed conference lane must survive an ASTRO scraper failure"


# ---------------------------------------------------------------------------
# 2. Date freshness gate (_date_is_fresh)
# ---------------------------------------------------------------------------

class TestDateFreshness:

    def _fresh(self, pub_date, end=RUN_DATE, days=7):
        from carcinos_ingestion.pipeline import _date_is_fresh
        cutoff = end - timedelta(days=days)
        return _date_is_fresh(pub_date=pub_date, entrez_date="", cutoff=cutoff, end=end)

    def test_session_day_passes(self):
        assert self._fresh("2026-09-27"), "Sep 27 abstract should pass freshness for Sep 28 run"

    def test_meeting_open_day_passes(self):
        assert self._fresh("2026-09-25"), "First day of meeting should pass"

    def test_two_weeks_before_fails(self):
        assert not self._fresh("2026-09-10"), "Abstract >14 days old should fail"

    def test_empty_pub_date_passes(self):
        assert self._fresh(""), "Empty pub_date must pass (safe behaviour for non-PubMed records)"

    def test_future_date_outside_window_fails(self):
        assert not self._fresh("2026-10-31"), "Future date outside [cutoff, end] should fail"


# ---------------------------------------------------------------------------
# 3. Pubtype filter: conference_source force-keep
# ---------------------------------------------------------------------------

class TestPubtypeForceKeep:

    def test_astro_record_is_force_kept(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        rec    = _make_astro_record()
        result = filter_by_pubtype([rec], journal_force_keep=[])
        kept   = [r.pmid for r, _ in result]
        assert "ASTRO2026-114268" in kept, \
            "ASTRO record must be force-kept via conference_source regardless of pub type"

    def test_lane3_pubmed_conf_also_force_kept(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        rec    = _make_pubmed_conf_record()
        result = filter_by_pubtype([rec], journal_force_keep=[])
        kept   = [r.pmid for r, _ in result]
        assert "39123456" in kept, \
            "PubMed conference lane record must also be force-kept"

    def test_plain_record_without_conference_source_is_not_force_kept(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        from carcinos_ingestion.retrieval.pubmed import PubMedRecord
        # A poster abstract with no conference tag and an excluded pub type
        rec = PubMedRecord(
            pmid="11111111", title="Case report", abstract="A case.",
            journal="Journal of Cases", pub_date="2026-09-20",
            publication_types=["Case Reports"],
        )
        result = filter_by_pubtype([rec], journal_force_keep=[])
        kept   = [r.pmid for r, _ in result]
        assert "11111111" not in kept, \
            "Case report without conference_source must not be force-kept"


# ---------------------------------------------------------------------------
# 4. Relevance bypass for conference_source records
# ---------------------------------------------------------------------------

class TestRelevanceBypass:
    """
    Records with conference_source != None bypass Gate 1 (relevance scoring).
    The bypass condition `r.conference_source not in (None, "")` is inlined in
    pipeline.py's canonicalization loop; we test it directly.
    """

    def test_astro_record_triggers_rel_bypass(self):
        rec = _make_astro_record()
        assert rec.conference_source not in (None, ""), \
            "ASTRO record must set rel_bypass=True in the pipeline"

    def test_esmo_record_triggers_rel_bypass(self):
        rec = _make_pubmed_conf_record()
        assert rec.conference_source not in (None, ""), \
            "PubMed conference record must also trigger rel_bypass"

    def test_plain_pubmed_record_does_not_bypass(self):
        from carcinos_ingestion.retrieval.pubmed import PubMedRecord
        rec = PubMedRecord(
            pmid="99999999", title="A PubMed paper", abstract="Some text.",
            journal="JCO", pub_date="2026-09-25",
        )
        assert rec.conference_source in (None, ""), \
            "PubMed record with no conference_source must NOT trigger rel_bypass"


# ---------------------------------------------------------------------------
# 5. Signal scoring: QS_MAJOR_CONFERENCE for ASTRO + trial language
# ---------------------------------------------------------------------------

class TestSignalScoring:

    def _score(self, text: str, cs: str = "ASTRO") -> bool:
        from carcinos_ingestion.filters.signal_score import _is_major_conference_lba
        return _is_major_conference_lba(text, ["Congress"], cs)

    def test_phase3_randomized_gets_major_conf_signal(self):
        assert self._score("Phase III randomized trial. Overall survival HR 0.60, p=0.001."), \
            "Phase III RCT with OS data should score QS_MAJOR_CONFERENCE"

    def test_lba_label_gets_major_conf_signal(self):
        assert self._score("Late-breaking abstract: SBRT for early-stage NSCLC."), \
            "LBA label should score QS_MAJOR_CONFERENCE"

    def test_plenary_label_gets_major_conf_signal(self):
        assert self._score("Plenary session presentation of updated RTOG results."), \
            "Plenary label should score QS_MAJOR_CONFERENCE"

    def test_practice_changing_language_gets_major_conf_signal(self):
        assert self._score("Practice-changing results. Standard of care revised."), \
            "Practice-changing language should score QS_MAJOR_CONFERENCE"

    def test_fda_approval_language_gets_major_conf_signal(self):
        assert self._score("FDA-approved regimen confirmed in this phase III trial."), \
            "FDA-approved language should score QS_MAJOR_CONFERENCE"

    def test_narrative_education_session_does_not_score(self):
        assert not self._score(
            "An overview of historical stereotactic techniques and equipment evolution."
        ), "Narrative education session must not score QS_MAJOR_CONFERENCE"

    def test_non_astro_source_requires_combined_lba_pattern(self):
        """
        A paper with no conference_source must have 'ASTRO' + 'LBA' adjacent in text
        to score — a plain ASTRO mention without LBA context doesn't qualify.
        """
        assert not self._score(
            "Presented at the ASTRO 2026 meeting.", cs=""
        ), "ASTRO mention without LBA context and no conference_source tag must not score"

    def test_astro_tagged_record_with_maverick_abstract(self):
        """Regression: the MAVERICK-style abstract must score QS_MAJOR_CONFERENCE."""
        rec = _make_astro_record()
        assert self._score(f"{rec.title} {rec.abstract}", cs=rec.conference_source), \
            "MAVERICK abstract with Phase III + OS + HR data must score QS_MAJOR_CONFERENCE"


# ---------------------------------------------------------------------------
# 6. End-to-end: ASTRO record passes all pre-canonical gates
# ---------------------------------------------------------------------------

class TestEndToEndCanonicalPool:
    """
    Feed a synthetic ASTRO record through each gate in sequence.
    _date_is_fresh → filter_by_pubtype → rel_bypass → signal scoring.
    If all four pass, the record would reach to_canonical() and Pass 2 in a live run.
    """

    def test_astro_record_passes_all_pre_canonical_gates(self):
        from carcinos_ingestion.pipeline import _date_is_fresh
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        from carcinos_ingestion.filters.signal_score import _is_major_conference_lba

        rec = _make_astro_record()

        # Gate A: date freshness
        cutoff = RUN_DATE - timedelta(days=14)
        assert _date_is_fresh(
            pub_date=rec.pub_date, entrez_date="",
            cutoff=cutoff, end=RUN_DATE,
        ), "Gate A failed: date freshness"

        # Gate B: pubtype filter force-keep
        kept = filter_by_pubtype([rec], journal_force_keep=[])
        assert len(kept) == 1, "Gate B failed: pubtype filter dropped the ASTRO record"

        # Gate C: relevance bypass
        assert rec.conference_source not in (None, ""), \
            "Gate C failed: conference_source not set — record would fail rel_bypass"

        # Gate D: signal → QS_MAJOR_CONFERENCE (trial text)
        text = f"{rec.title} {rec.abstract}"
        assert _is_major_conference_lba(text, rec.publication_types, rec.conference_source), \
            "Gate D failed: abstract should score QS_MAJOR_CONFERENCE"
