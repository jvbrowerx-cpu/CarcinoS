"""
Orchestrator — runs the full ingestion pipeline for a single disease site.

Flow (matches the spec doc):

  Step 1.  Build deterministic PubMed query (per-site config)
  Step 2.  esearch + efetch  → PubMedRecord list
           - second lane: journal force-include query
  Step 3.  Hard dedupe (PMID/DOI) → fuzzy dedupe (title sim ≥ 0.92)
  Step 4.  Pubtype filter (drop editorials/letters/case reports)
           with journal-whitelist override
  Step 5.  Deterministic relevance scoring
  Step 6.  Normalize → CanonicalCandidate
  Step 7.  Pass 1 LLM triage → keep rules
  Step 8.  Pass 2 LLM deep review (only on Pass 1 keeps)
           - quote grounding check
           - tier mapping enforced by code
  Step 9.  Persist to Supabase (alerts + sources + audit log)
           - status = EXTRACTED (founder editor must approve before PUBLISH)
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

from .config import Config
from .disease_sites import get as get_site
from .disease_sites.base import DiseaseSiteConfig
from .retrieval.pubmed import PubMedClient, PubMedRecord
from .filters.dedupe import dedupe
from .filters.pubtype import filter_by_pubtype
from .filters.relevance import score_relevance
from .normalize.canonical import to_canonical, CanonicalCandidate
from .triage.openai_client import OpenAIClient
from .triage.pass1 import run_pass1, enforce_pass1_keep_rules, Pass1Result
from .triage.pass2 import run_pass2, verify_evidence_quotes, Pass2Result

log = logging.getLogger("carcinos.pipeline")


@dataclass
class RunStats:
    site_code: str
    site_name: str
    window_start: str
    window_end: str
    raw_count: int = 0
    deduped_count: int = 0
    pubtype_kept_count: int = 0
    deterministic_kept_count: int = 0
    pass1_kept_count: int = 0
    pass2_run_count: int = 0
    grounded_count: int = 0
    alerts_created: int = 0
    alerts_by_tier: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0, "NOISE": 0})
    pass1_cost_usd: float = 0.0
    pass2_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AlertOutput:
    """In-memory alert that the orchestrator hands back to callers
    (the persistence layer will write this to the alerts table)."""
    candidate: CanonicalCandidate
    pass1: Pass1Result
    pass2: Pass2Result
    grounded: bool
    unverified_quotes: list[str]


def run_site(
    site_code: str,
    *,
    config: Config,
    days: int = 7,
    persist: bool = False,
    end: Optional[date] = None,
    include_conferences: bool = True,
    seen_pmids: set[str] | None = None,
) -> tuple[RunStats, list[AlertOutput]]:
    """
    Run the full pipeline for a single disease site.

    Returns (RunStats, list[AlertOutput]) — alerts are NOT persisted unless
    persist=True (in which case they are written to Supabase as EXTRACTED
    rows for the founder editor to review).
    """
    site = get_site(site_code)
    if end is None:
        end = date.today()
    start = end.replace()
    from datetime import timedelta
    start = end - timedelta(days=days)

    stats = RunStats(
        site_code=site.code, site_name=site.name,
        window_start=start.isoformat(), window_end=end.isoformat(),
    )

    log.info("[%s] Running pipeline for %s..%s", site.code, start, end)

    # ---- STEP 1+2  retrieval -------------------------------------------
    pubmed = PubMedClient(email=config.ncbi_email, api_key=config.ncbi_api_key)
    records = _retrieve(pubmed, site, start, end, max_pmids=config.max_pmids_per_query,
                        include_conferences=include_conferences)
    stats.raw_count = len(records)
    log.info("[%s] retrieved %d PubMed records", site.code, stats.raw_count)

    # ---- STEP 3  dedupe -------------------------------------------------
    records = dedupe(records)
    stats.deduped_count = len(records)
    log.info("[%s] %d after dedupe", site.code, stats.deduped_count)

    # ---- STEP 3a  cross-site PMID filter --------------------------------
    # Drop PMIDs already processed by a previous disease site this run.
    # Prevents the same paper appearing multiple times in the editor queue.
    if seen_pmids:
        before = len(records)
        records = [r for r in records if r.pmid not in seen_pmids]
        dropped = before - len(records)
        if dropped:
            log.info("[%s] %d cross-site duplicates removed", site.code, dropped)

    # ---- STEP 3b  English-only filter -----------------------------------
    records = [r for r in records if (r.language or "eng").lower() in ("eng", "english", "")]
    log.info("[%s] %d after English-only filter", site.code, len(records))

    # ---- STEP 3c  Abstract required -------------------------------------
    # Articles without abstracts cannot be meaningfully triaged by the LLM.
    # Exception: force-keep journals (whitelisted) may still pass without abstract.
    whitelist = list(site.journal_whitelist())
    records_with_abstract = [r for r in records if r.abstract]
    records_no_abstract_whitelisted = [
        r for r in records if not r.abstract and r.matches_journal_whitelist(whitelist)
    ]
    records = records_with_abstract + records_no_abstract_whitelisted
    log.info("[%s] %d after abstract filter", site.code, len(records))

    # ---- STEP 4  pubtype filter -----------------------------------------
    pubtyped = filter_by_pubtype(records, journal_force_keep=whitelist)
    stats.pubtype_kept_count = len(pubtyped)
    log.info("[%s] %d after pubtype filter", site.code, stats.pubtype_kept_count)

    # ---- STEP 5+6  relevance + canonicalize -----------------------------
    # Force-keep (journal whitelist) articles are capped to avoid flooding
    # the LLM during high-volume periods (e.g. ASCO supplement month).
    MAX_FORCE_KEEP = 20
    canonicals: list[CanonicalCandidate] = []
    force_kept_count = 0
    for r, pubtype_decision in pubtyped:
        rel = score_relevance(r, site)
        force_keep_reason = None
        if r.matches_journal_whitelist(whitelist):
            if rel.keep:
                # High-relevance whitelisted article — always keep
                force_keep_reason = "journal_whitelist"
            elif force_kept_count < MAX_FORCE_KEEP:
                # Low-relevance but whitelisted — keep up to cap
                force_keep_reason = "journal_whitelist_capped"
                force_kept_count += 1
            else:
                # Cap reached — skip low-relevance whitelist articles
                log.debug("[%s] force-keep cap reached, skipping pmid=%s", site.code, r.pmid)
                continue

        if not rel.keep and not force_keep_reason:
            continue
        canonicals.append(to_canonical(r, site, pubtype_decision, rel, force_keep_reason))
    stats.deterministic_kept_count = len(canonicals)
    log.info("[%s] %d after deterministic relevance + force-keep (cap=%d)",
             site.code, stats.deterministic_kept_count, MAX_FORCE_KEEP)

    if not canonicals:
        return stats, []

    # ---- STEP 7  Pass 1 LLM triage --------------------------------------
    if not config.openai_api_key:
        log.warning("[%s] OPENAI_API_KEY not set — stopping after deterministic stage", site.code)
        return stats, []

    openai_client = OpenAIClient(
        api_key=config.openai_api_key,
        triage_model=config.triage_model,
        deep_review_model=config.deep_review_model,
    )

    pass1_kept: list[tuple[CanonicalCandidate, Pass1Result]] = []
    for cand in canonicals:
        try:
            p1 = run_pass1(openai_client, cand)
            stats.pass1_cost_usd += p1.cost_usd_estimate
            keep, reason = enforce_pass1_keep_rules(
                cand, p1,
                keep_threshold=config.keep_threshold,
                high_priority_floor=config.high_priority_floor,
            )
            if keep:
                pass1_kept.append((cand, p1))
        except Exception as e:
            stats.errors.append(f"pass1 pmid={cand.pmid}: {e}")
            log.exception("[%s] pass1 failure", site.code)
    stats.pass1_kept_count = len(pass1_kept)
    log.info("[%s] %d after Pass 1 keep rules", site.code, stats.pass1_kept_count)

    # ---- STEP 8  Pass 2 LLM deep review ---------------------------------
    alerts: list[AlertOutput] = []
    for cand, p1 in pass1_kept:
        try:
            p2 = run_pass2(openai_client, cand, p1.parsed)
            stats.pass2_cost_usd += p2.cost_usd_estimate
            stats.pass2_run_count += 1

            grounded, unverified = verify_evidence_quotes(p2.parsed, cand.abstract)
            if grounded:
                stats.grounded_count += 1
            else:
                # Ungrounded quotes are flagged for editor attention but do NOT
                # change the tier. The editor reviews every alert before publish,
                # and is better placed than an algorithm to judge clinical validity.
                # The flag appears as a warning badge in the admin portal.
                log.debug("[%s] pmid=%s quotes unverified: %s",
                          site_code, cand.pmid, unverified)

            stats.alerts_by_tier[p2.final_tier_code] = stats.alerts_by_tier.get(p2.final_tier_code, 0) + 1
            if p2.final_tier_code in ("A", "B", "C"):
                alerts.append(AlertOutput(
                    candidate=cand, pass1=p1, pass2=p2,
                    grounded=grounded, unverified_quotes=unverified,
                ))
        except Exception as e:
            stats.errors.append(f"pass2 pmid={cand.pmid}: {e}")
            log.exception("[%s] pass2 failure", site.code)
    stats.alerts_created = len(alerts)
    log.info(
        "[%s] alerts: A=%d B=%d C=%d NOISE=%d (cost: pass1=$%.4f pass2=$%.4f)",
        site.code,
        stats.alerts_by_tier.get("A", 0),
        stats.alerts_by_tier.get("B", 0),
        stats.alerts_by_tier.get("C", 0),
        stats.alerts_by_tier.get("NOISE", 0),
        stats.pass1_cost_usd, stats.pass2_cost_usd,
    )

    # ---- STEP 9  persist (optional) -------------------------------------
    if persist:
        _persist(site_code, alerts, stats, config)

    return stats, alerts


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _retrieve(
    pubmed: PubMedClient,
    site: DiseaseSiteConfig,
    start: date,
    end: date,
    *,
    max_pmids: int,
    include_conferences: bool = True,
) -> list[PubMedRecord]:
    # Lane 1: main keyword-driven query
    main_q = site.build_main_query(start, end)
    main_pmids = pubmed.esearch(main_q, retmax=max_pmids)
    log.info("[%s] esearch (main): %d PMIDs", site.code, len(main_pmids))

    # Lane 2: journal force-include (whitelisted venues, site-narrowed)
    journal_q = site.build_journal_force_query(start, end)
    journal_pmids = pubmed.esearch(journal_q, retmax=max_pmids // 2)
    log.info("[%s] esearch (journal force-include): %d PMIDs", site.code, len(journal_pmids))

    # Lane 3: conference supplements (wider window around major meeting months)
    conf_records: list[PubMedRecord] = []
    if include_conferences:
        from .retrieval.conferences import retrieve_conference_records
        conf_records = retrieve_conference_records(
            pubmed, site,
            reference_date=end,
            lookback_days=35,
            max_pmids=max_pmids // 4,
        )
        log.info("[%s] conference lane: %d records", site.code, len(conf_records))

    # Merge: dedupe by PMID at the ID level before efetch
    all_pmids = list({p for p in (main_pmids + journal_pmids) if p})
    if not all_pmids and not conf_records:
        return []

    fetched = pubmed.efetch(all_pmids) if all_pmids else []

    # Combine fetched + conference records; downstream dedupe handles duplicates
    return fetched + conf_records


def _persist(
    site_code: str,
    alerts: list[AlertOutput],
    stats: RunStats,
    config: Config,
) -> None:
    from .persistence import SupabaseClient
    sb = SupabaseClient(url=config.supabase_url, service_role_key=config.supabase_service_role_key)
    run_id = sb.start_run("pubmed", site_code)
    try:
        for a in alerts:
            source_id, trial_id = sb.upsert_source_and_trial(a.candidate, raw_xml=a.candidate.raw_xml_hash)
            if not trial_id:
                # Fall back to a synthetic single-source "trial" record so the
                # alert FK constraint is satisfied; the editor will merge later
                # via the alias-resolution helper.
                synth = sb._client.table("trials").insert({
                    "canonical_name": a.candidate.title[:200],
                    "phase": None,
                    "disease_site_id": sb.get_disease_site_id(site_code),
                    "keywords": a.candidate.modality_keywords_present[:20],
                }).execute()
                trial_id = synth.data[0]["id"]

            sb.insert_alert(a.candidate, a.pass1, a.pass2, source_id, trial_id,
                            grounded=a.grounded, unverified_quotes=a.unverified_quotes)

        sb.finish_run(
            run_id,
            status="succeeded",
            candidates_found=stats.raw_count,
            candidates_passed_filter=stats.deterministic_kept_count,
            candidates_extracted=stats.pass2_run_count,
            alerts_created=stats.alerts_created,
        )
    except Exception as e:
        sb.finish_run(
            run_id,
            status="failed",
            candidates_found=stats.raw_count,
            candidates_passed_filter=stats.deterministic_kept_count,
            candidates_extracted=stats.pass2_run_count,
            alerts_created=stats.alerts_created,
            error_log=str(e),
        )
        raise
