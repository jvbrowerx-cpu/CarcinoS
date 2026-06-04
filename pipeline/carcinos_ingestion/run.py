"""
CLI entry point.

Examples:
  # Dry run for one site, no Supabase write, print stats + alert summaries to stdout
  python -m carcinos_ingestion.run --site head_neck --days 7 --dry-run

  # Run all 10 sites and write EXTRACTED alerts to Supabase
  python -m carcinos_ingestion.run --all --persist

  # Print the constructed PubMed query without retrieving
  python -m carcinos_ingestion.run --site gynecologic --print-query
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import date

from .config import Config
from .disease_sites import ALL_SITES, get as get_site
from .pipeline import run_site, AlertOutput


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="carcinos-ingest")
    site_group = p.add_mutually_exclusive_group(required=True)
    site_group.add_argument(
        "--site",
        choices=sorted(ALL_SITES.keys()),
        help="Run for a single disease-site code",
    )
    site_group.add_argument(
        "--all",
        action="store_true",
        help="Run all 10 disease sites sequentially",
    )
    p.add_argument("--days", type=int, default=7, help="Rolling window (default 7)")
    p.add_argument("--end", help="Window end date YYYY-MM-DD (default: today)")
    p.add_argument("--persist", action="store_true",
                   help="Write alerts to Supabase (default: dry run)")
    p.add_argument("--dry-run", action="store_true",
                   help="Force dry run, even if --persist is set")
    p.add_argument("--print-query", action="store_true",
                   help="Print the PubMed queries that would be sent and exit")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap candidates fed to LLM (cost-control for testing)")
    p.add_argument("--no-conferences", action="store_true",
                   help="Skip the conference supplement lane (faster, but misses ASCO/ESMO/ASTRO/ASH abstracts)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    cfg = Config.from_env()
    end = date.fromisoformat(args.end) if args.end else date.today()
    persist = args.persist and not args.dry_run

    sites = sorted(ALL_SITES.keys()) if args.all else [args.site]

    if args.print_query:
        for code in sites:
            s = get_site(code)
            start, _ = s.build_default_window(args.days)
            print(f"\n=== {s.name} ({s.code}) main query ===")
            print(s.build_main_query(start, end))
            print(f"\n=== {s.name} ({s.code}) journal force-include query ===")
            print(s.build_journal_force_query(start, end))
        return 0

    overall_alerts = 0
    overall_cost = 0.0
    summaries = []
    for code in sites:
        try:
            stats, alerts = run_site(
                code, config=cfg, days=args.days, persist=persist, end=end,
                include_conferences=not args.no_conferences,
            )
        except Exception as e:
            logging.exception("Pipeline failed for %s", code)
            summaries.append({"site": code, "error": str(e)})
            continue
        overall_alerts += stats.alerts_created
        overall_cost += stats.pass1_cost_usd + stats.pass2_cost_usd
        summaries.append({
            "stats": stats.to_dict(),
            "alerts": [_alert_summary(a) for a in alerts],
        })

    print(json.dumps({
        "total_alerts": overall_alerts,
        "total_estimated_cost_usd": round(overall_cost, 4),
        "by_site": summaries,
    }, indent=2, default=str))
    return 0


def _alert_summary(a: AlertOutput) -> dict:
    return {
        "pmid": a.candidate.pmid,
        "doi": a.candidate.doi,
        "title": a.candidate.title,
        "journal": a.candidate.journal,
        "publication_date": a.candidate.publication_date,
        "tier": a.pass2.final_tier_code,
        "notify": a.pass2.notify,
        "evidence": a.pass2.evidence_strength,
        "impact": a.pass2.impact_score,
        "grounded": a.grounded,
        "unverified_quotes": a.unverified_quotes,
        "carcinos_one_liner": a.pass2.parsed.get("carcinos_one_liner"),
    }


if __name__ == "__main__":
    sys.exit(main())
