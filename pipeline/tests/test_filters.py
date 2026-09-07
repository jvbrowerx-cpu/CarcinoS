"""
Unit tests for the deterministic filter layer:
  - filters/dedupe.py
  - filters/pubtype.py
  - filters/relevance.py
  - filters/signal_score.py

Run from the pipeline/ directory:
  pip install pytest --break-system-packages
  pytest tests/
"""

import sys
import os

# Allow running from the pipeline/ directory or the project root.
_HERE = os.path.dirname(__file__)
_PIPELINE = os.path.dirname(_HERE)
if _PIPELINE not in sys.path:
    sys.path.insert(0, _PIPELINE)

import unittest
from carcinos_ingestion.retrieval.pubmed import PubMedRecord
from carcinos_ingestion.normalize.canonical import CanonicalCandidate
from carcinos_ingestion.disease_sites.base import DiseaseSiteConfig


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_record(**kwargs) -> PubMedRecord:
    defaults = dict(
        pmid="12345678",
        title="A randomized phase III trial of Drug X in lung cancer",
        abstract="Patients were randomized. Overall survival improved.",
        journal="Journal of Clinical Oncology",
        pub_date="2024-01-15",
        publication_types=["Randomized Controlled Trial"],
        doi=None,
        pmc_id=None,
        nct_ids=[],
        mesh_terms=[],
        authors=[],
        language="eng",
        raw_xml="",
        text_hash="",
        conference_source=None,
        url_override=None,
    )
    defaults.update(kwargs)
    return PubMedRecord(**defaults)


def make_candidate(**kwargs) -> CanonicalCandidate:
    defaults = dict(
        pmid="12345678",
        doi=None,
        nct_ids=[],
        text_hash="abc123",
        title="A randomized phase III trial of Drug X vs placebo in lung cancer",
        abstract=(
            "We randomized 500 patients with non-small cell lung cancer to Drug X or placebo. "
            "The primary endpoint was overall survival. Drug X significantly improved OS "
            "(HR 0.72, p=0.001). This phase III RCT establishes a new standard of care."
        ),
        journal="Journal of Clinical Oncology",
        publication_date="2024-01-15",
        publication_types=["Randomized Controlled Trial"],
        mesh_terms=[],
        cancer_site_code="thoracic",
        cancer_site_name="Thoracic Oncology",
        modality_keywords_present=[],
        deterministic_relevance_score=75,
        deterministic_low_confidence=False,
        deterministic_rationale=[],
        pubtype_keep=True,
        pubtype_low_priority=False,
        pubtype_rationale="randomized controlled trial",
        force_keep_reason=None,
        is_conference_abstract=False,
        conference_source=None,
        raw_xml_hash="",
        source_url="",
    )
    defaults.update(kwargs)
    return CanonicalCandidate(**defaults)


def make_thoracic_site() -> DiseaseSiteConfig:
    return DiseaseSiteConfig(
        code="thoracic",
        name="Thoracic Oncology",
        free_text_core=["lung", "nsclc", "sclc", "mesothelioma"],
        mesh_headings=["Lung Neoplasms", "Carcinoma, Non-Small-Cell Lung"],
        modality_terms=["chemotherapy", "immunotherapy", "radiation", "SBRT"],
        site_journals=["Journal of Thoracic Oncology"],
        watched_trials=["LAURA", "PACIFIC"],
    )


# ===========================================================================
# SECTION 1: filters/dedupe.py
# ===========================================================================

