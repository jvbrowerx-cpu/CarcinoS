"""
Tests for carcinos_ingestion/retrieval/astro.py

All tests are offline — no real HTTP calls are made.
The portal HTML is reproduced from the observed page structure (no
copyrighted abstract text used verbatim).
"""

from __future__ import annotations

import hashlib
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal fake HTML fixtures
# ---------------------------------------------------------------------------

# A real scientific abstract has all four required sections
ABSTRACT_HTML = """\
<html><body><main>
  <div class="session__presentations-wrapper">
    <h1>LBA 03 - MAVERICK: A Phase III Trial of Brain MRI Without PCI for SCLC</h1>
  </div>
  <div class="session__presentations-date">Sep<span class="session__presentations-date-big">27</span></div>
  <p>A. Smith<sup>1</sup>, <u>B. Jones</u><sup>2</sup>, C. Doe<sup>3</sup></p>
  <p><b>Purpose/Objective(s):</b> To evaluate brain MRI surveillance without PCI.</p>
  <p><b>Materials/Methods:</b> Phase III trial, 304 patients randomized. NCT01234567 was the registry.</p>
  <p><b>Results:</b> CFFS improved with MRI alone (HR 0.60, p=0.001).</p>
  <p><b>Conclusion:</b> MRI surveillance alone is preferred over PCI for SCLC.</p>
</main></body></html>
"""

# A discussant page — no abstract sections
DISCUSSANT_HTML = """\
<html><body><main>
  <div class="session__presentations-wrapper">
    <h1>Discussant</h1>
  </div>
  <div class="session__presentations-date">Sep<span>27</span></div>
  <p>Discussant speaker bio goes here.</p>
</main></body></html>
"""

# An education session with only partial sections
PARTIAL_HTML = """\
<html><body><main>
  <div class="session__presentations-wrapper">
    <h1>Introduction to Stereotactic Radiosurgery Techniques</h1>
  </div>
  <p>Educational overview — this session has no structured abstract.</p>
  <p><b>Purpose/Objective(s):</b> Educational session overview.</p>
</main></body></html>
"""

ABSTRACT_URL   = "https://amportal.astro.org/sessions/ct-01-22948/maverick-114268"
DISCUSSANT_URL = "https://amportal.astro.org/sessions/ct-01-22948/discussant-113797"


# ---------------------------------------------------------------------------
# Unit tests: _parse_abstract_page
# ---------------------------------------------------------------------------

class TestParseAbstractPage:

    def _parse(self, html, url=ABSTRACT_URL):
        from carcinos_ingestion.retrieval.astro import _parse_abstract_page
        return _parse_abstract_page(html, url)

    def test_scientific_abstract_returns_record(self):
        assert self._parse(ABSTRACT_HTML) is not None

    def test_discussant_returns_none(self):
        assert self._parse(DISCUSSANT_HTML, url=DISCUSSANT_URL) is None, \
            "Discussant pages must be filtered out"

    def test_partial_sections_returns_none(self):
        assert self._parse(PARTIAL_HTML) is None, \
            "Pages missing some required sections must be filtered out"

    def test_title_strips_abstract_number(self):
        rec = self._parse(ABSTRACT_HTML)
        assert rec.title == "MAVERICK: A Phase III Trial of Brain MRI Without PCI for SCLC"
        assert not rec.title.startswith("LBA")

    def test_abstract_number_regex_matches_lba(self):
        from carcinos_ingestion.retrieval.astro import _ABSTRACT_NUM_RE
        m = _ABSTRACT_NUM_RE.match("LBA 03 - Some Title Here")
        assert m is not None
        assert m.group(1).strip() == "LBA 03"

    def test_abstract_number_regex_matches_plain(self):
        from carcinos_ingestion.retrieval.astro import _ABSTRACT_NUM_RE
        m = _ABSTRACT_NUM_RE.match("179 - SBRT Dose Escalation")
        assert m is not None
        assert m.group(1).strip() == "179"

    def test_synthetic_pmid_contains_year_and_portal_id(self):
        rec = self._parse(ABSTRACT_HTML)
        assert "ASTRO2026" in rec.pmid
        assert "114268" in rec.pmid  # extracted from URL slug

    def test_conference_source_is_astro(self):
        rec = self._parse(ABSTRACT_HTML)
        assert rec.conference_source == "ASTRO"

    def test_url_override_set(self):
        rec = self._parse(ABSTRACT_HTML)
        assert rec.url_override == ABSTRACT_URL

    def test_url_property_uses_override(self):
        rec = self._parse(ABSTRACT_HTML)
        assert rec.url == ABSTRACT_URL

    def test_journal_is_red_journal(self):
        rec = self._parse(ABSTRACT_HTML)
        assert "Radiation Oncology" in rec.journal

    def test_pub_date_extracted_as_iso(self):
        rec = self._parse(ABSTRACT_HTML)
        assert rec.pub_date == "2026-09-27"

    def test_nct_id_extracted(self):
        rec = self._parse(ABSTRACT_HTML)
        assert "NCT01234567" in rec.nct_ids

    def test_abstract_contains_section_labels(self):
        rec = self._parse(ABSTRACT_HTML)
        assert "Purpose/Objective(s):" in rec.abstract
        assert "Materials/Methods:" in rec.abstract
        assert "Results:" in rec.abstract
        assert "Conclusion:" in rec.abstract

    def test_abstract_contains_content(self):
        rec = self._parse(ABSTRACT_HTML)
        assert "HR 0.60" in rec.abstract
        assert "304 patients" in rec.abstract

    def test_authors_extracted(self):
        rec = self._parse(ABSTRACT_HTML)
        assert len(rec.authors) >= 1

    def test_text_hash_is_sha256_of_html(self):
        rec = self._parse(ABSTRACT_HTML)
        expected = hashlib.sha256(ABSTRACT_HTML.encode("utf-8")).hexdigest()
        assert rec.text_hash == expected


