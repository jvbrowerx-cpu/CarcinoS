"""
FDA Reconciliation — weekly safety net against pipeline misses.

Run every Monday before the digest is published:

  python -m carcinos_ingestion.reconcile_fda [--days 7] [--persist] [--dry-run]

What it does:
  1. Fetches the latest FDA oncology approvals via the same three-tier
     retrieval used in the main pipeline (HTML scrape → RSS → LLM supplement).
  2. Queries Supabase for alerts already in the queue tagged
     conference_source='FDA' from the past 14 days.
  3. For each FDA approval NOT found in Supabase (matched by fuzzy title
     similarity), runs it through Pass 2 extraction on the deep-review model
     and inserts it with status=EXTRACTED so the editor sees it in the queue.
  4. Prints a reconciliation report to stdout.

This is a safety net, not a replacement for the main pipeline. The main
pipeline's FDA lane has three-tier fallback + LLM supplement (added 2026-07-14).
This script catches the remaining tail risk: cases where the pipeline ran
before the FDA page updated, or where a site-routing mismatch silently
dropped a relevant record.

Exit codes:
  0  — all FDA approvals already in queue (clean)
  1  — gaps found (details printed; inserted if --persist was set)
  2  — error (check stderr)

GitHub Actions usage (add after the main pipeline step in weekly.yml):

  - name: FDA reconciliation
    run: python -m carcinos_ingestion.reconcile_fda --days 7 --persist
    env:
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    continue-on-error: false   # fail the workflow if errors occur
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger("carcinos.reconcile_fda")


# ---------------------------------------------------------------------------
# Title normalisation + fuzzy similarity
# ---------------------------------------------------------------------------

_NOISE = re.compile(r"[^a-z0-9 ]+")
_STOPWORDS = {"with", "for", "and", "the", "from", "into", "plus", "upon", "after", "versus"}


def _tokens(text: str) -> set[str]:
    """Lowercase, strip punctuation, remove short/stop words."""
    words = _NOISE.sub(" ", text.lower()).split()
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _jaccard(a: str, b: str) -> float:
    """Token-Jaccard similarity between two titles (0–1)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Site inference from FDA approval text
# ---------------------------------------------------------------------------

def _infer_site(text: str) -> str:
    """
    Return the most likely disease_site_code for an FDA approval record.
    Uses SITE_QUICK_TERMS substring counts; falls back to 'hematologic'
    (the most common FDA oncology approval category).
    """
    from .disease_sites.base import SITE_QUICK_TERMS
    text_lower = text.lower()
    best_site = "hematologic"
    best_count = 0
    for site_code, terms in SITE_QUICK_TERMS.items():
        count = sum(1 for t in terms if t in text_lower)
        if count > best_count:
            best_count = count
            best_site = site_code
    return best_site


# ---------------------------------------------------------------------------
# FDAItem → CanonicalCandidate
# ---------------------------------------------------------------------------

def _item_to_canonical(item, site_code: str, site_name: str):
    """Build a CanonicalCandidate from an FDAItem for reconciliation insertion."""
    from .normalize.canonical import CanonicalCandidate

    raw = f"FDA|{item.url}|{item.title}"
    text_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return CanonicalCandidate(
        pmid="",
        doi=None,
        nct_ids=[],
        text_hash=text_hash,
        title=item.title,
        abstract=item.summary,
        journal="FDA Hematology-Oncology",
        publication_date=item.pub_date,
        publication_types=["FDA Drug Approval"],
        mesh_terms=[],
        cancer_site_code=site_code,
        cancer_site_name=site_name,
        modality_keywords_present=[],
        deterministic_relevance_score=100,
        deterministic_low_confidence=False,
        deterministic_rationale=["fda_reconciliation"],
        pubtype_keep=True,
        pubtype_low_priority=False,
        pubtype_rationale="force-kept by FDA reconciliation lane",
        force_keep_reason="fda_reconciliation",
        is_conference_abstract=False,
        conference_source="FDA",
        raw_xml_hash=text_hash,
        source_url=item.url,
    )


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReconcileReport:
    fda_fetched: int = 0
    already_in_queue: int = 0
    gaps_found: int = 0
    gaps_inserted: int = 0
    gap_titles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main reconciliation logic
# ---------------------------------------------------------------------------

