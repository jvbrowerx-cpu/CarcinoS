"""
Regression tests for the PubMed Entrez-date fix.

Problem being tested
---------------------
Our esearch query uses [Date - Entrez] (when NCBI indexed the record).
But the old _pub_date_ok() checked ArticleDate (when the publisher put
the paper online). For journals like JCO that have a publishing-to-indexing
lag of 3–6 weeks this caused *all* newly discoverable papers to be silently
discarded: esearch found them (recent Entrez date) but the date filter
killed them (old ArticleDate).

Fix
---
1. pubmed.py: _extract_entrez_date() reads PubmedData/History/PubMedPubDate
   [@PubStatus="entrez"] from the efetch XML and stores it on PubMedRecord.entrez_date.
2. pipeline.py: _date_is_fresh() passes a record when EITHER entrez_date OR
   pub_date falls within the ingestion window. Non-PubMed records have no
   entrez_date and fall back to the original pub_date behaviour.
"""

from __future__ import annotations
import textwrap
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import pytest

from carcinos_ingestion.retrieval.pubmed import (
    _extract_entrez_date,
    parse_pubmed_xml,
)
from carcinos_ingestion.pipeline import _date_is_fresh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pubmed_xml(
    pmid: str = "12345678",
    article_date_days_ago: int | None = 40,   # None → omit ArticleDate
    entrez_date_days_ago: int | None = 3,     # None → omit PubmedData/History
) -> str:
    """Build a minimal PubmedArticleSet XML string for one article."""
    today = date.today()

    def iso_parts(d: date) -> tuple[str, str, str]:
        return str(d.year), f"{d.month:02d}", f"{d.day:02d}"

    art_date_block = ""
    if article_date_days_ago is not None:
        y, m, d = iso_parts(today - timedelta(days=article_date_days_ago))
        art_date_block = f"""
        <ArticleDate DateType="Electronic">
          <Year>{y}</Year><Month>{m}</Month><Day>{d}</Day>
        </ArticleDate>"""

    history_block = ""
    if entrez_date_days_ago is not None:
        y, m, d = iso_parts(today - timedelta(days=entrez_date_days_ago))
        history_block = f"""
      <PubmedData>
        <History>
          <PubMedPubDate PubStatus="pubmed">
            <Year>2026</Year><Month>01</Month><Day>01</Day>
          </PubMedPubDate>
          <PubMedPubDate PubStatus="entrez">
            <Year>{y}</Year><Month>{m}</Month><Day>{d}</Day>
          </PubMedPubDate>
        </History>
      </PubmedData>"""

    return textwrap.dedent(f"""
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>{pmid}</PMID>
          <Article>
            <ArticleTitle>Test article {pmid}</ArticleTitle>
            <Abstract><AbstractText>Some abstract text.</AbstractText></Abstract>
            <Journal>
              <Title>Journal of Clinical Oncology</Title>
              <JournalIssue>
                <PubDate><Year>2026</Year><Month>01</Month></PubDate>
              </JournalIssue>
            </Journal>
            <AuthorList>
              <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
            </AuthorList>{art_date_block}
          </Article>
        </MedlineCitation>{history_block}
      </PubmedArticle>
    </PubmedArticleSet>
    """).strip()


# ---------------------------------------------------------------------------
# Tests for _extract_entrez_date()
# ---------------------------------------------------------------------------

class TestExtractEntrezDate:
    """Unit tests for pubmed._extract_entrez_date()."""

    def test_returns_entrez_date_when_present(self):
        """Standard case: History block contains PubStatus='entrez'."""
        xml = _make_pubmed_xml(entrez_date_days_ago=3)
        root = ET.fromstring(xml)
        art = root.find(".//PubmedArticle")
        result = _extract_entrez_date(art)
        expected = (date.today() - timedelta(days=3)).isoformat()
        assert result == expected

    def test_returns_empty_when_no_history(self):
        """RSS / non-PubMed records have no PubmedData/History."""
        xml = _make_pubmed_xml(entrez_date_days_ago=None)
        root = ET.fromstring(xml)
        art = root.find(".//PubmedArticle")
        assert _extract_entrez_date(art) == ""

    def test_returns_empty_when_entrez_status_missing(self):
        """History exists but only has 'pubmed' status, not 'entrez'."""
        xml = textwrap.dedent("""
        <PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation><PMID>999</PMID>
              <Article><ArticleTitle>T</ArticleTitle><Journal><Title>J</Title>
              <JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
              </Article>
            </MedlineCitation>
            <PubmedData>
              <History>
                <PubMedPubDate PubStatus="pubmed">
                  <Year>2026</Year><Month>01</Month><Day>01</Day>
                </PubMedPubDate>
              </History>
            </PubmedData>
          </PubmedArticle>
        </PubmedArticleSet>
        """).strip()
        root = ET.fromstring(xml)
        art = root.find(".//PubmedArticle")
        assert _extract_entrez_date(art) == ""

    def test_entrez_date_populated_on_record(self):
        """parse_pubmed_xml() correctly stores entrez_date on the record."""
        xml = _make_pubmed_xml(article_date_days_ago=40, entrez_date_days_ago=2)
        records = parse_pubmed_xml(xml)
        assert len(records) == 1
        r = records[0]
        expected_entrez = (date.today() - timedelta(days=2)).isoformat()
        expected_pub    = (date.today() - timedelta(days=40)).isoformat()
        assert r.entrez_date == expected_entrez
        assert r.pub_date    == expected_pub

    def test_entrez_date_empty_without_history(self):
        """Records with no History block get entrez_date=''."""
        xml = _make_pubmed_xml(entrez_date_days_ago=None)
        records = parse_pubmed_xml(xml)
        assert records[0].entrez_date == ""


