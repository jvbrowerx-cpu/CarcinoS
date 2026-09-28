"""
Pre-retrieval LLM context brief — dynamic trial watch list augmentation.

Before the pipeline touches PubMed, this module asks gpt-4o-mini a single
question: "Given today's date and this disease site, what specific trials or
FDA decisions should we search for right now?"

The response is a list of trial acronyms and NCT numbers that gets merged into
the site's curated watched_trials list for the current run. Any paper mentioning
a name on the merged list gets QS_WATCHED_TRIAL auto-admission (Gate 2 priority 3).

Why this matters
----------------
Deterministic gates are designed for precision — they don't miss randomized trials
that use clear Phase III language. But they miss papers that ARE high-value but
whose PubMed abstract doesn't trigger a qualifying signal:

  • ASCO LBA papers may have sparse abstracts
  • Named trials use their acronym prominently but may not say "Phase III"
    prominently enough to clear the borrowed-language guard
  • FDA decisions published as drug-label documents, not research articles

The LLM's training data knows which trials were in active Phase III status with
expected 2025-2026 readouts. It knows the ASCO Annual Meeting is in June. It
connects those dots. The static curated watchlists cannot.

Cost
----
One gpt-4o-mini call per site per run.
  ~500 tokens in + ~300 tokens out × 10 sites ≈ $0.01-0.02 per weekly run.

Failure mode
------------
Always returns ([], 0.0) on any error — never blocks the pipeline.
Logged as WARNING so the operator knows the brief was skipped.

Schema
------
The LLM returns a strict JSON object:
  {
    "trials": ["LAURA", "NCT03521153", ...],   // trial acronyms / NCT numbers
    "reasoning": "ASCO 2026 is happening now; LAURA Phase III results..."
  }
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .openai_client import OpenAIClient

log = logging.getLogger("carcinos.context_brief")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_BRIEF_SYSTEM = """\
You are an oncology trial surveillance assistant for CarcinoS, a clinical
intelligence pipeline that monitors oncology literature weekly.

Your job: given today's date and a cancer disease site, return the specific
clinical trial acronyms and NCT numbers that are most likely to have published
primary results, updated survival data, or received FDA action in the PAST 21
DAYS — or are presenting right now at a major oncology conference (ASCO, ESMO,
ASTRO, ASH, AACR, SITC).

Focus areas:
  1. Phase III trials with known readout windows near today's date
  2. Named trials presenting at any active or just-concluded major meeting
  3. FDA approvals or label changes in this disease area
  4. High-profile Phase II trials that recently published paradigm-shifting data

