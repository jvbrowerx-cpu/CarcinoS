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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    p.add_argument("--no-fda", action="store_true",
                   help="Skip the FDA oncology approvals RSS lane")
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
    summaries_lock = threading.Lock()

    # Run sites sequentially to respect NCBI's PubMed rate limit (3 req/sec
    # without API key, 10/sec with). Parallel LLM calls within each site
    # (pipeline.py) already provide the major speedup.
    _SITE_WORKERS = 1

    def _run_one_site(code: str):
        return code, run_site(
            code, config=cfg, days=args.days, persist=persist, end=end,
            include_conferences=not args.no_conferences,
            include_fda=not args.no_fda,
        )

    with ThreadPoolExecutor(max_workers=_SITE_WORKERS) as pool:
        futures = {pool.submit(_run_one_site, code): code for code in sites}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                code, (stats, alerts) = fut.result()
                # Print cards as each site completes
                for a in alerts:
                    _print_card(a)
                with summaries_lock:
                    overall_alerts += stats.alerts_created
                    overall_cost += stats.pass2_cost_usd
                    summaries.append({
                        "stats": stats.to_dict(),
                        "alerts": [_alert_summary(a) for a in alerts],
                    })
            except Exception as e:
                logging.exception("Pipeline failed for %s", code)
                with summaries_lock:
                    summaries.append({"site": code, "error": str(e)})

    print(json.dumps({
        "total_alerts": overall_alerts,
        "total_estimated_cost_usd": round(overall_cost, 4),
        "by_site": summaries,
    }, indent=2, default=str))
    return 0


def _alert_summary(a: AlertOutput) -> dict:
    p2 = a.pass2.parsed
    kr = p2.get("key_results") or {}
    return {
        "pmid": a.candidate.pmid,
        "doi": a.candidate.doi,
        "title": a.candidate.title,
        "journal": a.candidate.journal,
        "publication_date": a.candidate.publication_date,
        "is_conference_abstract": a.candidate.is_conference_abstract,
        "conference_source": a.candidate.conference_source,
        "tier": a.pass2.final_tier_code,
        "notify": a.pass2.notify,
        "evidence": a.pass2.evidence_strength,
        "tier_rationale": a.pass2.tier_rationale_text,
        "grounded": a.grounded,
        "unverified_quotes": a.unverified_quotes,
        "population": p2.get("population"),
        "regimen_description": p2.get("regimen_description"),
        "intervention": p2.get("intervention"),
        "comparator": p2.get("comparator"),
        "primary_endpoint": p2.get("primary_endpoint"),
        "effect_size": kr.get("effect_size"),
        "p_value_or_ci": kr.get("p_value_or_ci"),
        "absolute_difference": kr.get("absolute_difference"),
        "toxicity_qol_signal": kr.get("toxicity_qol_signal"),
        "limitations_flags": p2.get("limitations_flags") or [],
        "who_should_care": p2.get("who_should_care") or [],
        "carcinos_one_liner": p2.get("carcinos_one_liner"),
        "why_it_surfaced": p2.get("why_it_surfaced"),
        "radiation_oncology_relevance": p2.get("radiation_oncology_relevance"),
        "confidence": p2.get("confidence"),
        "reject_recommendation": p2.get("reject_recommendation", False),
    }


# ---------------------------------------------------------------------------
# Terminal card printer — CarcinoS card format with ANSI tier colours
# ---------------------------------------------------------------------------

# ANSI helpers
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"

# Tier colours: Practice Impacting = green, Incremental = white/bold, Horizon = dim
_TIER_COLOR = {
    "A": "\033[92m",   # bright green
    "B": "\033[97m",   # bright white
    "C": "\033[37m",   # light gray / dim
}
_TIER_LABEL = {
    "A": "■■■ PRACTICE IMPACTING",
    "B": "■■  INCREMENTAL",
    "C": "■   HORIZON",
}
_TIER_BADGE = {
    "A": "\033[42m\033[30m",   # green bg, black text
    "B": "\033[47m\033[30m",   # white bg, black text
    "C": "\033[100m\033[97m",  # dark-gray bg, white text
}