def run_reconcile(
    *,
    days: int = 7,
    persist: bool = False,
    config=None,
    reference_date: Optional[date] = None,
    similarity_threshold: float = 0.35,
) -> ReconcileReport:
    """
    Core reconciliation pass. Returns a ReconcileReport.

    Args:
        days:                 FDA lookback window in days (default 7).
        persist:              If True, insert missing approvals into Supabase.
        config:               Config object (required when persist=True).
        reference_date:       Window end date (default today).
        similarity_threshold: Token-Jaccard overlap required to consider a
                              Supabase alert as "matching" an FDA item.
                              0.35 works well empirically for FDA titles.
    """
    if reference_date is None:
        reference_date = date.today()

    report = ReconcileReport()

    # ── Step 1: Fetch FDA approvals ───────────────────────────────────────────
    from .retrieval.fda import fetch_fda_oncology_items

    openai_key = config.openai_api_key if config else None
    fda_items = fetch_fda_oncology_items(
        lookback_days=days,
        reference_date=reference_date,
        openai_api_key=openai_key,
    )
    report.fda_fetched = len(fda_items)
    log.info("FDA reconcile: fetched %d item(s) (lookback=%dd)", len(fda_items), days)

    if not fda_items:
        log.warning("FDA reconcile: no FDA approvals found in the past %d days — "
                    "verify the FDA scraper is working", days)
        return report

    # ── Step 2: Query Supabase for existing FDA alerts ────────────────────────
    #
    # We look back 14 days (wider than the FDA fetch) to catch approvals that
    # were inserted by a prior pipeline run earlier in the same week.
    existing_fda_titles: list[str] = []
    sb = None

    if config:
        try:
            from .persistence import SupabaseClient
            sb = SupabaseClient(
                url=config.supabase_url,
                service_role_key=config.supabase_service_role_key,
            )
            sb_cutoff = (reference_date - timedelta(days=14)).isoformat()

            # Select title + the conference_source field from summary_json.
            # Postgrest JSONB extraction: summary_json->>'conference_source'
            resp = (
                sb._client
                .table("alerts")
                .select("title, summary_json")
                .gte("created_at", sb_cutoff)
                .execute()
            )
            for row in (resp.data or []):
                sj = row.get("summary_json") or {}
                is_fda = (
                    sj.get("conference_source") == "FDA"
                    or sj.get("qualifying_signal") == "FDA"
                    or "fda" in (row.get("title") or "").lower()
                )
                if is_fda:
                    existing_fda_titles.append(row["title"])

            log.info(
                "FDA reconcile: %d existing FDA alert(s) found in Supabase (past 14d)",
                len(existing_fda_titles),
            )
        except Exception as exc:
            msg = f"Supabase query failed: {exc}"
            log.error("FDA reconcile: %s", msg)
            report.errors.append(msg)
            # Proceed without Supabase data — we can still report gaps
    else:
        log.info("FDA reconcile: no config — skipping Supabase lookup (dry run)")

    # ── Step 3: Identify gaps ─────────────────────────────────────────────────
    gaps = []
    for item in fda_items:
        matched = any(
            _jaccard(item.title, existing) >= similarity_threshold
            for existing in existing_fda_titles
        )
        if matched:
            report.already_in_queue += 1
            log.info("  ✓ in queue: %s", item.title[:90])
        else:
            gaps.append(item)
            report.gap_titles.append(item.title)
            log.warning("  ✗ MISSING:  %s", item.title[:90])

    report.gaps_found = len(gaps)

    if not gaps:
        log.info("FDA reconcile: all %d approval(s) already in queue", report.fda_fetched)
        return report

    log.warning(
        "FDA reconcile: %d gap(s) found out of %d FDA approval(s)",
        len(gaps), report.fda_fetched,
    )

    # ── Step 4: Insert gaps ───────────────────────────────────────────────────
    if not persist:
        log.info("FDA reconcile: dry run — pass --persist to auto-insert gaps")
        return report

    if not config or not config.openai_api_key:
        log.error("FDA reconcile: --persist requires OPENAI_API_KEY to run Pass 2")
        report.errors.append("OPENAI_API_KEY missing — cannot run Pass 2 for insertions")
        return report

    if sb is None:
        log.error("FDA reconcile: --persist requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY")
        report.errors.append("Supabase client not initialised — cannot insert")
        return report

    from .disease_sites import get as get_site
    from .triage.openai_client import OpenAIClient
    from .triage.pass2 import run_pass2, verify_evidence_quotes
    from .triage.pass1 import Pass1Result
    from .filters.signal_score import QS_FORCE_KEEP

    openai_client = OpenAIClient(
        api_key=config.openai_api_key,
        triage_model=config.triage_model,
        deep_review_model=config.deep_review_model,
    )

    for item in gaps:
        try:
            site_code = _infer_site(f"{item.title} {item.summary}")
            site = get_site(site_code)
            candidate = _item_to_canonical(item, site.code, site.name)

            # Synthetic Pass 1 — FDA force-keep bypasses LLM triage
            synthetic_p1 = Pass1Result(
                parsed={
                    "keep": True,
                    "relevance_score": 100,
                    "priority_hint": "high",
                    "one_line_rationale": "qualifying_signal=FDA; fda_reconciliation",
                    "drop_reason": None,
                },
                keep=True,
                relevance_score=100,
                priority_hint="high",
                drop_reason=None,
                cost_usd_estimate=0.0,
            )

            # Run Pass 2 for full extraction (tier, summary, one-liner, etc.)
            p2 = run_pass2(
                openai_client,
                candidate,
                synthetic_p1.parsed,
                qualifying_signal=QS_FORCE_KEEP,
                model=config.deep_review_model,
            )
            grounded, unverified = verify_evidence_quotes(p2.parsed, candidate.abstract)

            # Persist to Supabase
            source_id, trial_id = sb.upsert_source_and_trial(
                candidate, raw_xml=candidate.raw_xml_hash
            )
            if not trial_id:
                synth = sb._client.table("trials").insert({
                    "canonical_name": candidate.title[:200],
                    "phase": None,
                    "disease_site_id": sb.get_disease_site_id(site_code),
                    "keywords": [],
                }).execute()
                trial_id = synth.data[0]["id"]

            alert_id = sb.insert_alert(
                candidate, synthetic_p1, p2, source_id, trial_id,
                grounded=grounded,
                unverified_quotes=unverified,
            )

            # Record provenance in the audit log
            sb.audit(
                alert_id,
                action="fda_reconciliation_insert",
                diff={
                    "fda_url": item.url,
                    "fda_source": item.source,
                    "pub_date": item.pub_date,
                    "site_inferred": site_code,
                },
            )

            report.gaps_inserted += 1
            log.info(
                "  → inserted alert_id=%s tier=%s title=%s",
                alert_id, p2.final_tier_code, item.title[:80],
            )

        except Exception as exc:
            msg = f"insert failed for '{item.title[:60]}': {exc}"
            log.error("FDA reconcile: %s", msg)
            report.errors.append(msg)

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="carcinos-reconcile-fda",
        description="Reconcile FDA oncology approvals against the Supabase alert queue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run — shows gaps without writing anything
  python -m carcinos_ingestion.reconcile_fda --days 7

  # Insert any missing approvals into Supabase
  python -m carcinos_ingestion.reconcile_fda --days 7 --persist

  # Wider window to catch approvals from two weeks ago
  python -m carcinos_ingestion.reconcile_fda --days 14 --persist
