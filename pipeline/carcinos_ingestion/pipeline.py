"""
Orchestrator — runs the full ingestion pipeline for a single disease site.

Architecture (revised — deterministic-first, LLM only for final extraction):

  Step 1.  Curated source ingestion
           - Lane 2a: Tier-1 guaranteed (NEJM/Lancet/JCO/JAMA) — never capped
           - Lane 2b: Broader journal whitelist per site
           - Lane 3:  Conference supplements (ASCO/ESMO/ASTRO/ASH/AACR/SGO/SITC)
           - Lane 4:  FDA oncology approvals (RSS, force-kept)

  Step 2.  Hard dedupe (PMID/DOI) → fuzzy (title sim ≥ 0.92)
           Cross-site PMID filter, 90-day publication date cutoff,
           English-only, abstract required

  Step 3.  Pubtype filter (drop editorials/letters/case reports)
           with journal-whitelist override

  Step 4.  Deterministic relevance score (0–100)
           → Canonicalise to CanonicalCandidate

  Step 5.  Signal scoring — ADMIT-ONLY architecture
           - Gate 1: Hard always-reject (mixture cure model, paraneoplastic, etc.)
           - Gate 2: Qualifying signal required — one of:
               FDA approval / label change / accelerated approval
               NCCN/ASCO/ESMO/ASTRO/ASH guideline update
               Phase III RCT (primary results)
               Randomized de-escalation / noninferiority trial
               Major conference LBA / plenary (ASCO, ESMO, ASTRO, ASH, AACR)
               Prospective trial directly changing RT dose/field/fractionation
               Phase II linked to regulatory action or new rare-disease standard
             Papers with no qualifying signal are rejected before Pass 2.
             Score, OS, PFS, journal name alone do NOT qualify a paper.
           - Gate 3: Additive score ranks qualifying candidates for TOP_N cap
           - Cap: top 20 qualifying candidates per site per run sent to LLM
           - Force-keep bypass: FDA records and top-tier journal whitelist papers
             carry QS_FORCE_KEEP and skip Gate 2

  Step 6.  Pass 2 LLM deep review (gpt-4o, strict JSON)
           - Classify tier (A/B/C/NOISE)
           - Summarise key findings, write "So what?"
           - Assess evidence strength and impact score
           - Provide 1-3 literal evidence quotes
           - Quote-grounding check + code-enforced tier mapping

  Step 7.  Persist to Supabase: alerts (status = EXTRACTED)
           → Awaits founder editor approval before PUBLISH

Design philosophy: CarcinoS should miss some low-value papers rather than
overwhelm users. Recall matters only for high-priority events. Precision,
trust, and speed are more important than completeness.

The LLM never decides what to search. It only summarises what the
deterministic pipeline already vetted.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

from .config import Config
from .disease_sites import get as get_site
from .disease_sites.base import DiseaseSiteConfig, TIER1_JOURNAL_WHITELIST, SITE_QUICK_TERMS
from .retrieval.pubmed import PubMedClient, PubMedRecord
from .filters.dedupe import dedupe
from .filters.pubtype import filter_by_pubtype
from .filters.relevance import score_relevance
from .filters.signal_score import (
    score_candidate, TOP_N_PER_SITE, SignalScore,
    QS_NONE, QS_FORCE_KEEP,
)
from .normalize.canonical import to_canonical, CanonicalCandidate
from .triage.openai_client import OpenAIClient
from .triage.pass1 import Pass1Result
from .triage.pass2 import run_pass2, verify_evidence_quotes, Pass2Result

log = logging.getLogger("carcinos.pipeline")

# Max concurrent Pass 2 LLM calls per site
_LLM_WORKERS = 8


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
    signal_kept_count: int = 0                # candidates forwarded to Pass 2
    signal_excluded_count: int = 0            # Gate 1 hard-excluded
    signal_no_qualifying_signal_count: int = 0  # Gate 2 — no qualifying signal
    pass2_run_count: int = 0
    grounded_count: int = 0
    alerts_created: int = 0
    alerts_by_tier: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0, "NOISE": 0})
    pass2_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AlertOutput:
    """In-memory alert handed back to callers (persistence writes to alerts table)."""
    candidate: CanonicalCandidate
    pass1: Pass1Result        # synthetic Pass1Result built from signal score
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
    include_fda: bool = True,
    seen_pmids: set[str] | None = None,
) -> tuple[RunStats, list[AlertOutput]]:
    """
    Run the full pipeline for a single disease site.

    Returns (RunStats, list[AlertOutput]). Alerts are NOT persisted unless
    persist=True, in which case they are written to Supabase as EXTRACTED rows
    for the founder editor to review.
    """
    site = get_site(site_code)
    if end is None:
        end = date.today()
    from datetime import timedelta
    start = end - timedelta(days=days)

    stats = RunStats(
        site_code=site.code, site_name=site.name,
        window_start=start.isoformat(), window_end=end.isoformat(),
    )

    log.info("[%s] Running pipeline for %s..%s", site.code, start, end)

    # ---- STEP 1  retrieval -------------------------------------------------
    pubmed = PubMedClient(email=config.ncbi_email, api_key=config.ncbi_api_key)
    records = _retrieve(
        pubmed, site, start, end,
        max_pmids=config.max_pmids_per_query,
        include_conferences=include_conferences,
        include_fda=include_fda,
        lookback_days=days,
    )
    stats.raw_count = len(records)
    log.info("[%s] retrieved %d records total", site.code, stats.raw_count)

    # ---- STEP 2  dedupe + pre-filters -------------------------------------
    records = dedupe(records)
    stats.deduped_count = len(records)
    log.info("[%s] %d after dedupe", site.code, stats.deduped_count)

    # Cross-site PMID filter — drop PMIDs already processed by another site
    if seen_pmids:
        before = len(records)
        records = [r for r in records if r.pmid not in seen_pmids]
        dropped = before - len(records)
        if dropped:
            log.info("[%s] %d cross-site duplicates removed", site.code, dropped)

    # Publication date floor — [Date - Entrez] can surface late-indexed older
    # papers (PubMed indexing lag is typically 1-4 weeks). We allow a 30-day
    # grace period beyond the run window, but nothing older than that.
    # This prevents papers from 1-2 months ago from appearing in weekly runs.
    from datetime import timedelta
    cutoff = end - timedelta(days=30)

    def _pub_date_ok(r: PubMedRecord) -> bool:
        pd = r.pub_date or ""
        if not pd:
            return True
        try:
            parts = pd[:10].split("-")
            y = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 1
            d = int(parts[2]) if len(parts) > 2 else 1
            return date(y, m, d) >= cutoff
        except Exception:
            return True

    before_date = len(records)
    records = [r for r in records if _pub_date_ok(r)]
    dropped_old = before_date - len(records)
    if dropped_old:
        log.info("[%s] %d old papers removed (published before %s)",
                 site.code, dropped_old, cutoff.isoformat())

    # English-only
    records = [r for r in records if (r.language or "eng").lower() in ("eng", "english", "")]

    # Abstract required — except force-keep journals and FDA records
    whitelist = list(site.journal_whitelist())
    records_with_abstract = [r for r in records if r.abstract]
    records_no_abstract_ok = [
        r for r in records
        if not r.abstract and (
            r.matches_journal_whitelist(whitelist)
            or r.conference_source == "FDA"
        )
    ]
    records = records_with_abstract + records_no_abstract_ok
    log.info("[%s] %d after English + abstract filters", site.code, len(records))

    # ---- STEP 3  pubtype filter -------------------------------------------
    pubtyped = filter_by_pubtype(records, journal_force_keep=whitelist)
    stats.pubtype_kept_count = len(pubtyped)
    log.info("[%s] %d after pubtype filter", site.code, stats.pubtype_kept_count)

    # ---- STEP 4  relevance scoring + canonicalise -------------------------
    canonicals: list[CanonicalCandidate] = []

    for r, pubtype_decision in pubtyped:
        rel = score_relevance(
            r, site,
            keep_threshold=config.keep_threshold,
            low_confidence_floor=config.high_priority_floor,
        )

        force_keep_reason = None

        # Only FDA oncology approval records are force-kept.
        # The FDA RSS filter already pre-qualified them as oncology approvals,
        # so they bypass Gate 2 (the FDA record IS the qualifying signal).
        # All other records — including top-tier journals — go through Gates
        # 1 and 2. Journal prestige does not exempt a paper from qualifying
        # signal detection. A meta-analysis in NEJM is still a meta-analysis.
        if r.conference_source == "FDA":
            force_keep_reason = "fda_approval"

        if not rel.keep and not force_keep_reason:
            continue

        canonicals.append(to_canonical(r, site, pubtype_decision, rel, force_keep_reason))

    stats.deterministic_kept_count = len(canonicals)
    log.info("[%s] %d after deterministic relevance + force-keep (cap=%d)",
             site.code, stats.deterministic_kept_count, MAX_FORCE_KEEP)

    if not canonicals:
        return stats, []

    # ---- STEP 5  Signal scoring (replaces Pass 1 LLM) --------------------
    #
    # Force-keep candidates (FDA, top-tier journal whitelist) bypass scoring
    # and go straight to Pass 2 with a perfect score. Everything else is
    # evaluated against the signal rubric and must clear SIGNAL_THRESHOLD.
    _stats_lock = threading.Lock()

    signal_kept: list[tuple[CanonicalCandidate, SignalScore]] = []

    for cand in canonicals:
        if cand.force_keep_reason:
            # Pre-qualified by source (FDA approval RSS, top-tier journal whitelist).
            # These bypass Gate 2 entirely — their qualifying signal is the source.
            signal_kept.append((
                cand,
                SignalScore(
                    qualifying_signal=QS_FORCE_KEEP,
                    score=100,
                    signals=["force_keep"],
                    has_trigger=True,
                ),
            ))
            continue

        sig = score_candidate(cand)

        if sig.hard_excluded:
            stats.signal_excluded_count += 1
            log.debug(
                "[%s] hard-exclude pmid=%s: %s",
                site.code, cand.pmid, sig.exclusion_reason,
            )
            continue

        if sig.qualifying_signal == QS_NONE:
            stats.signal_no_qualifying_signal_count += 1
            log.debug(
                "[%s] no qualifying signal pmid=%s reason=%s",
                site.code, cand.pmid, sig.rejection_reason,
            )
            continue

        signal_kept.append((cand, sig))

    # Sort by score descending — highest-signal items go first into Pass 2.
    # If we hit TOP_N_PER_SITE, drop the lowest-scoring qualifying candidates
    # (cost-control only; they still had a qualifying signal).
    signal_kept.sort(key=lambda x: x[1].score, reverse=True)

    if len(signal_kept) > TOP_N_PER_SITE:
        log.info(
            "[%s] capping at top %d for LLM (from %d qualifying candidates)",
            site.code, TOP_N_PER_SITE, len(signal_kept),
        )
        signal_kept = signal_kept[:TOP_N_PER_SITE]

    stats.signal_kept_count = len(signal_kept)
    log.info(
        "[%s] %d → Pass 2 (hard-excluded=%d no-qualifying-signal=%d)",
        site.code,
        stats.signal_kept_count,
        stats.signal_excluded_count,
        stats.signal_no_qualifying_signal_count,
    )

    if not signal_kept:
        return stats, []

    if not config.openai_api_key:
        log.warning(
            "[%s] OPENAI_API_KEY not set — stopping after signal scoring", site.code
        )
        return stats, []

    openai_client = OpenAIClient(
        api_key=config.openai_api_key,
        triage_model=config.triage_model,
        deep_review_model=config.deep_review_model,
    )

    # ---- STEP 6  Pass 2 LLM deep review — parallel -----------------------

    alerts: list[AlertOutput] = []
    alerts_lock = threading.Lock()

    def _do_pass2(cand: CanonicalCandidate, sig: SignalScore):
        # Build a pass1-compatible context dict from the signal score so that
        # Pass 2's prompt has a relevance prior even without an LLM Pass 1.
        priority = (
            "high"   if sig.score >= 45 else
            "medium" if sig.score >= 25 else
            "low"
        )
        p1_context = {
            "keep": True,
            "relevance_score": sig.score,
            "priority_hint": priority,
            "one_line_rationale": (
                f"qualifying_signal={sig.qualifying_signal}; "
                + "; ".join(sig.signals)
            ) if sig.signals else f"qualifying_signal={sig.qualifying_signal}",
            "drop_reason": None,
        }
        p2 = run_pass2(openai_client, cand, p1_context)
        grounded, unverified = verify_evidence_quotes(p2.parsed, cand.abstract)

        # Wrap the signal score in a Pass1Result for backward-compat with
        # AlertOutput and the persistence layer.
        synthetic_p1 = Pass1Result(
            parsed=p1_context,
            keep=True,
            relevance_score=sig.score,
            priority_hint=priority,
            drop_reason=None,
            cost_usd_estimate=0.0,
        )
        return cand, synthetic_p1, p2, grounded, unverified

    with ThreadPoolExecutor(max_workers=_LLM_WORKERS) as pool:
        futures2 = {
            pool.submit(_do_pass2, c, s): (c, s)
            for c, s in signal_kept
        }
        for fut in as_completed(futures2):
            try:
                cand, p1, p2, grounded, unverified = fut.result()
                with _stats_lock:
                    stats.pass2_cost_usd += p2.cost_usd_estimate
                    stats.pass2_run_count += 1
                    if grounded:
                        stats.grounded_count += 1
                    stats.alerts_by_tier[p2.final_tier_code] = (
                        stats.alerts_by_tier.get(p2.final_tier_code, 0) + 1
                    )
                if p2.final_tier_code in ("A", "B", "C"):
                    with alerts_lock:
                        alerts.append(AlertOutput(
                            candidate=cand,
                            pass1=p1,
                            pass2=p2,
                            grounded=grounded,
                            unverified_quotes=unverified,
                        ))
            except Exception as e:
                cand, _ = futures2[fut]
                stats.errors.append(f"pass2 pmid={cand.pmid}: {e}")
                log.exception("[%s] pass2 failure pmid=%s", site.code, cand.pmid)

    stats.alerts_created = len(alerts)
    log.info(
        "[%s] alerts: A=%d B=%d C=%d NOISE=%d (cost: pass2=$%.4f)",
        site.code,
        stats.alerts_by_tier.get("A", 0),
        stats.alerts_by_tier.get("B", 0),
        stats.alerts_by_tier.get("C", 0),
        stats.alerts_by_tier.get("NOISE", 0),
        stats.pass2_cost_usd,
    )

    # ---- STEP 7  persist (optional) --------------------------------------
    if persist:
        _persist(site_code, alerts, stats, config)

    return stats, alerts


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _retrieve(
    pubmed: PubMedClient,
    site: DiseaseSiteConfig,
    start: date,
    end: date,
    *,
    max_pmids: int,
    include_conferences: bool = True,
    include_fda: bool = True,
    lookback_days: int = 7,
) -> list[PubMedRecord]:
    """
    Pull records from all active ingestion lanes and return a merged list.
    Downstream dedupe handles any cross-lane duplicates.
    """
    from .disease_sites.base import TIER1_JOURNAL_WHITELIST
    from .disease_sites.base import _journal_block, _date_block

    # Lane 1 (broad keyword search) is intentionally DISABLED.
    # Broad PubMed keyword queries return too much low-value material.
    # All retrieval goes through curated journal/source lanes below.

    # Lane 2a: Tier-1 guaranteed (NEJM / Lancet / JCO / JAMA) — never capped
    tier1_q = " AND ".join([
        site.core_block(),
        _journal_block(TIER1_JOURNAL_WHITELIST),
        _date_block(start, end),
    ])
    tier1_pmids = pubmed.esearch(tier1_q, retmax=max_pmids)
    log.info("[%s] esearch (tier-1 guaranteed): %d PMIDs", site.code, len(tier1_pmids))

    # Lane 2b: broader curated journal whitelist (rest of site + shared list)
    journal_q = site.build_journal_force_query(start, end)
    journal_pmids = pubmed.esearch(journal_q, retmax=max_pmids // 2)
    log.info("[%s] esearch (journal whitelist): %d PMIDs", site.code, len(journal_pmids))

    # Lane 3: conference supplement abstracts
    conf_records: list[PubMedRecord] = []
    if include_conferences:
        from .retrieval.conferences import retrieve_conference_records
        conf_records = retrieve_conference_records(
            pubmed, site,
            reference_date=end,
            lookback_days=35,
            max_pmids=max_pmids // 3,
        )
        log.info("[%s] conference lane: %d records", site.code, len(conf_records))

    # Merge PubMed PMIDs, dedupe at ID level before efetch
    all_pmids = list({p for p in (tier1_pmids + journal_pmids) if p})
    fetched = pubmed.efetch(all_pmids) if all_pmids else []

    # Lane 4: FDA oncology approvals (RSS)
    fda_records: list[PubMedRecord] = []
    if include_fda:
        from .retrieval.fda import retrieve_fda_records
        all_fda = retrieve_fda_records(lookback_days=lookback_days, reference_date=end)

        # Route FDA records to only the sites they're relevant to using
        # simple substring matching on title + summary vs. site quick terms.
        site_terms = [t.lower() for t in SITE_QUICK_TERMS.get(site.code, [])]
        for r in all_fda:
            if not site_terms:
                fda_records.append(r)
            else:
                text = f"{r.title} {r.abstract}".lower()
                if any(t in text for t in site_terms):
                    fda_records.append(r)

        log.info(
            "[%s] FDA lane: %d relevant records (of %d total FDA items)",
            site.code, len(fda_records), len(all_fda),
        )

    return fetched + conf_records + fda_records


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

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
            source_id, trial_id = sb.upsert_source_and_trial(
                a.candidate, raw_xml=a.candidate.raw_xml_hash
            )
            if not trial_id:
                synth = sb._client.table("trials").insert({
                    "canonical_name": a.candidate.title[:200],
                    "phase": None,
                    "disease_site_id": sb.get_disease_site_id(site_code),
                    "keywords": a.candidate.modality_keywords_present[:20],
                }).execute()
                trial_id = synth.data[0]["id"]

            sb.insert_alert(
                a.candidate, a.pass1, a.pass2, source_id, trial_id,
                grounded=a.grounded,
                unverified_quotes=a.unverified_quotes,
            )

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
