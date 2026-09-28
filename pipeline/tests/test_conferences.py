"""
Regression tests for ConferenceMeeting.is_active() and .get_pub_window().

Key scenarios validated
-----------------------
1.  ASTRO is active on Sep 28, 2026 (3 days before pub_month=10 start).
    Previously broken: is_active() required delta >= 0 so Sep 28 returned False.

2.  get_pub_window() on Sep 28, 2026 returns a 2026 window starting Sep 17,
    NOT a 2025 window.
    Previously broken: get_pub_window() fell back to the prior year because
    delta < 0 caused it to skip the current year.

3.  ASTRO is NOT active outside its window — far in the past or future — so
    the fix doesn't accidentally make it year-round.

4.  Normal post-pub behaviour is preserved: ASTRO is active on Oct 15, 2026
    (14 days after pub_month start) with the expected 2026 window.

5.  ASH January carry-over: Jan 15, 2027 sees ASH's Dec 2026 window.

6.  ESMO is active around its Sep 2026 pub_month and ASTRO is NOT active at
    the same time (ensures no cross-meeting bleed).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from carcinos_ingestion.retrieval.conferences import (
    MEETING_REGISTRY,
    get_active_meetings,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _meeting(short_code: str):
    for m in MEETING_REGISTRY:
        if m.short_code == short_code:
            return m
    raise KeyError(f"Meeting {short_code!r} not found in MEETING_REGISTRY")


ASTRO = _meeting("ASTRO")   # pub_month=10, window_days=14
ESMO  = _meeting("ESMO")    # pub_month=9,  window_days=14
ASH   = _meeting("ASH")     # pub_month=12, window_days=14


# ── 1.  is_active() pre-publication window ───────────────────────────────────

class TestIsActiveBugFix:
    """
    The original bug: `0 <= delta` prevented activation before pub_month's 1st.
    ASTRO has pub_month=10, window_days=14, so it should activate on Sep 17–30.
    """

    def test_astro_active_sep28_2026(self):
        """Sep 28 is 3 days before Oct 1 — within the 14-day pre-pub window."""
        assert ASTRO.is_active(date(2026, 9, 28)), (
            "ASTRO must be active on Sep 28 (3 days before pub_month start, "
            "within window_days=14)"
        )

    def test_astro_active_sep17_2026(self):
        """Sep 17 is exactly 14 days before Oct 1 — boundary should be active."""
        assert ASTRO.is_active(date(2026, 9, 17)), (
            "ASTRO must be active on Sep 17 (exactly window_days=14 before pub_month)"
        )

    def test_astro_inactive_sep16_2026(self):
        """Sep 16 is 15 days before Oct 1 — just outside window_days=14."""
        assert not ASTRO.is_active(date(2026, 9, 16)), (
            "ASTRO must NOT be active on Sep 16 (15 days before pub_month, "
            "outside window_days=14)"
        )

    def test_astro_inactive_aug1_2026(self):
        """Well before any window — must be inactive."""
        assert not ASTRO.is_active(date(2026, 8, 1)), (
            "ASTRO must NOT be active on Aug 1, 2026"
        )

    def test_astro_inactive_nov30_2026(self):
        """Well after the lookback window expires — must be inactive."""
        # Oct 1 + 35 (lookback) + 14 (window) = Nov 19 is last active day
        assert not ASTRO.is_active(date(2026, 11, 30)), (
            "ASTRO must NOT be active on Nov 30, 2026 (outside post-pub lookback)"
        )

    def test_astro_active_oct15_2026(self):
        """14 days after Oct 1 — firmly in the post-pub window."""
        assert ASTRO.is_active(date(2026, 10, 15))

    def test_astro_active_oct1_2026(self):
        """Oct 1 itself — pub_month start, delta=0, always was active."""
        assert ASTRO.is_active(date(2026, 10, 1))


# ── 2.  get_pub_window() returns 2026 window, not 2025 ───────────────────────

class TestGetPubWindowBugFix:
    """
    The original bug: when delta < 0, get_pub_window() skipped the current year
    and fell through to the previous year, returning a 2025 ASTRO window instead
    of the correct 2026 window.
    """

    def test_astro_pub_window_sep28_2026_is_2026(self):
        """
        On Sep 28, 2026 the window start must be 2026-09-17 (not 2025-09-17).
        """
        start, end = ASTRO.get_pub_window(date(2026, 9, 28))
        assert start == date(2026, 9, 17), (
            f"Window start must be 2026-09-17 (got {start}); "
            "2025 window would be a regression."
        )
        assert end == date(2026, 9, 28), (
            f"Window end should be capped at reference_date 2026-09-28 (got {end})"
        )

    def test_astro_pub_window_sep17_2026_boundary(self):
        """Boundary: Sep 17 = exactly window_days=14 before Oct 1."""
        start, end = ASTRO.get_pub_window(date(2026, 9, 17))
        assert start == date(2026, 9, 17)
        assert end == date(2026, 9, 17)   # capped at reference_date

    def test_astro_pub_window_oct15_2026_normal(self):
        """Normal post-pub case: start=Sep 17, end=Oct 15 (capped)."""
        start, end = ASTRO.get_pub_window(date(2026, 10, 15))
        assert start == date(2026, 9, 17)
        assert end == date(2026, 10, 15)

    def test_astro_pub_window_nov5_2026_full(self):
        """
        Oct 1 + 35 lookback = Nov 5; end is NOT capped before reference_date.
        """
        start, end = ASTRO.get_pub_window(date(2026, 11, 5))
        assert start == date(2026, 9, 17)
        assert end == date(2026, 11, 5)


# ── 3.  No cross-meeting bleed ───────────────────────────────────────────────

class TestNoBleed:
    """
    On Sep 28, 2026: ESMO (pub_month=9) should be active,
    ASTRO (pub_month=10) should ALSO be active (after fix),
    but meetings with distant pub_months should NOT be active.
    """

    def test_esmo_active_sep28_2026(self):
        """ESMO pub_month=9, Sep 28 is 27 days after Sep 1 — active."""
        assert ESMO.is_active(date(2026, 9, 28))

    def test_asco_inactive_sep28_2026(self):
        asco = _meeting("ASCO")  # pub_month=6
        assert not asco.is_active(date(2026, 9, 28)), (
            "ASCO (pub_month=6) must NOT be active in late September"
        )

    def test_ash_inactive_sep28_2026(self):
        assert not ASH.is_active(date(2026, 9, 28)), (
            "ASH (pub_month=12) must NOT be active in late September"
        )


# ── 4.  ASH Jan carry-over (existing correct behaviour preserved) ─────────────

class TestASHJanuaryCarryOver:
    """
    On Jan 15, 2027 ASH (pub_month=12) should still be active via the
    prior-year fallback, because delta from Dec 1 2026 is 45 days
    (< lookback_days=35 + window_days=14 = 49).
    """

    def test_ash_active_jan15_2027(self):
        assert ASH.is_active(date(2027, 1, 15)), (
            "ASH must be active on Jan 15, 2027 via the 2026 Dec window"
        )

    def test_ash_pub_window_jan15_2027_is_2026(self):
        start, end = ASH.get_pub_window(date(2027, 1, 15))
        assert start.year == 2026, f"Window must reference 2026 ASH (got {start})"
        assert start == date(2026, 11, 17)

    def test_ash_inactive_feb1_2027(self):
        # Dec 1 2026 + 49 = Jan 19 2027; Feb 1 is outside.
        assert not ASH.is_active(date(2027, 2, 1)), (
            "ASH must NOT be active on Feb 1, 2027"
        )


# ── 5.  get_active_meetings integration ──────────────────────────────────────

class TestGetActiveMeetings:

    def test_sep28_2026_includes_astro_and_esmo(self):
        active = {m.short_code for m in get_active_meetings(date(2026, 9, 28))}
        assert "ASTRO" in active, f"ASTRO missing from active meetings: {active}"
        assert "ESMO" in active,  f"ESMO missing from active meetings: {active}"

    def test_aug1_2026_excludes_astro(self):
        active = {m.short_code for m in get_active_meetings(date(2026, 8, 1))}
        assert "ASTRO" not in active

    def test_dec1_2026_includes_ash(self):
        active = {m.short_code for m in get_active_meetings(date(2026, 12, 1))}
        assert "ASH" in active