""",
    )
    p.add_argument("--days", type=int, default=7,
                   help="FDA lookback window in days (default 7)")
    p.add_argument("--persist", action="store_true",
                   help="Insert missing approvals into Supabase (default: dry run)")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicitly suppress all writes (overrides --persist)")
    p.add_argument("--similarity", type=float, default=0.35,
                   help="Token-Jaccard threshold for duplicate detection (default 0.35)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Enable DEBUG logging")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    persist = args.persist and not args.dry_run
    config = None
    if persist or True:   # always load config so Supabase read works in dry-run too
        try:
            from .config import Config
            config = Config.from_env()
        except Exception as exc:
            log.warning("Config load failed (%s) — proceeding without Supabase", exc)

    report = run_reconcile(
        days=args.days,
        persist=persist,
        config=config,
        similarity_threshold=args.similarity,
    )

    # ── Report ──────────────────────────────────────────────────────────────
    sep = "─" * 62
    print()
    print(sep)
    print("  CarcinoS FDA Reconciliation Report")
    print(sep)
    print(f"  FDA approvals fetched  (past {args.days}d):  {report.fda_fetched}")
    print(f"  Already in queue:                       {report.already_in_queue}")
    print(f"  Gaps found:                             {report.gaps_found}")
    print(f"  Gaps inserted:                          {report.gaps_inserted}")

    if report.gap_titles:
        print()
        print("  MISSING FDA APPROVALS:")
        for i, title in enumerate(report.gap_titles, 1):
            inserted = i <= report.gaps_inserted
            tag = "✓ inserted" if inserted else ("✗ not inserted" if persist else "⚠ dry run")
            print(f"    [{tag}]  {title}")

    if report.errors:
        print()
        print("  ERRORS:")
        for err in report.errors:
            print(f"    ✗  {err}")

    print(sep)
    print()

    if report.errors:
        return 2
    if report.gaps_found > 0 and not persist:
        # Gaps found in dry run — alert CI but don't fail the job
        return 1
    if report.gaps_found > 0 and report.gaps_inserted < report.gaps_found:
        # Some gaps remain uninserted after a persist attempt
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