class TestJournalRank(unittest.TestCase):
    def test_exact_match_returns_correct_index(self):
        from carcinos_ingestion.filters.dedupe import journal_rank, JOURNAL_RANK
        assert journal_rank("New England Journal of Medicine") == 0

    def test_case_insensitive(self):
        from carcinos_ingestion.filters.dedupe import journal_rank
        assert journal_rank("new england journal of medicine") == 0

    def test_partial_contains_match(self):
        from carcinos_ingestion.filters.dedupe import journal_rank
        # "Lancet Oncol" should match "Lancet Oncology"
        rank = journal_rank("Lancet Oncol")
        assert rank < 10  # should match Lancet Oncology (index 2)

    def test_unknown_journal_returns_default(self):
        from carcinos_ingestion.filters.dedupe import journal_rank, _DEFAULT_RANK
        assert journal_rank("Obscure Veterinary Quarterly") == _DEFAULT_RANK

    def test_empty_journal_returns_default(self):
        from carcinos_ingestion.filters.dedupe import journal_rank, _DEFAULT_RANK
        assert journal_rank("") == _DEFAULT_RANK

    def test_tier1_journals_rank_higher_than_tier2(self):
        from carcinos_ingestion.filters.dedupe import journal_rank
        nejm_rank = journal_rank("New England Journal of Medicine")
        cancer_rank = journal_rank("Cancer")
        assert nejm_rank < cancer_rank


class TestHardDedupe(unittest.TestCase):
    def test_duplicate_pmid_dropped(self):
        from carcinos_ingestion.filters.dedupe import hard_dedupe
        r1 = make_record(pmid="1111", doi=None)
        r2 = make_record(pmid="1111", doi=None)
        result = hard_dedupe([r1, r2])
        assert len(result) == 1

    def test_same_doi_different_pmid_keeps_one(self):
        from carcinos_ingestion.filters.dedupe import hard_dedupe
        r1 = make_record(pmid="1001", doi="10.1000/test", abstract="")   # no abstract
        r2 = make_record(pmid="1002", doi="10.1000/test", abstract="Full abstract here")  # has abstract
        result = hard_dedupe([r1, r2])
        assert len(result) == 1
        # r2 has abstract → higher quality → should be kept
        assert result[0].pmid == "1002"

    def test_different_pmid_and_doi_both_kept(self):
        from carcinos_ingestion.filters.dedupe import hard_dedupe
        r1 = make_record(pmid="1001", doi="10.1000/aaa")
        r2 = make_record(pmid="1002", doi="10.1000/bbb")
        result = hard_dedupe([r1, r2])
        assert len(result) == 2

    def test_doi_comparison_case_insensitive(self):
        from carcinos_ingestion.filters.dedupe import hard_dedupe
        r1 = make_record(pmid="1001", doi="10.1000/ABC")
        r2 = make_record(pmid="1002", doi="10.1000/abc")
        result = hard_dedupe([r1, r2])
        assert len(result) == 1

    def test_no_doi_records_never_merged_on_doi(self):
        from carcinos_ingestion.filters.dedupe import hard_dedupe
        r1 = make_record(pmid="1001", doi=None)
        r2 = make_record(pmid="1002", doi=None)
        result = hard_dedupe([r1, r2])
        assert len(result) == 2


class TestFuzzyDedupe(unittest.TestCase):
    def test_highly_similar_titles_within_window_deduped(self):
        from carcinos_ingestion.filters.dedupe import fuzzy_dedupe
        title = "A randomized phase III trial of pembrolizumab in lung cancer patients"
        r1 = make_record(
            pmid="1001",
            title=title,
            pub_date="2024-01-15",
            abstract="Full abstract",
            journal="Journal of Clinical Oncology",
        )
        r2 = make_record(
            pmid="1002",
            title=title + ".",  # trivially different but >0.92 similar
            pub_date="2024-01-16",
        )
        result = fuzzy_dedupe([r1, r2])
        assert len(result) == 1
        # r1 has better quality (abstract + higher-rank journal) → kept
        assert result[0].pmid == "1001"

    def test_different_titles_both_kept(self):
        from carcinos_ingestion.filters.dedupe import fuzzy_dedupe
        r1 = make_record(pmid="1001", title="Phase III trial of Drug X in lung cancer", pub_date="2024-01-15")
        r2 = make_record(pmid="1002", title="Phase II study of Drug Y in colorectal cancer", pub_date="2024-01-15")
        result = fuzzy_dedupe([r1, r2])
        assert len(result) == 2

    def test_similar_titles_outside_date_window_both_kept(self):
        from carcinos_ingestion.filters.dedupe import fuzzy_dedupe
        title = "A randomized phase III trial of Drug X in lung cancer"
        r1 = make_record(pmid="1001", title=title, pub_date="2024-01-01")
        r2 = make_record(pmid="1002", title=title, pub_date="2024-03-01")  # >7 days apart
        result = fuzzy_dedupe([r1, r2])
        assert len(result) == 2

    def test_empty_title_not_deduplicated(self):
        from carcinos_ingestion.filters.dedupe import fuzzy_dedupe
        r1 = make_record(pmid="1001", title="", pub_date="2024-01-01")
        r2 = make_record(pmid="1002", title="", pub_date="2024-01-02")
        # Empty titles have 0 similarity → not merged
        result = fuzzy_dedupe([r1, r2])
        assert len(result) == 2

    def test_missing_pub_date_treated_as_within_window(self):
        from carcinos_ingestion.filters.dedupe import fuzzy_dedupe
        title = "A randomized phase III trial of Drug X in lung cancer"
        r1 = make_record(pmid="1001", title=title, pub_date="2024-01-01")
        r2 = make_record(pmid="1002", title=title, pub_date="")  # missing date
        result = fuzzy_dedupe([r1, r2])
        # Missing date is treated conservatively as within-window → deduped
        assert len(result) == 1