def _print_card(a: AlertOutput) -> None:
    """Print a full CarcinoS-style card to stdout for dry-run review."""
    p2 = a.pass2.parsed
    kr = p2.get("key_results") or {}
    tier = a.pass2.final_tier_code
    tc   = _TIER_COLOR.get(tier, "")
    tb   = _TIER_BADGE.get(tier, "")

    sep = "─" * 72

    # ── Tier banner ──────────────────────────────────────────────────────────
    label = _TIER_LABEL.get(tier, tier)
    conf_badge = ""
    if getattr(a.candidate, "is_conference_abstract", False):
        src = getattr(a.candidate, "conference_source", "") or "CONFERENCE"
        conf_badge = f"  {_DIM}[{src.upper()} ABSTRACT]{_RESET}"
    print(f"\n{tc}{_BOLD}{sep}{_RESET}")
    print(f"{tb} {label} {_RESET}{conf_badge}  "
          f"{_DIM}Evidence {a.pass2.evidence_strength} · {a.pass2.tier_rationale_text}{_RESET}")
    print(f"{tc}{sep}{_RESET}")

    # ── Journal / Date ───────────────────────────────────────────────────────
    journal = a.candidate.journal or ""
    pub_date = a.candidate.publication_date or ""
    if journal or pub_date:
        parts = []
        if journal:  parts.append(f"{_BOLD}Journal:{_RESET} {journal}")
        if pub_date: parts.append(f"{_BOLD}Date:{_RESET} {pub_date}")
        print("  " + "   ".join(parts))

    # ── Title ────────────────────────────────────────────────────────────────
    print(f"  {_BOLD}Title:{_RESET} {a.candidate.title or '(no title)'}")

    # ── Relevant population ──────────────────────────────────────────────────
    population = p2.get("population") or ""
    if population and population != "not_reported":
        print(f"  {_BOLD}Relevant population:{_RESET} {population}")

    # ── Study / regimen ──────────────────────────────────────────────────────
    regimen = p2.get("regimen_description") or ""
    if not regimen:
        # Fallback: build from parts
        parts = []
        sd = (p2.get("study_design") or "").replace("_", " ")
        if sd:  parts.append(sd)
        iv = p2.get("intervention") or ""
        cp = p2.get("comparator") or ""
        if iv: parts.append(iv)
        if cp and cp != "not_reported": parts.append(f"vs {cp}")
        regimen = "; ".join(parts)
    if regimen:
        print(f"  {_BOLD}Study / regimen{_RESET} (high level): {regimen}")

    # ── Key findings ─────────────────────────────────────────────────────────
    finding_parts = []
    es  = kr.get("effect_size") or ""
    pv  = kr.get("p_value_or_ci") or ""
    ad  = kr.get("absolute_difference") or ""
    tox = kr.get("toxicity_qol_signal") or ""
    if es  and es  != "not_reported": finding_parts.append(f"{_BOLD}{es}{_RESET}")
    if pv  and pv  != "not_reported": finding_parts.append(pv)
    if ad  and ad  != "not_reported": finding_parts.append(ad)
    findings_line = " · ".join(finding_parts)
    if findings_line or (tox and tox != "not_reported"):
        print(f"  {_BOLD}Key findings:{_RESET}", end="")
        if findings_line: print(f" {findings_line}", end="")
        print()
        if tox and tox != "not_reported":
            print(f"    {tox}")

    # ── So what ──────────────────────────────────────────────────────────────
    one_liner = p2.get("carcinos_one_liner") or ""
    if one_liner:
        print(f"  {_BOLD}So what (clinical implication):{_RESET} {one_liner}")

    # ── Signal / confidence metadata ─────────────────────────────────────────
    why_surfaced = p2.get("why_it_surfaced") or ""
    confidence   = p2.get("confidence") or ""
    rad_rel      = p2.get("radiation_oncology_relevance") or ""
    reject_rec   = bool(p2.get("reject_recommendation", False))
    meta_parts   = []
    if confidence: meta_parts.append(f"Confidence: {confidence.upper()}")
    if rad_rel:    meta_parts.append(f"RT relevance: {rad_rel}")
    if reject_rec: meta_parts.append("\033[33m⚠ LLM REJECT RECOMMENDATION\033[0m")
    if meta_parts:
        print(f"  {_DIM}{' · '.join(meta_parts)}{_RESET}")
    if why_surfaced:
        print(f"  {_DIM}Gate signal: {why_surfaced}{_RESET}")

    # ── Footer tags ──────────────────────────────────────────────────────────
    tags = []
    limits = p2.get("limitations_flags") or []
    who    = p2.get("who_should_care") or []
    if limits: tags.append(f"{_DIM}⚠ {', '.join(limits)}{_RESET}")
    if who:    tags.append(f"{_DIM}→ {', '.join(who)}{_RESET}")
    if not a.grounded:
        tags.append("\033[33m⚠ VERIFY ABSTRACT — quotes unverified\033[0m")
    if tags:
        print(f"  {' · '.join(tags)}")

    # ── PubMed link ──────────────────────────────────────────────────────────
    if a.candidate.pmid:
        print(f"  {_DIM}https://pubmed.ncbi.nlm.nih.gov/{a.candidate.pmid}/{_RESET}")


if __name__ == "__main__":
    sys.exit(main())
