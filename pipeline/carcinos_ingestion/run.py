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
from .filters.trial_dedup import deduplicate_by_trial_name
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
    p.add_argument("--no-web-search", action="store_true",
                   help="Skip Lane 5 GPT-4o web search (saves ~$2.50/run; use for PubMed-only testing)")
    p.add_argument("--max-cards", type=int, default=10,
                   help="Hard cap on weekly output cards across all sites (default 10). "
                        "Cards are selected tier-first (A → B → C), then by Gate 3 score. "
                        "Use 0 to disable the cap (show all survivors).")
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

    overall_cost = 0.0
    per_site_stats = []   # list of (stats, alerts) tuples, one per site
    all_alerts: list[AlertOutput] = []

    # Cross-site PMID deduplication: the same paper (e.g. pembrolizumab SC/IV)
    # can be retrieved by multiple disease sites. seen_pmids is shared across
    # all site runs so each PMID is processed (and written to Supabase) only
    # once — by whichever site retrieves it first in alphabetical order.
    seen_pmids: set[str] = set()

    # Run sites sequentially to respect NCBI's PubMed rate limit (3 req/sec
    # without API key, 10/sec with). Parallel LLM calls within each site
    # (pipeline.py) already provide the major speedup.
    for code in sites:
        try:
            stats, alerts = run_site(
                code, config=cfg, days=args.days, persist=persist, end=end,
                include_conferences=not args.no_conferences,
                include_fda=not args.no_fda,
                include_web_search=not args.no_web_search,
                seen_pmids=seen_pmids,
            )
            overall_cost += (stats.pass2_cost_usd + stats.context_brief_cost_usd
                             + stats.web_search_cost_usd)
            per_site_stats.append((code, stats, alerts))
            all_alerts.extend(alerts)
            if stats.context_brief_trials:
                logging.info("[%s] context_brief added: %s", code, stats.context_brief_trials)
        except Exception as e:
            logging.exception("Pipeline failed for %s", code)
            per_site_stats.append((code, None, []))

    # ── Trial-name deduplication ─────────────────────────────────────────────
    # After all sites complete, remove duplicate cards for the same named trial.
    # Example: FLAURA2 OS data might appear as both a JCO article (main lane)
    # and an ASCO abstract (conference lane). Only the highest-priority source
    # (FDA > journal > conference abstract) is retained.
    deduplicated, trial_dropped = deduplicate_by_trial_name(all_alerts)
    if trial_dropped:
        logging.info(
            "[trial_dedup] dropped %d trial-name duplicate(s): %s",
            len(trial_dropped),
            [a.candidate.pmid for a in trial_dropped],
        )

    # ── Hard output cap ──────────────────────────────────────────────────────
    # Apply weekly card cap (default 10) after all deduplication.
    # Selection is tier-first (A → B → C), then by Gate 3 additive score.
    # FDA / guideline records (Tier A) are never cut — they're why the pipeline
    # exists. Tier B and C are trimmed if the total exceeds max_cards.
    max_cards = args.max_cards if hasattr(args, "max_cards") else 10
    capped, cap_dropped = _apply_output_cap(deduplicated, max_cards)
    if cap_dropped:
        logging.info(
            "[output_cap] capped at %d; dropped %d lower-priority card(s): %s",
            max_cards,
            len(cap_dropped),
            [a.candidate.pmid for a in cap_dropped],
        )

    # Build the final PMID set for fast lookup
    kept_pmids = {a.candidate.pmid for a in capped}

    # ── Print cards and build summaries ─────────────────────────────────────
    summaries = []
    overall_alerts = 0
    for code, stats, alerts in per_site_stats:
        if stats is None:
            summaries.append({"site": code, "error": "pipeline failed"})
            continue
        # Only include alerts that survived both dedup and cap
        site_alerts = [a for a in alerts if a.candidate.pmid in kept_pmids]
        for a in site_alerts:
            _print_card(a)
        overall_alerts += len(site_alerts)
        site_pmids = {a.candidate.pmid for a in alerts}
        summaries.append({
            "stats": stats.to_dict(),
            "alerts": [_alert_summary(a) for a in site_alerts],
            "trial_dedup_dropped": [a.candidate.pmid for a in trial_dropped
                                    if a.candidate.pmid in site_pmids],
            "cap_dropped": [a.candidate.pmid for a in cap_dropped
                            if a.candidate.pmid in site_pmids],
        })

    print(json.dumps({
        "total_alerts": overall_alerts,
        "trial_dedup_dropped_total": len(trial_dropped),
        "cap_dropped_total": len(cap_dropped),
        "total_estimated_cost_usd": round(overall_cost, 4),
        "by_site": summaries,
    }, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# Output cap: tier-priority selection, hard weekly maximum
# ---------------------------------------------------------------------------

_TIER_ORDER = {"A": 0, "B": 1, "C": 2}   # lower = higher priority

def _apply_output_cap(
    alerts: list[AlertOutput],
    max_cards: int,
) -> tuple[list[AlertOutput], list[AlertOutput]]:
    """
    Apply the weekly output cap.

    Selection logic:
      1. Always keep all Tier A (FDA / guideline / Phase III OS) — never cut.
      2. Sort remaining (B then C) by Gate 3 additive score descending.
      3. Take as many as fit within max_cards.

    Args:
        alerts:    All alerts surviving trial-name dedup.
        max_cards: Hard cap (0 = disabled).

    Returns:
        (kept, dropped)
    """
    if max_cards <= 0:
        return alerts, []

    tier_a = [a for a in alerts if a.pass2.final_tier_code == "A"]
    tier_bc = [a for a in alerts if a.pass2.final_tier_code != "A"]

    # Sort B and C: tier first (B before C), then Gate 3 score descending
    tier_bc_sorted = sorted(
        tier_bc,
        key=lambda a: (
            _TIER_ORDER.get(a.pass2.final_tier_code, 9),
            -(getattr(a.pass1, "relevance_score", 0) or 0),
        ),
    )

    slots_remaining = max(0, max_cards - len(tier_a))
    kept_bc = tier_bc_sorted[:slots_remaining]
    dropped_bc = tier_bc_sorted[slots_remaining:]

    if dropped_bc:
        logging.info(
            "[output_cap] %d Tier-A cards kept unconditionally; "
            "%d/%d Tier-B/C kept (%d dropped to stay within %d-card cap)",
            len(tier_a),
            len(kept_bc),
            len(tier_bc),
            len(dropped_bc),
            max_cards,
        )

    return tier_a + kept_bc, dropped_bc


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
        "trial_name": p2.get("trial_name"),
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