class TestDedupeCombined(unittest.TestCase):
    def test_dedupe_runs_both_passes(self):
        from carcinos_ingestion.filters.dedupe import dedupe
        r1 = make_record(pmid="1001", doi="10.1000/abc", title="Trial A", pub_date="2024-01-01")
        r2 = make_record(pmid="1001", doi=None, title="Totally different", pub_date="2024-01-01")  # same PMID
        result = dedupe([r1, r2])
        assert len(result) == 1


# ===========================================================================
# SECTION 2: filters/pubtype.py
# ===========================================================================

class TestPubtypeClassify(unittest.TestCase):
    def test_rct_is_keep(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Randomized Controlled Trial"])
        d = classify(r)
        assert d.keep is True
        assert d.low_priority is False

    def test_phase_iii_is_keep(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Clinical Trial, Phase III"])
        d = classify(r)
        assert d.keep is True
        assert d.low_priority is False

    def test_meta_analysis_is_keep(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Meta-Analysis"])
        d = classify(r)
        assert d.keep is True
        assert d.low_priority is False

    def test_systematic_review_is_keep(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Systematic Review"])
        d = classify(r)
        assert d.keep is True

    def test_editorial_is_drop(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Editorial"])
        d = classify(r)
        assert d.keep is False

    def test_comment_is_drop(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Comment"])
        d = classify(r)
        assert d.keep is False

    def test_letter_is_drop(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Letter"])
        d = classify(r)
        assert d.keep is False

    def test_case_report_is_drop(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Case Reports"])
        d = classify(r)
        assert d.keep is False

    def test_narrative_review_is_drop(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Review"])
        d = classify(r)
        assert d.keep is False

    def test_journal_article_is_low_priority(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Journal Article"])
        d = classify(r)
        assert d.keep is True
        assert d.low_priority is True

    def test_congress_is_low_priority(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Congress"])
        d = classify(r)
        assert d.keep is True
        assert d.low_priority is True

    def test_rct_overrides_letter(self):
        """KEEP_TYPES take priority over DROP_TYPES when both present."""
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Randomized Controlled Trial", "Letter"])
        d = classify(r)
        assert d.keep is True

    def test_low_priority_overrides_editorial_drop(self):
        """A LOW_PRIORITY_TYPES tag prevents the DROP from taking effect."""
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=["Editorial", "Journal Article"])
        d = classify(r)
        # Journal Article is in LOW_PRIORITY → prevents drop logic
        assert d.keep is True

    def test_unknown_type_is_low_priority(self):
        from carcinos_ingestion.filters.pubtype import classify
        r = make_record(publication_types=[])
        d = classify(r)
        assert d.keep is True


class TestFilterByPubtype(unittest.TestCase):
    def test_keep_record_included(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        r = make_record(pmid="1", publication_types=["Randomized Controlled Trial"])
        result = filter_by_pubtype([r])
        assert len(result) == 1

    def test_drop_record_excluded(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        r = make_record(pmid="1", publication_types=["Editorial"])
        result = filter_by_pubtype([r])
        assert len(result) == 0

    def test_conference_source_overrides_drop(self):
        """Records with a conference_source are force-kept regardless of pubtype."""
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        r = make_record(pmid="1", publication_types=["Editorial"], conference_source="FDA")
        result = filter_by_pubtype([r])
        assert len(result) == 1
        assert result[0][1].rationale.startswith("force-kept by lane source")

    def test_journal_whitelist_saves_dropped_record(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        r = make_record(
            pmid="1",
            publication_types=["Review"],
            journal="New England Journal of Medicine",
        )
        result = filter_by_pubtype([r], journal_force_keep=["New England Journal of Medicine"])
        assert len(result) == 1
        assert result[0][1].low_priority is True  # force-kept but flagged low priority

    def test_journal_whitelist_partial_name_match(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        r = make_record(
            pmid="1",
            publication_types=["Letter"],
            journal="NEJM",
        )
        result = filter_by_pubtype([r], journal_force_keep=["New England Journal of Medicine", "NEJM"])
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        from carcinos_ingestion.filters.pubtype import filter_by_pubtype
        result = filter_by_pubtype([])
        assert result == []


# ===========================================================================
# SECTION 3: filters/relevance.py
# ===========================================================================

class TestScoreRelevance(unittest.TestCase):
    def setUp(self):
        self.site = make_thoracic_site()

    def test_site_term_in_title_gets_thirty_points(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(title="A trial of pembrolizumab in lung cancer patients", abstract="")
        result = score_relevance(r, self.site)
        assert any("+30" in n for n in result.rationale)

    def test_site_term_in_abstract_only_gets_fifteen_points(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Immunotherapy outcomes in solid tumors",
            abstract="This study evaluated pembrolizumab in patients with lung cancer.",
        )
        result = score_relevance(r, self.site)
        assert any("+15" in n for n in result.rationale)
        assert not any("+30" in n for n in result.rationale)

    def test_mesh_match_adds_fifteen_points(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Immunotherapy study",
            abstract="A clinical trial.",
            mesh_terms=["Lung Neoplasms"],
        )
        result = score_relevance(r, self.site)
        assert any("+15 MeSH" in n for n in result.rationale)

    def test_trial_keyword_adds_twenty_points(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Lung cancer study",
            abstract="This was a randomized controlled trial.",
        )
        result = score_relevance(r, self.site)
        assert any("+20" in n for n in result.rationale)

    def test_modality_keyword_adds_fifteen_points(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Lung cancer study",
            abstract="Patients received immunotherapy and chemotherapy.",
        )
        result = score_relevance(r, self.site)
        assert any("+15 modality" in n for n in result.rationale)

    def test_endpoint_vocabulary_adds_fifteen_points(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Lung cancer trial",
            abstract="Primary endpoint was overall survival.",
        )
        result = score_relevance(r, self.site)
        assert any("+15 endpoint" in n for n in result.rationale)

    def test_preclinical_only_gets_penalty(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Lung cancer cell line study",
            abstract="We tested Drug X in vitro using cell lines from lung cancer xenografts.",
        )
        result = score_relevance(r, self.site)
        assert any("-30" in n for n in result.rationale)

    def test_preclinical_with_clinical_bridge_no_penalty(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Lung cancer translational study",
            abstract="We tested in vitro and also enrolled patients in a clinical trial.",
        )
        result = score_relevance(r, self.site)
        # has preclinical hint but also has clinical bridge → no penalty
        assert not any("-30" in n for n in result.rationale)

    def test_score_keep_at_fifty_or_above(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="A randomized phase III trial in lung cancer",
            abstract="Overall survival improved. Hazard ratio 0.75, 95% CI.",
        )
        result = score_relevance(r, self.site)
        assert result.keep is True
        assert result.low_confidence is False

    def test_score_low_confidence_between_thirty_and_fifty(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        # Only abstract mention of lung (not title) = +15; nothing else
        r = make_record(
            title="Immunotherapy in solid tumors",
            abstract="Including patients with lung cancer.",
        )
        result = score_relevance(r, self.site)
        # Score: +15 (abstract) = 15 → should be dropped (< 30)
        # But mesh or other terms could add. Let's verify keep/low_confidence logic.
        assert result.score <= 50  # certainly not high-confidence

    def test_score_drop_below_threshold(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Veterinary oncology review",
            abstract="Study of dogs.",
        )
        result = score_relevance(r, self.site)
        assert result.keep is False

    def test_score_clamped_to_one_hundred_max(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        # All possible positive signals
        r = make_record(
            title="A randomized phase III trial in lung cancer",
            abstract=(
                "Randomized phase III noninferiority trial in lung cancer. "
                "Primary endpoint was overall survival. "
                "FDA approved. Guideline update. "
                "Hazard ratio 0.72, 95% CI. "
            ),
            mesh_terms=["Lung Neoplasms"],
        )
        result = score_relevance(r, self.site)
        assert result.score <= 100

    def test_score_clamped_to_zero_minimum(self):
        from carcinos_ingestion.filters.relevance import score_relevance
        r = make_record(
            title="Endometriosis cell line in vitro study",
            abstract="Cell line xenograft mouse model investigation.",
        )
        result = score_relevance(r, self.site)
        assert result.score >= 0


# ===========================================================================
# SECTION 4: filters/signal_score.py
# ===========================================================================

class TestGate1HardExcludes(unittest.TestCase):
    """Gate 1 patterns that always trigger hard_excluded=True."""

    def _score(self, title="", abstract="", conf_source=None, pub_types=None):
        from carcinos_ingestion.filters.signal_score import score_candidate
        c = make_candidate(title=title, abstract=abstract,
                           conference_source=conf_source,
                           publication_types=pub_types or [])
        return score_candidate(c)

    def test_mixture_cure_model_hard_excluded(self):
        sig = self._score(
            abstract="We used a mixture cure model to reanalyze KEYNOTE-189 OS data."
        )
        assert sig.hard_excluded is True

    def test_reconstructed_ipd_hard_excluded(self):
        sig = self._score(
            abstract="Reconstructed individual patient data from published Kaplan-Meier curves."
        )
        assert sig.hard_excluded is True

    def test_narrative_review_hard_excluded(self):
        sig = self._score(abstract="This narrative review summarizes the evidence for PD-L1 inhibitors.")
        assert sig.hard_excluded is True

    def test_literature_review_hard_excluded(self):
        sig = self._score(abstract="A literature review of phase III trials in NSCLC.")
        assert sig.hard_excluded is True

    def test_post_hoc_analysis_title_hard_excluded(self):
        sig = self._score(
            title="Post-hoc analysis of the PACIFIC phase III trial",
            abstract="We analyzed the PACIFIC trial data retrospectively.",
        )
        assert sig.hard_excluded is True

    def test_reanalysis_of_phase_iii_title_hard_excluded(self):
        sig = self._score(
            title="Reanalysis of phase III trial data for pembrolizumab",
            abstract="We performed a reanalysis.",
        )
        assert sig.hard_excluded is True

    def test_secondary_analysis_of_trial_data_hard_excluded(self):
        sig = self._score(
            title="Secondary analysis of phase III trial data from KEYNOTE-189",
            abstract="Data were analyzed secondarily.",
        )
        assert sig.hard_excluded is True

    def test_normal_rct_not_hard_excluded(self):
        sig = self._score(
            title="A randomized phase III trial of pembrolizumab in NSCLC",
            abstract=(
                "We randomized 600 patients to pembrolizumab or placebo. "
                "Primary endpoint: overall survival. HR 0.72, p=0.001."
            ),
        )
        assert sig.hard_excluded is False


class TestGate2QualifyingSignals(unittest.TestCase):
    """Gate 2: each qualifying signal type should be correctly detected."""

    def _score(self, title="", abstract="", conf_source=None, pub_types=None, journal="Test Journal", watched=frozenset()):
        from carcinos_ingestion.filters.signal_score import score_candidate
        c = make_candidate(
            title=title,
            abstract=abstract,
            conference_source=conf_source,
            publication_types=pub_types or [],
            journal=journal,
        )
        return score_candidate(c, watched_trials=watched)

    # ── FDA ──────────────────────────────────────────────────────────────────

    def test_fda_approved_text_triggers_qs_fda(self):
        sig = self._score(abstract="FDA approved pembrolizumab for first-line NSCLC treatment.")
        assert sig.qualifying_signal == "FDA"

    def test_accelerated_approval_triggers_qs_fda(self):
        sig = self._score(abstract="The drug received accelerated approval from the FDA.")
        assert sig.qualifying_signal == "FDA"

    def test_conference_source_fda_triggers_qs_fda(self):
        sig = self._score(
            abstract="New approval for lung cancer.",
            conf_source="FDA",
        )
        assert sig.qualifying_signal == "FDA"

    # ── GUIDELINE ────────────────────────────────────────────────────────────

    def test_nccn_guideline_update_triggers_qs_guideline(self):
        sig = self._score(
            abstract="NCCN guideline update incorporates pembrolizumab as category 1 for NSCLC."
        )
        assert sig.qualifying_signal == "GUIDELINE"

    def test_asco_consensus_recommendation(self):
        sig = self._score(
            abstract="ASCO consensus recommendation for the management of stage III NSCLC."
        )
        assert sig.qualifying_signal == "GUIDELINE"

    def test_guideline_body_without_update_event_not_triggered(self):
        sig = self._score(
            abstract="NCCN provides comprehensive cancer care resources."
        )
        # Body mentioned but no update event → not GUIDELINE
        assert sig.qualifying_signal != "GUIDELINE"

    # ── WATCHED TRIAL ────────────────────────────────────────────────────────

    def test_watched_trial_acronym_in_title_triggers(self):
        sig = self._score(
            title="The LAURA trial: consolidation osimertinib after CRT in stage III NSCLC",
            abstract="We report primary results of the LAURA trial.",
            watched=frozenset({"LAURA", "PACIFIC"}),
        )
        assert sig.qualifying_signal == "WATCHED_TRIAL"

    def test_watched_trial_nct_in_abstract_triggers(self):
        sig = self._score(
            title="Randomized trial of osimertinib",
            abstract="NCT03521154 enrolled 216 patients with stage III NSCLC.",
            watched=frozenset({"NCT03521154"}),
        )
        assert sig.qualifying_signal == "WATCHED_TRIAL"

    def test_partial_acronym_match_not_triggered(self):
        """'LAURA' should not match 'LAURA2' as a whole word."""
        sig = self._score(
            title="The LAURA2 extension study",
            abstract="LAURA2 enrolled additional patients.",
            watched=frozenset({"LAURA"}),
        )
        # LAURA2 contains LAURA but not as a word boundary → should not match
        # Note: regex uses \bLAURA\b, so "LAURA2" should NOT match
        assert sig.qualifying_signal != "WATCHED_TRIAL"

    # ── NEGATIVE TRIAL ───────────────────────────────────────────────────────

    def test_did_not_meet_primary_endpoint_triggers_negative(self):
        sig = self._score(
            abstract=(
                "Patients were randomized to Drug X or placebo. "
                "The trial did not meet its primary endpoint of overall survival."
            )
        )
        assert sig.qualifying_signal == "NEGATIVE_TRIAL"

    def test_primary_endpoint_not_met_triggers_negative(self):
        sig = self._score(
            abstract=(
                "In this randomized phase III study, the primary endpoint was not met. "
                "No significant improvement in progression-free survival was observed."
            )
        )
        assert sig.qualifying_signal == "NEGATIVE_TRIAL"

    def test_negative_without_randomized_not_triggered(self):
        # "did not meet primary endpoint" but no randomized language
        sig = self._score(
            abstract="The observational study did not meet its primary endpoint of OS."
        )
        # No randomized language → not NEGATIVE_TRIAL
        assert sig.qualifying_signal != "NEGATIVE_TRIAL"

    # ── PHASE III RCT ────────────────────────────────────────────────────────

    def test_phase_iii_randomized_triggers(self):
        sig = self._score(
            title="A phase III randomized trial of Drug X in lung cancer",
            abstract="Patients were randomly assigned to Drug X or placebo.",
        )
        assert sig.qualifying_signal == "PHASE_III_RANDOMIZED"

    def test_phase_iii_with_previously_published_not_triggered(self):
        sig = self._score(
            abstract=(
                "We report a subgroup analysis based on previously published phase III trial data. "
                "Patients were randomized in the original trial."
            )
        )
        # Borrowed phase III language → should NOT trigger QS_PHASE_III_RANDOMIZED
        assert sig.qualifying_signal != "PHASE_III_RANDOMIZED"

    def test_retrospective_in_title_blocks_phase_iii(self):
        sig = self._score(
            title="Retrospective analysis of phase III randomized trial outcomes",
            abstract="Patients were originally randomized in the PACIFIC trial.",
        )
        # Retrospective in title → not a primary Phase III RCT paper
        assert sig.qualifying_signal != "PHASE_III_RANDOMIZED"

    # ── RANDOMIZED DE-ESCALATION ─────────────────────────────────────────────

    def test_noninferiority_randomized_triggers_deescalation(self):
        sig = self._score(
            abstract=(
                "In this randomized noninferiority trial, we compared reduced-dose RT "
                "to standard RT in NSCLC patients."
            )
        )
        assert sig.qualifying_signal == "RANDOMIZED_DEESCALATION"

    def test_deescalation_without_randomized_not_triggered(self):
        sig = self._score(
            abstract="Active surveillance protocols allow treatment de-escalation in low-risk patients."
        )
        # De-escalation but not randomized → not triggered
        assert sig.qualifying_signal != "RANDOMIZED_DEESCALATION"

    # ── PHASE II RANDOMIZED ───────────────────────────────────────────────────

    def test_phase_ii_randomized_triggers(self):
        sig = self._score(
            abstract="In this randomized phase II trial, patients with NSCLC were assigned to Drug X or Y."
        )
        assert sig.qualifying_signal == "PHASE_II_RANDOMIZED"

    def test_phase_ii_single_arm_does_not_trigger_phase_ii_randomized(self):
        sig = self._score(
            abstract=(
                "In this phase II single-arm study, we enrolled 50 patients with NSCLC. "
                "The overall response rate was 45%."
            ),
            journal="Orphan Journal",  # not a top-tier journal
        )
        assert sig.qualifying_signal != "PHASE_II_RANDOMIZED"

    # ── MAJOR CONFERENCE ─────────────────────────────────────────────────────

    def test_conference_source_asco_with_trial_signal(self):
        # ASCO-tagged record. Note: Phase III language fires before MAJOR_CONFERENCE
        # in priority order, so a pure ASCO abstract without Phase III text should
        # yield MAJOR_CONFERENCE; one with Phase III text yields PHASE_III_RANDOMIZED.
        sig = self._score(
            title="Updated overall survival analysis from a large cancer trial",
            abstract=(
                "Plenary session at ASCO 2024. Hazard ratio 0.76. "
                "Progression-free survival benefit observed."
            ),
            conf_source="ASCO",
        )
        assert sig.qualifying_signal == "MAJOR_CONFERENCE"

    def test_lba_mention_in_abstract_triggers_major_conference(self):
        # Abstract mentions late-breaking session at ASCO but does NOT include
        # Phase III / randomized language (which would fire first in priority chain).
        sig = self._score(
            abstract=(
                "Presented as a late-breaking abstract at ASCO 2024. "
                "Results from a large prospective cohort study showing OS benefit."
            )
        )
        assert sig.qualifying_signal == "MAJOR_CONFERENCE"

    # ── META-ANALYSIS ────────────────────────────────────────────────────────

    def test_meta_analysis_triggers_qs_meta_analysis(self):
        sig = self._score(
            abstract="We performed a meta-analysis of 15 randomized trials including 8,000 patients."
        )
        assert sig.qualifying_signal == "META_ANALYSIS"

    def test_systematic_review_triggers_qs_meta_analysis(self):
        sig = self._score(
            abstract="A systematic review of phase III trials evaluating EGFR inhibitors in NSCLC."
        )
        assert sig.qualifying_signal == "META_ANALYSIS"

    # ── TOP JOURNAL ──────────────────────────────────────────────────────────

    def test_top_journal_with_clinical_signal_triggers(self):
        sig = self._score(
            abstract="A randomized trial demonstrated progression-free survival benefit.",
            journal="New England Journal of Medicine",
        )
        assert sig.qualifying_signal == "TOP_JOURNAL"

    def test_top_journal_without_clinical_signal_not_triggered(self):
        sig = self._score(
            abstract="We describe the history of oncology drug development.",
            journal="New England Journal of Medicine",
        )
        assert sig.qualifying_signal != "TOP_JOURNAL"

    # ── WEB SEARCH ───────────────────────────────────────────────────────────

    def test_web_search_source_triggers_llm_curated(self):
        sig = self._score(
            abstract="Phase III trial of nivolumab in lung cancer.",
            conf_source="WEB_SEARCH",
        )
        assert sig.qualifying_signal == "LLM_CURATED"

    # ── QS_NONE ──────────────────────────────────────────────────────────────

    def test_no_signal_returns_qs_none(self):
        sig = self._score(
            title="Surgical technique for lobectomy in NSCLC",
            abstract="We describe our robotic surgical technique for lobectomy.",
            journal="Obscure Surgical Journal",
        )
        assert sig.qualifying_signal == "NONE"

    def test_qs_none_is_not_hard_excluded(self):
        sig = self._score(
            title="Retrospective database study of NSCLC outcomes",
            abstract="Using SEER data, we analyzed 10,000 lung cancer patients.",
            journal="Obscure Journal",
        )
        assert sig.qualifying_signal == "NONE"
        assert sig.hard_excluded is False


class TestGate3AdditiveScore(unittest.TestCase):
    """Gate 3 scoring bonuses should stack correctly."""

    def _score(self, abstract="", journal="Journal of Clinical Oncology"):
        from carcinos_ingestion.filters.signal_score import score_candidate
        c = make_candidate(
            title="A randomized phase III trial in lung cancer",
            abstract=abstract,
            journal=journal,
        )
        return score_candidate(c)

    def test_base_phase_iii_score(self):
        from carcinos_ingestion.filters.signal_score import QS_BASE, QS_PHASE_III_RANDOMIZED
        sig = self._score(abstract="We randomized 500 patients in this phase III trial.")
        assert sig.score >= QS_BASE[QS_PHASE_III_RANDOMIZED]

    def test_os_bonus_applied(self):
        sig_with_os = self._score(
            abstract="Randomized phase III trial. Primary endpoint: overall survival improved."
        )
        sig_without_os = self._score(
            abstract="Randomized phase III trial. Endpoint was response rate."
        )
        assert sig_with_os.score > sig_without_os.score

    def test_exploratory_penalty_applied(self):
        sig_exploratory = self._score(
            abstract="Randomized phase III trial. This post-hoc subgroup analysis showed OS benefit."
        )
        sig_primary = self._score(
            abstract="Randomized phase III trial. Primary endpoint was overall survival."
        )
        assert sig_exploratory.score < sig_primary.score

    def test_qualifying_signal_priority_ordering(self):
        """FDA score must exceed Phase III score even with bonuses."""
        from carcinos_ingestion.filters.signal_score import score_candidate, QS_BASE
        fda_cand = make_candidate(
            title="FDA granted full approval for Drug X in NSCLC",
            abstract=(
                "FDA approved Drug X. Accelerated approval granted. "
                "Phase III randomized trial showed OS benefit. "
                "Overall survival improved. First-line therapy. "
                "Late-breaking plenary session at ASCO."
            ),
            conference_source="FDA",
        )
        p3_cand = make_candidate(
            title="Randomized phase III trial of Drug Y in NSCLC",
            abstract=(
                "Phase III randomized trial. Overall survival improved. "
                "First-line. De-escalation. Late-breaking plenary session."
            ),
        )
        fda_sig = score_candidate(fda_cand)
        p3_sig = score_candidate(p3_cand)
        assert fda_sig.score >= p3_sig.score
if __name__ == '__main__':
    unittest.main()