# ---------------------------------------------------------------------------
# Tests for _date_is_fresh()
# ---------------------------------------------------------------------------

class TestDateIsFresh:
    """
    Unit tests for pipeline._date_is_fresh().

    Window: ingestion window of the last 14 days.
    """

    @pytest.fixture
    def window(self):
        end    = date.today()
        cutoff = end - timedelta(days=14)
        return cutoff, end

    # ── The four expected-behaviour cases from the spec ────────────────────

    def test_delayed_indexing_passes(self, window):
        """
        Delayed indexing (ArticleDate 5 weeks ago, Entrez 3 days ago) → PASS.

        This is the JCO bug: paper published 35 days ago but indexed 3 days ago.
        The old code would FAIL because pub_date is outside the 14-day window.
        The fix makes it PASS because entrez_date IS within the window.
        """
        cutoff, end = window
        pub_date    = (date.today() - timedelta(days=35)).isoformat()
        entrez_date = (date.today() - timedelta(days=3)).isoformat()
        assert _date_is_fresh(pub_date, entrez_date, cutoff, end) is True

    def test_normal_new_paper_passes(self, window):
        """Normal new paper (both pub_date and entrez_date within window) → PASS."""
        cutoff, end = window
        pub_date    = (date.today() - timedelta(days=5)).isoformat()
        entrez_date = (date.today() - timedelta(days=3)).isoformat()
        assert _date_is_fresh(pub_date, entrez_date, cutoff, end) is True

    def test_genuinely_old_paper_fails(self, window):
        """Genuinely old paper (both dates in 2023) → FAIL."""
        cutoff, end = window
        assert _date_is_fresh("2023-03-15", "2023-03-17", cutoff, end) is False

    def test_non_pubmed_record_uses_pub_date_only(self, window):
        """
        RSS/non-PubMed record (entrez_date='') → use pub_date unchanged.

        Recent pub_date → PASS; old pub_date → FAIL.
        """
        cutoff, end = window
        recent_pub = (date.today() - timedelta(days=2)).isoformat()
        old_pub    = "2023-09-01"
        assert _date_is_fresh(recent_pub, "", cutoff, end) is True
        assert _date_is_fresh(old_pub,    "", cutoff, end) is False

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_empty_pub_date_and_empty_entrez_passes(self, window):
        """Both dates missing → cannot determine age → pass (original behaviour)."""
        cutoff, end = window
        assert _date_is_fresh("", "", cutoff, end) is True

    def test_future_dated_paper_fails(self, window):
        """A paper with both dates in the future → FAIL (upper bound check)."""
        cutoff, end = window
        future = (date.today() + timedelta(days=10)).isoformat()
        assert _date_is_fresh(future, future, cutoff, end) is False

    def test_entrez_in_window_pub_future_passes(self, window):
        """
        Entrez date in window but pub_date slightly in the future (clock skew).
        Should PASS because entrez_date is valid.
        """
        cutoff, end = window
        entrez_date = (date.today() - timedelta(days=1)).isoformat()
        future_pub  = (date.today() + timedelta(days=2)).isoformat()
        assert _date_is_fresh(future_pub, entrez_date, cutoff, end) is True

    def test_pub_date_on_cutoff_boundary_passes(self, window):
        """pub_date exactly on the cutoff date (inclusive lower bound) → PASS."""
        cutoff, end = window
        # entrez_date empty → RSS-like record
        assert _date_is_fresh(cutoff.isoformat(), "", cutoff, end) is True

    def test_pub_date_one_day_before_cutoff_fails(self, window):
        """pub_date one day before cutoff (stale) → FAIL for non-PubMed record."""
        cutoff, end = window
        one_day_before = (cutoff - timedelta(days=1)).isoformat()
        assert _date_is_fresh(one_day_before, "", cutoff, end) is False

    def test_malformed_date_string_passes(self, window):
        """Malformed date string is treated as missing → pass (original behaviour)."""
        cutoff, end = window
        assert _date_is_fresh("not-a-date", "", cutoff, end) is True
