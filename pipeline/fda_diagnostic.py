#!/usr/bin/env python3
"""
FDA lane diagnostic — run this locally to see exactly what each source returns.

Usage:
    cd /path/to/CarcinoS/pipeline
    python fda_diagnostic.py                        # last 14 days, no LLM
    python fda_diagnostic.py --days 21              # wider window
    python fda_diagnostic.py --openai-key sk-...    # also test LLM fallback

The script calls each FDA source independently and prints results so you can
see exactly what's failing before the next pipeline run.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

# Make sure the package is importable from the pipeline root
sys.path.insert(0, os.path.dirname(__file__))


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose FDA ingestion lane")
    parser.add_argument("--days", type=int, default=14,
                        help="Lookback window in days (default 14)")
    parser.add_argument("--openai-key", default=os.environ.get("OPENAI_API_KEY"),
                        help="OpenAI API key (for LLM fallback test). "
                             "Defaults to OPENAI_API_KEY env var.")
    parser.add_argument("--model", default="gpt-4o-mini-search-preview",
                        help="LLM model to use for fallback test")
    args = parser.parse_args()

    cutoff = date.today() - timedelta(days=args.days)
    print(f"\n{'='*60}")
    print(f"FDA DIAGNOSTIC  |  cutoff={cutoff.isoformat()}  |  lookback={args.days}d")
    print(f"{'='*60}\n")

    # ── Source 1: HTML scrape ──────────────────────────────────────────────────
    print("SOURCE 1: HTML approval notifications page scrape")
    print("-" * 50)
    try:
        from carcinos_ingestion.retrieval.fda import _scrape_approval_page
        items_page = _scrape_approval_page(cutoff=cutoff)
        if items_page:
            for i, item in enumerate(items_page, 1):
                print(f"  [{i}] {item.pub_date}  {item.title[:90]}")
                print(f"       URL: {item.url}")
        else:
            print("  ⚠ 0 items returned — either Akamai blocked the request,")
            print("    the table structure changed, or no approvals in window.")
    except Exception as exc:
        print(f"  ✗ EXCEPTION: {exc}")
    print()

    # ── Source 2: OpenFDA REST API ─────────────────────────────────────────────
    print("SOURCE 2: OpenFDA REST API (api.fda.gov/drug/drugsfda.json)")
    print("-" * 50)
    try:
        from carcinos_ingestion.retrieval.fda import _fetch_fda_via_openfda
        items_api = _fetch_fda_via_openfda(cutoff=cutoff)
        if items_api:
            for i, item in enumerate(items_api, 1):
                print(f"  [{i}] {item.pub_date}  {item.title[:90]}")
                print(f"       URL: {item.url}")
        else:
            print("  ⚠ 0 items — API returned nothing.")
            print("    Possible causes: OpenFDA lags press releases by days-weeks;")
            print("    the approval date in openFDA may not match the announcement date.")
    except Exception as exc:
        print(f"  ✗ EXCEPTION: {exc}")
    print()

    # ── Source 3: RSS feeds ────────────────────────────────────────────────────
    print("SOURCE 3: RSS feeds (fallback)")
    print("-" * 50)
    try:
        from carcinos_ingestion.retrieval.fda import _fetch_rss_items
        items_rss = _fetch_rss_items(cutoff=cutoff)
        if items_rss:
            for i, item in enumerate(items_rss, 1):
                print(f"  [{i}] {item.pub_date}  {item.title[:90]}")
        else:
            print("  ⚠ 0 items from RSS feeds")
    except Exception as exc:
        print(f"  ✗ EXCEPTION: {exc}")
    print()

    # ── Source 4: LLM web search ───────────────────────────────────────────────
    print(f"SOURCE 4: LLM web search (model={args.model})")
    print("-" * 50)
    if not args.openai_key:
        print("  — Skipped (no OpenAI API key). Pass --openai-key sk-... to test.")
    else:
        try:
            from carcinos_ingestion.retrieval.fda import _fetch_fda_via_llm
            items_llm = _fetch_fda_via_llm(
                cutoff=cutoff,
                openai_api_key=args.openai_key,
                model=args.model,
            )
            if items_llm:
                for i, item in enumerate(items_llm, 1):
                    print(f"  [{i}] {item.pub_date}  {item.title[:90]}")
                    print(f"       {item.summary[:120]}")
            else:
                print("  ⚠ 0 items from LLM search")
                print("    If the model returned an error, check pipeline logs above.")
        except Exception as exc:
            print(f"  ✗ EXCEPTION: {exc}")
    print()

    # ── Full combined run ──────────────────────────────────────────────────────
    print("COMBINED: retrieve_fda_records() (full pipeline call)")
    print("-" * 50)
    try:
        from carcinos_ingestion.retrieval.fda import retrieve_fda_records
        combined = retrieve_fda_records(
            lookback_days=args.days,
            openai_api_key=args.openai_key,
            llm_model=args.model,
        )
        print(f"  Total: {len(combined)} record(s)")
        for i, r in enumerate(combined, 1):
            print(f"  [{i}] {r.pub_date}  {r.title[:90]}")
        if not combined:
            print("  ✗ Zero records — the FDA lane will show nothing in the portal.")
    except Exception as exc:
        print(f"  ✗ EXCEPTION: {exc}")

    print()
    print("Done.")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(name)s  %(message)s")
    main()
