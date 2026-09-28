"""
Regression tests for the deliver.py publication-date fix.

Background
----------
Before this fix, `deliver.py` contained a `_recent_enough()` function that
dropped any alert whose `pub_date` was more than 10 days old.  That filter
incorrectly discarded delayed-indexed PubMed papers: a JCO article published
35 days ago but first indexed by PubMed 3 days ago passes the pipeline's
`_date_is_fresh()` entrez-date gate and is correctly approved into Supabase —
yet `_recent_enough()` would then silently drop it at delivery time based on
the stale journal pub_date.

Fix
---
`_recent_enough()` has been removed entirely.  Delivery eligibility for the
current digest window is anchored to `alerts.published_at` (the CarcinoS
approval/creation timestamp) via the Supabase RPC:

    get_user_feed_for_digest(p_user_id, p_since = Monday of this week)

which filters `f.published_at >= p_since`.  `pub_date` is now display-only
metadata and does not affect delivery.

Tests in this file
------------------
1. `_date_is_fresh_survives_stale_pub_date` — the pipeline gate passes a
   record with pub_date 35 days ago when entrez_date is 3 days ago.
2. `monday_of_week_anchor` — confirms `_monday_of_week()` returns the right
   Monday for several known dates, covering the p_since boundary used by the
   Supabase RPC.
3. `rpc_published_at_anchor_conceptual` — documents (cannot unit-test without
   a live DB) that `get_user_feed_for_digest` filters on `published_at`, not
   `publication_date`; verified from migrations/13_audience_routing.sql.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import pytest


# ---------------------------------------------------------------------------
# 1.  Pipeline gate: delayed-indexed paper still passes _date_is_fresh()
# ---------------------------------------------------------------------------

class TestPipelineGateSurvivesStalePublicationDate:
    """
    Confirm that a record with a stale pub_date but a fresh entrez_date is
    NOT dropped by _date_is_fresh().  This is the core entrez-date fix.
    """

    def test_stale_pub_date_fresh_entrez_date_passes(self):
        """
        pub_date 35 days ago (older than any publication-date window),
        entrez_date 3 days ago (within the 14-day ingestion window).
        _date_is_fresh() must return True — the OR logic lets the fresh
        entrez_date carry the record through.
        """
        from carcinos_ingestion.pipeline import _date_is_fresh

        today   = date.today()
        cutoff  = today - timedelta(days=14)
        end     = today

        pub_date    = (today - timedelta(days=35)).isoformat()
        entrez_date = (today - timedelta(days=3)).isoformat()

        assert _date_is_fresh(pub_date, entrez_date, cutoff, end) is True, (
            "A delayed-indexed PubMed paper (pub_date=35d ago, entrez_date=3d ago) "
            "must survive _date_is_fresh() so it can reach the digest."
        )

    def test_stale_pub_date_stale_entrez_date_fails(self):
        """
        Genuinely old paper: both dates are 35+ days ago.
        Must still be rejected.
        """
        from carcinos_ingestion.pipeline import _date_is_fresh

        today   = date.today()
        cutoff  = today - timedelta(days=14)
        end     = today

        pub_date    = (today - timedelta(days=35)).isoformat()
        entrez_date = (today - timedelta(days=35)).isoformat()

        assert _date_is_fresh(pub_date, entrez_date, cutoff, end) is False, (
            "A genuinely old paper (both dates 35d ago) must be rejected."
        )

    def test_non_pubmed_stale_pub_date_fails(self):
        """
        RSS/non-PubMed record (entrez_date='') with a stale pub_date: must fail.
        Removing _recent_enough() does NOT change RSS behaviour — those records
        never had an entrez_date to rescue them, so the pipeline pub_date gate
        still rejects them.
        """
        from carcinos_ingestion.pipeline import _date_is_fresh

        today   = date.today()
        cutoff  = today - timedelta(days=14)
        end     = today

        pub_date    = (today - timedelta(days=35)).isoformat()

        assert _date_is_fresh(pub_date, "", cutoff, end) is False, (
            "A stale RSS/non-PubMed record (no entrez_date, old pub_date) "
            "must still be rejected at the pipeline gate."
        )


# ---------------------------------------------------------------------------
# 2.  Delivery anchor: _monday_of_week()
# ---------------------------------------------------------------------------

class TestMondayOfWeekAnchor:
    """
    Confirm that _monday_of_week() returns the ISO Monday for a given date.

    The weekly digest uses `p_since = _monday_of_week(as_of)` as the
    Supabase RPC boundary, so this function's correctness is the first
    requirement for the published_at anchor.
    """

    def _monday(self, as_of: date) -> date:
        from carcinos_ingestion.digest import _monday_of_week
        return _monday_of_week(as_of)

    def test_monday_is_returned_unchanged(self):
        """Monday → same day."""
        d = date(2026, 9, 14)   # a known Monday
        assert d.weekday() == 0, "fixture sanity: 2026-09-14 must be Monday"
        assert self._monday(d) == d

    def test_tuesday_gives_preceding_monday(self):
        d = date(2026, 9, 15)   # Tuesday
        assert self._monday(d) == date(2026, 9, 14)

    def test_sunday_gives_preceding_monday(self):
        d = date(2026, 9, 20)   # Sunday
        assert self._monday(d) == date(2026, 9, 14)

    def test_friday_gives_preceding_monday(self):
        d = date(2026, 9, 25)   # Friday (delivery day)
        assert self._monday(d) == date(2026, 9, 21)

    def test_first_day_of_month_can_be_monday(self):
        d = date(2026, 6, 1)    # Monday
        assert d.weekday() == 0
        assert self._monday(d) == d


# ---------------------------------------------------------------------------
# 3.  Conceptual: Supabase RPC anchors on published_at, not publication_date
# ---------------------------------------------------------------------------

class TestRPCPublishedAtAnchor:
    """
    Documents (without a live DB) the guarantee that delivery eligibility is
    anchored to alerts.published_at (the CarcinoS approval timestamp), NOT
    to the journal publication_date.

    Verified from migrations/13_audience_routing.sql:

        WHERE f.user_id = p_user_id
          AND f.published_at >= p_since

    where p_since = Monday of this week.

    Implications:
    - An alert with pub_date 35 days ago but published_at = today is INCLUDED
      (pub_date does not govern eligibility).
    - An alert with pub_date = today but published_at = last Monday is EXCLUDED
      (it already ran in last week's digest; published_at < p_since).

    The removal of _recent_enough() from deliver.py means no Python code
    re-introduces a pub_date gate after the RPC returns its results.
    """

    def test_rpc_uses_published_at_not_publication_date(self):
        """
        Smoke-test: the RPC SQL text from the migration must contain
        'published_at >= p_since' and must NOT filter on 'publication_date'.
        """
        import os, pathlib

        # Locate the migration relative to this test file's project root.
        # tests/ is a sibling of migrations/; walk up from this file.
        this_dir   = pathlib.Path(__file__).resolve().parent
        project_root = this_dir.parent
        migration  = project_root / "migrations" / "13_audience_routing.sql"

        if not migration.exists():
            pytest.skip(f"Migration file not found at {migration} — skipping conceptual check.")

        sql = migration.read_text()
        assert "f.published_at >= p_since" in sql, (
            "RPC must filter on published_at, not publication_date"
        )
        # publication_date must NOT appear in the WHERE clause
        # (it's fine in comments or RETURNS cols, but not as a filter)
        import re
        where_clause_match = re.search(r'WHERE(.+?)ORDER BY', sql, re.DOTALL)
        if where_clause_match:
            where_text = where_clause_match.group(1)
            assert "publication_date" not in where_text, (
                "RPC WHERE clause must not reference publication_date"
            )

    def test_no_recent_enough_in_deliver(self):
        """
        Confirm that `_recent_enough` no longer exists in deliver.py.
        If it reappears, this test catches the regression immediately.
        """
        import pathlib
        this_dir     = pathlib.Path(__file__).resolve().parent
        project_root = this_dir.parent
        deliver_py   = project_root / "carcinos_ingestion" / "deliver.py"

        if not deliver_py.exists():
            pytest.skip("deliver.py not found — skipping.")

        source = deliver_py.read_text()
        assert "_recent_enough" not in source, (
            "_recent_enough() was removed — it must not reappear in deliver.py"
        )
        assert "pub_cutoff = as_of - timedelta(days=10)" not in source, (
            "10-day pub_date cutoff was removed — it must not reappear."
        )