# ---------------------------------------------------------------------------
# Unit tests: _portal_id_from_url
# ---------------------------------------------------------------------------

class TestPortalIdFromUrl:

    def _id(self, url):
        from carcinos_ingestion.retrieval.astro import _portal_id_from_url
        return _portal_id_from_url(url)

    def test_numeric_id_extracted_from_slug(self):
        assert self._id(ABSTRACT_URL) == "114268"

    def test_longer_slug_with_multiple_hyphens(self):
        url = "https://amportal.astro.org/sessions/ct-01-22948/swog-s1827-maverick-114268"
        assert self._id(url) == "114268"

    def test_discussant_id(self):
        assert self._id(DISCUSSANT_URL) == "113797"

    def test_url_with_no_numeric_suffix_returns_empty(self):
        assert self._id("https://amportal.astro.org/sessions/ct-01-22948/discussant") == ""


# ---------------------------------------------------------------------------
# Unit tests: meeting window gate
# ---------------------------------------------------------------------------

class TestMeetingWindowGate:
    """retrieve_astro_records() returns [] immediately outside the meeting window."""

    def _retrieve(self, ref_date):
        from carcinos_ingestion.retrieval.astro import retrieve_astro_records
        fake_site = MagicMock()
        fake_site.code = "thoracic"
        return retrieve_astro_records(fake_site, reference_date=ref_date)

    def test_outside_window_august_returns_empty(self):
        assert self._retrieve(date(2026, 8, 1)) == []

    def test_outside_window_december_returns_empty(self):
        assert self._retrieve(date(2026, 12, 1)) == []

    def test_wrong_year_2025_returns_empty(self):
        assert self._retrieve(date(2025, 9, 28)) == []

    def test_wrong_year_2027_returns_empty(self):
        assert self._retrieve(date(2027, 9, 28)) == []

    def test_inside_window_makes_network_attempt(self):
        """
        Sep 28, 2026 is inside the window.  Patch _collect_session_urls to
        avoid real network traffic; confirm the function proceeds (returns list,
        not None / exception).
        """
        from carcinos_ingestion.retrieval import astro as astro_mod
        fake_site = MagicMock()
        fake_site.code = "thoracic"
        with patch.object(astro_mod, "_collect_session_urls", return_value=[]):
            result = astro_mod.retrieve_astro_records(
                fake_site, reference_date=date(2026, 9, 28)
            )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Unit tests: site filtering
# ---------------------------------------------------------------------------

class TestSiteFiltering:
    """_abstract_matches_site() uses SITE_QUICK_TERMS from disease_sites.base."""

    def _make_record(self, title, abstract="No relevant content."):
        from carcinos_ingestion.retrieval.astro import _parse_abstract_page
        html = (
            f"<html><body><main>"
            f"<div class='session__presentations-wrapper'><h1>179 - {title}</h1></div>"
            f"<div class='session__presentations-date'>Sep"
            f"<span class='session__presentations-date-big'>28</span></div>"
            f"<p>A. Smith, B. Jones</p>"
            f"<p><b>Purpose/Objective(s):</b> {abstract}</p>"
            f"<p><b>Materials/Methods:</b> Methods here.</p>"
            f"<p><b>Results:</b> Results here.</p>"
            f"<p><b>Conclusion:</b> Conclusions here.</p>"
            f"</main></body></html>"
        )
        return _parse_abstract_page(html, "https://amportal.astro.org/sessions/ct-01/title-179")

    def test_lung_abstract_matches_thoracic_site(self):
        from carcinos_ingestion.retrieval.astro import _abstract_matches_site
        rec = self._make_record("SBRT for Early-Stage Non-Small Cell Lung Cancer")
        fake_site = MagicMock()
        fake_site.code = "thoracic"
        # Patch where the function imports from
        with patch(
            "carcinos_ingestion.disease_sites.base.SITE_QUICK_TERMS",
            {"thoracic": ["lung", "nsclc", "sclc"]},
        ):
            assert _abstract_matches_site(rec, fake_site)

    def test_prostate_abstract_does_not_match_breast_site(self):
        from carcinos_ingestion.retrieval.astro import _abstract_matches_site
        rec = self._make_record("Hypofractionation for Prostate Cancer")
        fake_site = MagicMock()
        fake_site.code = "breast"
        with patch(
            "carcinos_ingestion.disease_sites.base.SITE_QUICK_TERMS",
            {"breast": ["breast", "dcis"]},
        ):
            assert not _abstract_matches_site(rec, fake_site)

    def test_site_with_no_quick_terms_receives_all_abstracts(self):
        from carcinos_ingestion.retrieval.astro import _abstract_matches_site
        rec = self._make_record("Unrelated Title")
        fake_site = MagicMock()
        fake_site.code = "general"
        with patch(
            "carcinos_ingestion.disease_sites.base.SITE_QUICK_TERMS",
            {},
        ):
            assert _abstract_matches_site(rec, fake_site)