Output rules:
  • Return trial ACRONYMS (e.g. "LAURA", "PATHOS") or NCT numbers ("NCT03521153")
    rather than generic drug names alone — specific names match better in PubMed.
  • Include a drug+trial name combo only when the trial has no common acronym
    (e.g. "nivolumab CheckMate-816").
  • 5 to 20 entries maximum. Fewer, more confident entries beat a long speculative
    list — hallucinated trial names will pollute search results.
  • If today is during or within 14 days of a named meeting (e.g. "ASCO 2026,
    June 1-3"), prioritise the expected late-breaking presentations from that
    meeting even if you're not certain of the final title.
  • If you have no specific knowledge for this date + site, return an empty list.
  • IMPORTANT: The "already_watching" list contains trials the pipeline monitors
    statically, but it does NOT mean those papers have been found yet. If any trial
    on the already_watching list has RECENTLY PUBLISHED (within 21 days) or is
    presenting at a current conference, you MUST include it in your output so the
    web search lane actively hunts for it this week. Do not skip a trial just
    because it appears in already_watching — skip it only if it has NOT recently
    published and is not expected to publish this week.

Return strict JSON matching the schema. No markdown, no explanation outside the
JSON fields."""

_BRIEF_USER = """\
Today's date: {today}
Disease site: {site_name} ({site_code})

Active / recent major meetings (within ±21 days of today):
{active_meetings}

Already watching (do NOT skip these if they have recently published — include \
them if results dropped in the past 21 days):
{existing_trials}

What specific trial acronyms or NCT numbers should we search for in PubMed \
and on journal websites over the past 21 days for this disease site? \
Include any watched trials that recently published. Return JSON only."""

# JSON schema for the structured response
_BRIEF_SCHEMA = {
    "name": "context_brief",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "trials": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Trial acronyms (e.g. 'LAURA'), NCT numbers "
                    "(e.g. 'NCT03521153'), or drug+trial combos "
                    "(e.g. 'nivolumab CheckMate-816'). 5–20 entries max."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "1-3 sentence explanation of why these trials were selected — "
                    "e.g. which conference is active, which regulatory window applies."
                ),
            },
        },
        "required": ["trials", "reasoning"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Meeting calendar (mirrors conferences.py — kept minimal here to avoid import)
# ---------------------------------------------------------------------------

_MEETING_WINDOWS: list[tuple[str, int, int]] = [
    # (display_name, pub_month, window_days_before_after)
    ("ASCO Annual Meeting",            6,  21),
    ("ASCO GU Symposium",              2,  14),
    ("ASCO Breast Cancer Symposium",  10,  14),
    ("ESMO Congress",                  9,  21),
    ("ESMO Breast Cancer Congress",    5,  14),
    ("ASTRO Annual Meeting",          10,  21),
    ("ASH Annual Meeting",            12,  21),
    ("AACR Annual Meeting",            4,  14),
    ("SGO Annual Meeting",             3,  14),
    ("SITC Annual Meeting",           11,  14),
    ("SABCS",                         12,  14),
]


def _active_meetings_str(today: date) -> str:
    """Return a human-readable list of meetings currently active or just concluded."""
    from datetime import timedelta
    active = []
    for name, pub_month, window in _MEETING_WINDOWS:
        for year in (today.year, today.year - 1):
            try:
                meeting_start = date(year, pub_month, 1)
            except ValueError:
                continue
            delta = (today - meeting_start).days
            if -7 <= delta <= window:   # 7 days before to window days after
                active.append(f"  • {name} ({year})")
    return "\n".join(active) if active else "  • None currently active"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_context_brief(
    client: "OpenAIClient",
    *,
    site_name: str,
    site_code: str,
    existing_trials: list[str],
    today: date | None = None,
) -> tuple[list[str], float]:
    """
    Generate a dynamic trial watch list for the current run.

    Returns:
        (new_trials, cost_usd_estimate)
        new_trials: list of trial names/NCT numbers NOT in existing_trials.
                    Empty list on any failure.
        cost_usd_estimate: rough token-based cost estimate.

    The returned list should be merged into watched_trials before retrieval:
        effective_watchlist = frozenset(site.watched_trials) | frozenset(new_trials)
    """
    if today is None:
        today = date.today()

    existing_str = (
        ", ".join(existing_trials[:30]) if existing_trials else "none"
    )
    active_mtg = _active_meetings_str(today)

    user_msg = _BRIEF_USER.format(
        today=today.isoformat(),
        site_name=site_name,
        site_code=site_code,
        active_meetings=active_mtg,
        existing_trials=existing_str,
    )

    try:
        result = client.structured(
            model=client.triage_model,   # gpt-4o-mini
            system=_BRIEF_SYSTEM,
            user=user_msg,
            schema=_BRIEF_SCHEMA,
            temperature=0.2,
        )
    except Exception as exc:
        log.warning("[%s] context_brief LLM call failed: %s", site_code, exc)
        return [], 0.0

    raw_trials: list = result.parsed.get("trials") or []
    reasoning: str   = result.parsed.get("reasoning") or ""

    # Sanitise: keep non-empty strings, strip whitespace
    cleaned = [t.strip() for t in raw_trials if isinstance(t, str) and t.strip()]

    # Keep ALL trials the LLM flagged as recently published — including ones
    # already in the static watched_trials list. The LLM is telling us these
    # trials have ACTIVE results right now and need to be prioritised in Lane 5.
    # We only drop exact duplicates within the returned list itself.
    seen: set[str] = set()
    new_trials = []
    for t in cleaned:
        if t.lower() not in seen:
            seen.add(t.lower())
            new_trials.append(t)

    # Cost estimate (gpt-4o-mini: $0.15/1M in, $0.60/1M out)
    usage = result.usage
    cost = (
        usage.get("prompt_tokens", 0)     * 0.15 / 1_000_000
        + usage.get("completion_tokens", 0) * 0.60 / 1_000_000
    )

    log.info(
        "[%s] context_brief → %d new trials added (reasoning: %s)",
        site_code,
        len(new_trials),
        reasoning[:120],
    )
    if new_trials:
        log.info("[%s] context_brief trials: %s", site_code, new_trials)

    return new_trials, cost
