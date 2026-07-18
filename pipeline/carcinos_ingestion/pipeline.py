"""
Orchestrator — runs the full ingestion pipeline for a single disease site.

Architecture (revised — deterministic-first, LLM only for final extraction):

  Step 1.  Curated source ingestion
           - Lane 2a: Tier-1 guaranteed (NEJM/Lancet/JCO/JAMA) — never capped
           - Lane 2b: Broader journal whitelist per site
           - Lane 3:  Conference supplements (ASCO/ESMO/ASTRO/ASH/AACR/SGO/SITC)
           - Lane 4:  FDA oncology approvals (RSS, force-kept)
           - Lane 5:  GPT-4o web search (ASCO abstract pages, JCO online-first,
                      FDA.gov approvals not yet in PubMed) — merged before Gate 1

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
    score_candidate, SignalScore,
    QS_NONE, QS_FORCE_KEEP,
    _journal_is_top_tier,
)
from .normalize.canonical import to_canonical, CanonicalCandidate
from .triage.openai_client import OpenAIClient
from .triage.pass1 import Pass1Result, run_pass1, enforce_pass1_keep_rules
from .triage.pass2 import run_pass2, verify_evidence_quotes, Pass2Result
from .triage.context_brief import generate_context_brief
from .retrieval.web_search import run_web_search_lane

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
    context_brief_cost_usd: float = 0.0
    context_brief_trials: list[str] = field(default_factory=list)  # LLM-generated additions
    web_search_cost_usd: float = 0.0
    web_search_count: int = 0       # papers surfaced by Lane 5

    # ── Lane 6 — hybrid news monitoring ──────────────────────────────────────
    news_primary_count: int = 0          # primary feed records (journal early-access + society)
    news_secondary_signals: int = 0      # trial names extracted from secondary (trade press) feeds
    news_secondary_trial_names: list[str] = field(default_factory=list)  # the actual names

    # ── LLM-first / three-way routing attrition ──────────────────────────────
    # When Gate 2 rejects an item (no qualifying signal), it enters a three-stage
    # path: relevance gate → Pass 1 mini-triage → promote / quarantine / reject.
    qs_none_count: int = 0                       # passed Gate 1 but no qualifying signal
    qs_none_by_reason: dict[str, int] = field(default_factory=dict)
    qs_none_top_journal_count: int = 0           # QS_NONE papers from a Tier-1 journal

    # Stage 1: relevance gate (deterministic, before any LLM)
    qs_none_below_relevance_floor: int = 0       # hard-rejected: score < qs_none_min_relevance

    # Stage 2: Pass 1 mini-triage
    qs_none_sent_to_minitriage: int = 0          # items that reached Pass 1
    qs_none_minitriage_rejected: int = 0         # Pass 1 said drop / low score
    qs_none_quarantine_count: int = 0            # uncertain → QUARANTINE_REVIEW
    qs_none_promoted_to_pass2: int = 0           # promoted to Pass 2 (triage model)

    # Stage 3: Pass 2 outcomes for promoted items
    qs_none_sent_to_llm: int = 0                 # alias for promoted_to_pass2 (backward compat)
    qs_none_recovered_count: int = 0             # promoted items the LLM tiered A/B/C
    qs_none_recovered_by_tier: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0})
    qs_none_recovered: list[dict] = field(default_factory=list)  # [{pmid, journal, tier, reason}]

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


@dataclass
class QuarantineOutput:
    """
    An oncology-relevant item that failed Gate 2 (no qualifying signal) but
    passed the relevance floor and was judged uncertain — not clearly noise,
    not clearly a card — by the Pass 1 mini-triage.

    Persisted to Supabase with status=QUARANTINE_REVIEW for admin inspection.
    Never shown as a weekly digest card without human promotion.

    Routing:
      deterministic_relevance_score >= qs_none_min_relevance (40)   → enters mini-triage
      Pass 1 score in [qs_none_quarantine_threshold, promote_threshold) → this bucket
    """
    candidate: CanonicalCandidate
    pass1: Pass1Result
    rejection_reason: str          # why Gate 2 rejected it
    quarantine_reason: str         # plain-language explanation from Pass 1


def run_site(
    site_code: str,
    *,
    config: Config,
    days: int = 7,
    persist: bool = False,
    end: Optional[date] = None,
    include_conferences: bool = True,
    include_fda: bool = True,
    include_web_search: bool = True,
    seen_pmids: set[str] | None = None,
    llm_first: bool = True,
    qs_none_cap: int = 20,
) -> tuple[RunStats, list[AlertOutput], list[QuarantineOutput]]:
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

    # ---- STEP 0  Pre-retrieval LLM context brief ---------------------------
    #
    # Ask gpt-4o-mini: "Given today's date and this disease site, what specific
    # trials or FDA decisions should we search for right now?" The response
    # augments the site's curated watched_trials list so the QS_WATCHED_TRIAL
    # gate catches high-priority papers that wouldn't otherwise trigger a signal.
    #
    # Cost: ~$0.001-0.002 per site (one gpt-4o-mini call, ~800 tokens total).
    # Failure mode: silently returns [] so retrieval proceeds unaffected.
    effective_watched_trials = list(site.watched_trials)

    if config.openai_api_key:
        _brief_client = OpenAIClient(
            api_key=config.openai_api_key,
            triage_model=config.triage_model,
            deep_review_model=config.deep_review_model,
        )
        brief_trials, brief_cost = generate_context_brief(
            _brief_client,
            site_name=site.name,
            site_code=site.code,
            existing_trials=effective_watched_trials,
            today=end,
        )
        effective_watched_trials.extend(brief_trials)
        stats.context_brief_trials = brief_trials
        stats.context_brief_cost_usd = brief_cost
    else:
        log.debug("[%s] No OpenAI key — skipping context brief", site.code)

    # ---- STEP 1  retrieval -------------------------------------------------
    pubmed = PubMedClient(email=config.ncbi_email, api_key=config.ncbi_api_key)
    records = _retrieve(
        pubmed, site, start, end,
        max_pmids=config.max_pmids_per_query,
        include_conferences=include_conferences,
        include_fda=include_fda,
        lookback_days=days,
        openai_api_key=config.openai_api_key,
    )

    # ---- LANE 5: GPT-4o web search (runs after PubMed, merged before Gate 1) ─
    # Surfaces papers from ASCO/ESMO abstract pages, JCO online-first, and
    # FDA.gov that haven't been indexed in PubMed within the 24-48h lag window.
    # Results are injected into the record pool and flow through the identical
    # Gate 1 → Gate 2 → Pass 2 pipeline. Title-based dedup prevents doubles.
    if include_web_search and config.openai_api_key:
        ws_records, ws_cost = run_web_search_lane(
            config.openai_api_key,
            site=site,
            watched_trials=effective_watched_trials,
            today=end,
            model=config.triage_model,   # light/cheap model for the browsing lane
        )
        if ws_records:
            log.info(
                "[%s] Lane 5 web search: %d papers found (cost ~$%.3f)",
                site.code, len(ws_records), ws_cost,
            )
            records.extend(ws_records)
            stats.web_search_count = len(ws_records)
        stats.web_search_cost_usd = ws_cost
    elif include_web_search and not config.openai_api_key:
        log.debug("[%s] Lane 5 skipped — no OPENAI_API_KEY", site.code)

    # ---- LANE 6: Hybrid news monitoring -----------------------------------
    # Primary feeds (journal early-access + society news) produce PubMedRecord
    # objects that flow through the normal gate system and can become cards.
    # Secondary feeds (trade press) extract trial names only — these are injected
    # into effective_watched_trials so that matching PubMed/conference records
    # score QS_WATCHED_TRIAL and surface through the evidence pipeline.
    # Secondary sources NEVER directly create cards.
    if config.include_news_lane:
        from .retrieval.news import run_news_lane
        news_primary, news_secondary_names = run_news_lane(
            lookback_days=days,
            reference_date=end,
            enrich_abstracts=config.news_enrich_abstracts,
            openai_api_key=config.openai_api_key,
            llm_model=config.triage_model,
        )
        if news_primary:
            log.info(
                "[%s] Lane 6 primary: %d records (journal early-access + society)",
                site.code, len(news_primary),
            )
            records.extend(news_primary)
            stats.news_primary_count = len(news_primary)
        if news_secondary_names:
            new_names = [n for n in news_secondary_names if n not in effective_watched_trials]
            effective_watched_trials.extend(new_names)
            stats.news_secondary_signals = len(news_secondary_names)
            stats.news_secondary_trial_names = news_secondary_names
            log.info(
                "[%s] Lane 6 secondary: %d trial signal(s) added to watched list: %s",
                site.code, len(new_names), new_names,
            )

    stats.raw_count = len(records)
    log.info("[%s] retrieved %d records total (incl. web search)", site.code, stats.raw_count)

    # ---- STEP 2  dedupe + pre-filters -------------------------------------
    records = dedupe(records)
    stats.deduped_count = len(records)
    log.info("[%s] %d after dedupe", site.code, stats.deduped_count)

    # Cross-site dedup — drop records already processed by another site.
    # Primary key: PMID. Fallback for empty-PMID records (FDA, web-search, news):
    # normalize the title and use a "title:<hash>" sentinel so the same article
    # fetched under two different disease sites is only processed by the first.
    if seen_pmids is not None:
        def _title_sentinel(r) -> str | None:
            """Return a title-based sentinel key for records with no PMID."""
            t = (r.title or "").lower().split()
            if not t:
                return None
            normalized = " ".join(t)[:200]
            return f"title:{normalized}"

        before = len(records)
        filtered: list = []
        for r in records:
            if r.pmid:
                if r.pmid in seen_pmids:
                    continue
            else:
                sentinel = _title_sentinel(r)
                if sentinel and sentinel in seen_pmids:
                    continue
            filtered.append(r)

        records = filtered
        dropped = before - len(records)
        if dropped:
            log.info("[%s] %d cross-site duplicates removed", site.code, dropped)

        # Register all identifiers from records this site will process.
        # PMID-less records register by title sentinel so subsequent sites skip them.
        for r in records:
            if r.pmid:
                seen_pmids.add(r.pmid)
            else:
                sentinel = _title_sentinel(r)
                if sentinel:
                    seen_pmids.add(sentinel)

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
    whitelist = list(site.journal_whitelist())

    for r, pubtype_decision in pubtyped:
        force_keep_reason = None

        if r.conference_source == "FDA":
            # FDA oncology approval records are pre-qualified by source.
            # They bypass F3 relevance scoring and Gate 2 signal scoring.
            # The FDA RSS filter IS the qualifying signal.
            force_keep_reason = "fda_approval"

        # Journal whitelist bypass — papers retrieved via the curated journal
        # lanes (Tier 1: NEJM/Lancet/JCO/JAMA, or Lane 2b: site whitelist)
        # already passed a cancer-site keyword filter as part of the PubMed
        # query that fetched them. Running F3 on top is double-gating and
        # silently drops legitimate papers that score 25–64.
        # These papers still go through Gate 1 (hard excludes) and Gate 2
        # (qualifying signal) — journal prestige does not bypass signal scoring.
        if r.matches_journal_whitelist(whitelist) or r.conference_source not in (None, ""):
            rel_bypass = True
        else:
            rel_bypass = False

        if rel_bypass or force_keep_reason:
            # Give a synthetic relevance result so downstream code that reads
            # rel.score / rel.low_confidence still works correctly.
            from .filters.relevance import RelevanceResult
            rel = RelevanceResult(score=70, keep=True, low_confidence=False,
                                  rationale=["journal_whitelist_bypass"])
        else:
            rel = score_relevance(
                r, site,
                keep_threshold=config.keep_threshold,
                low_confidence_floor=config.high_priority_floor,
            )
            if not rel.keep:
                continue

        canonicals.append(to_canonical(r, site, pubtype_decision, rel, force_keep_reason))

    stats.deterministic_kept_count = len(canonicals)
    log.info("[%s] %d after deterministic relevance + FDA force-keep",
             site.code, stats.deterministic_kept_count)

    if not canonicals:
        return stats, [], []

    # ---- STEP 5  Signal scoring (replaces Pass 1 LLM) --------------------
    #
    # Force-keep candidates (FDA, top-tier journal whitelist) bypass scoring
    # and go straight to Pass 2 with a perfect score. Everything else is
    # evaluated against the signal rubric and must clear SIGNAL_THRESHOLD.
    _stats_lock = threading.Lock()

    # Papers carrying a qualifying signal — always forwarded to Pass 2 (uncapped).
    signal_kept: list[tuple[CanonicalCandidate, SignalScore]] = []
    # Papers that passed Gate 1 but carry NO qualifying signal. Under LLM-first
    # these are no longer dropped at the gate — the qualifying signal becomes a
    # ranking boost, not an entry requirement. They are ranked (top-journal
    # first, then deterministic relevance), capped per site to bound cost/noise,
    # and forwarded to Pass 2 on the cheaper model. The LLM decides their tier.
    no_signal: list[tuple[CanonicalCandidate, SignalScore]] = []

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

        sig = score_candidate(cand, watched_trials=frozenset(effective_watched_trials))

        if sig.hard_excluded:
            # Gate 1 stays a hard reject. These are patterns structurally unable
            # to be practice-changing (mixture cure model, narrative review,
            # surgical-technique comparison) — cheap, high-precision, kept as-is.
            stats.signal_excluded_count += 1
            log.debug(
                "[%s] hard-exclude pmid=%s: %s",
                site.code, cand.pmid, sig.exclusion_reason,
            )
            continue

        if sig.qualifying_signal == QS_NONE:
            # Instrument what the gate would have discarded.
            stats.qs_none_count += 1
            reason = sig.rejection_reason or "no_qualifying_signal"
            stats.qs_none_by_reason[reason] = stats.qs_none_by_reason.get(reason, 0) + 1
            if _journal_is_top_tier(cand.journal or ""):
                stats.qs_none_top_journal_count += 1

            if llm_first:
                no_signal.append((cand, sig))
            else:
                # Legacy admit-only behavior — drop at the gate (for A/B comparison).
                log.debug(
                    "[%s] no qualifying signal pmid=%s reason=%s (dropped; llm_first off)",
                    site.code, cand.pmid, reason,
                )
            continue

        signal_kept.append((cand, sig))

    # Rank qualifying papers by additive score — highest-signal processed first.
    # No cap on qualifying papers: a heavy conference week may legitimately
    # produce 25+ worthy papers and we must not silently drop them.
    signal_kept.sort(key=lambda x: x[1].score, reverse=True)
    stats.signal_kept_count = len(signal_kept)
    # Keep the legacy stat name populated for any downstream dashboard.
    stats.signal_no_qualifying_signal_count = stats.qs_none_count

    # Rank the no-signal tier: top-tier journal first, then deterministic relevance.
    # Cap removed — Lane 5/6 records route through qs_none as their primary path
    # and an arbitrary count cap silently drops LLM-curated web search results.
    # Cost is bounded by the relevance floor (Stage 1) and the cheap triage model.
    if no_signal:
        no_signal.sort(
            key=lambda x: (
                _journal_is_top_tier(x[0].journal or ""),
                x[0].deterministic_relevance_score,
            ),
            reverse=True,
        )

    if not signal_kept and not no_signal:
        return stats, [], []

    if not config.openai_api_key:
        log.warning(
            "[%s] OPENAI_API_KEY not set — stopping after signal scoring", site.code
        )
        return stats, [], []

    # Reuse the OpenAI client built in Step 0 (early return above guarantees
    # that _brief_client exists whenever we reach this line).
    openai_client = _brief_client

    # ---- STEP 5b  Three-way routing for QS_NONE items ----------------------
    #
    # Items that failed Gate 2 (no qualifying signal) go through a three-stage
    # funnel before reaching Pass 2:
    #
    #   Stage 1 — Relevance gate (deterministic, free):
    #     deterministic_relevance_score < qs_none_min_relevance → HARD REJECT
    #     Never reaches the LLM. Eliminates obvious junk cheaply.
    #
    #   Stage 2 — Pass 1 mini-triage (LLM, triage model, sequential):
    #     Pass 1 score >= qs_none_promote_threshold (65) → PROMOTE to Pass 2
    #     Pass 1 score >= qs_none_quarantine_threshold (45) + keep=True → QUARANTINE_REVIEW
    #     Otherwise → REJECT
    #
    #   Stage 3 — Pass 2 (deep review, triage model):
    #     Only promoted items reach here. Normal tier assignment (A/B/C/NOISE).
    #
    quarantine_items: list[QuarantineOutput] = []
    mini_triaged_for_pass2: list[tuple[CanonicalCandidate, SignalScore]] = []

    if no_signal:
        # Stage 1: relevance gate — hard reject below floor before any LLM call
        gated: list[tuple[CanonicalCandidate, SignalScore]] = []
        for cand, sig in no_signal:
            rel_score = cand.deterministic_relevance_score
            if rel_score < config.qs_none_min_relevance:
                stats.qs_none_below_relevance_floor += 1
                log.debug(
                    "[%s] qs_none relevance gate REJECT pmid=%s rel=%d < floor=%d",
                    site.code, cand.pmid, rel_score, config.qs_none_min_relevance,
                )
            else:
                gated.append((cand, sig))

        log.info(
            "[%s] qs_none relevance gate: %d passed, %d hard-rejected (floor=%d)",
            site.code, len(gated),
            stats.qs_none_below_relevance_floor,
            config.qs_none_min_relevance,
        )

        # Stage 2: Pass 1 mini-triage — three-way route
        stats.qs_none_sent_to_minitriage = len(gated)
        if gated:
            log.info(
                "[%s] qs_none mini-triage: running Pass 1 on %d items",
                site.code, len(gated),
            )
            for cand, sig in gated:
                try:
                    p1 = run_pass1(openai_client, cand)
                    final_keep, keep_reason = enforce_pass1_keep_rules(cand, p1)

                    p1_score = p1.relevance_score

                    if p1_score >= config.qs_none_promote_threshold and final_keep:
                        # Promote to Pass 2
                        mini_triaged_for_pass2.append((cand, sig))
                        stats.qs_none_promoted_to_pass2 += 1
                        log.debug(
                            "[%s] qs_none mini-triage PROMOTE pmid=%s score=%d",
                            site.code, cand.pmid, p1_score,
                        )
                    elif p1_score >= config.qs_none_quarantine_threshold and final_keep:
                        # Quarantine — uncertain, not clearly noise
                        gate_reason = sig.rejection_reason or "no_qualifying_signal"
                        quarantine_items.append(QuarantineOutput(
                            candidate=cand,
                            pass1=p1,
                            rejection_reason=gate_reason,
                            quarantine_reason=(
                                p1.parsed.get("one_line_rationale", "")
                                or (f"Pass 1 score {p1_score} in quarantine band "
                                    f"[{config.qs_none_quarantine_threshold}, "
                                    f"{config.qs_none_promote_threshold})")
                            ),
                        ))
                        stats.qs_none_quarantine_count += 1
                        log.debug(
                            "[%s] qs_none mini-triage QUARANTINE pmid=%s score=%d",
                            site.code, cand.pmid, p1_score,
                        )
                    else:
                        stats.qs_none_minitriage_rejected += 1
                        log.debug(
                            "[%s] qs_none mini-triage REJECT pmid=%s score=%d keep=%s",
                            site.code, cand.pmid, p1_score, p1.keep,
                        )
                except Exception as e:
                    stats.errors.append(f"pass1 mini-triage pmid={cand.pmid}: {e}")
                    log.exception(
                        "[%s] pass1 mini-triage failure pmid=%s",
                        site.code, cand.pmid,
                    )

        # Keep the alias in sync (backward compat for dashboards reading this field)
        stats.qs_none_sent_to_llm = stats.qs_none_promoted_to_pass2

        log.info(
            "[%s] qs_none mini-triage complete: promoted=%d quarantine=%d rejected=%d",
            site.code,
            stats.qs_none_promoted_to_pass2,
            stats.qs_none_quarantine_count,
            stats.qs_none_minitriage_rejected,
        )

    log.info(
        "[%s] Pass 2 intake: %d qualifying + %d promoted-qs-none (cap=%s) | "
        "hard-excluded=%d qs_none_total=%d (below_floor=%d quarantine=%d top_journal=%d)",
        site.code,
        stats.signal_kept_count,
        stats.qs_none_promoted_to_pass2,
        qs_none_cap,
        stats.signal_excluded_count,
        stats.qs_none_count,
        stats.qs_none_below_relevance_floor,
        stats.qs_none_quarantine_count,
        stats.qs_none_top_journal_count,
    )

    # ---- STEP 6  Pass 2 LLM deep review — parallel -----------------------

    alerts: list[AlertOutput] = []
    alerts_lock = threading.Lock()

    def _do_pass2(cand: CanonicalCandidate, sig: SignalScore, model: str, is_no_signal: bool):
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
        p2 = run_pass2(
            openai_client, cand, p1_context,
            qualifying_signal=sig.qualifying_signal, model=model,
        )
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
        return cand, sig, synthetic_p1, p2, grounded, unverified, is_no_signal

    # Build the Pass 2 work list. Qualifying papers run on the deep-review model;
    # promoted QS_NONE items run on the cheaper triage model to bound cost.
    work: list[tuple[CanonicalCandidate, SignalScore, str, bool]] = [
        (c, s, config.deep_review_model, False) for c, s in signal_kept
    ] + [
        (c, s, config.triage_model, True) for c, s in mini_triaged_for_pass2
    ]

    with ThreadPoolExecutor(max_workers=_LLM_WORKERS) as pool:
        futures2 = {
            pool.submit(_do_pass2, c, s, model, is_ns): (c, s, model, is_ns)
            for c, s, model, is_ns in work
        }
        for fut in as_completed(futures2):
            try:
                cand, sig, p1, p2, grounded, unverified, is_no_signal = fut.result()
                with _stats_lock:
                    stats.pass2_cost_usd += p2.cost_usd_estimate
                    stats.pass2_run_count += 1
                    if grounded:
                        stats.grounded_count += 1
                    stats.alerts_by_tier[p2.final_tier_code] = (
                        stats.alerts_by_tier.get(p2.final_tier_code, 0) + 1
                    )
                    # Track papers the gate would have discarded but the LLM tiered.
                    if is_no_signal and p2.final_tier_code in ("A", "B", "C"):
                        stats.qs_none_recovered_count += 1
                        stats.qs_none_recovered_by_tier[p2.final_tier_code] = (
                            stats.qs_none_recovered_by_tier.get(p2.final_tier_code, 0) + 1
                        )
                        stats.qs_none_recovered.append({
                            "pmid": cand.pmid,
                            "journal": cand.journal,
                            "tier": p2.final_tier_code,
                            "reason": sig.rejection_reason or "no_qualifying_signal",
                        })
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
                cand, *_ = futures2[fut]
                stats.errors.append(f"pass2 pmid={cand.pmid}: {e}")
                log.exception("[%s] pass2 failure pmid=%s", site.code, cand.pmid)

    stats.alerts_created = len(alerts)
    total_cost = (stats.context_brief_cost_usd + stats.web_search_cost_usd
                  + stats.pass2_cost_usd)
    log.info(
        "[%s] alerts: A=%d B=%d C=%d NOISE=%d "
        "(cost: brief=$%.4f ws=$%.4f pass2=$%.4f total=$%.4f)",
        site.code,
        stats.alerts_by_tier.get("A", 0),
        stats.alerts_by_tier.get("B", 0),
        stats.alerts_by_tier.get("C", 0),
        stats.alerts_by_tier.get("NOISE", 0),
        stats.context_brief_cost_usd,
        stats.web_search_cost_usd,
        stats.pass2_cost_usd,
        total_cost,
    )

    # ---- STEP 7  persist (optional) --------------------------------------
    if persist:
        _persist(site_code, alerts, quarantine_items, stats, config)

    return stats, alerts, quarantine_items


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
    openai_api_key: Optional[str] = None,
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
        # Use a 14-day minimum for the FDA lane regardless of the run window.
        # FDA approval timing can slip slightly across week boundaries, and
        # missing an approval is far more costly than reviewing one twice.
        all_fda = retrieve_fda_records(
            lookback_days=max(lookback_days, 14),
            reference_date=end,
            openai_api_key=openai_api_key,
        )

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

    # Lane priority order: FDA → Conference → PubMed.
    #
    # FDA records are pre-qualified by source and bypass Gate 2 entirely.
    # Conference records carry ASCO/ESMO/ASTRO/ASH tags and score via
    # QS_MAJOR_CONFERENCE. PubMed fills in evidence and catches things the
    # other lanes missed.
    #
    # Order matters for cross-site PMID deduplication in run.py: the first
    # site to process a record claims it. Putting FDA first ensures FDA
    # records are never displaced by a PubMed duplicate from another site.
    return fda_records + conf_records + fetched


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist(
    site_code: str,
    alerts: list[AlertOutput],
    quarantine_items: list[QuarantineOutput],
    stats: RunStats,
    config: Config,
) -> None:
    from .persistence import SupabaseClient
    sb = SupabaseClient(url=config.supabase_url, service_role_key=config.supabase_service_role_key)
    run_id = sb.start_run("pubmed", site_code)
    try:
        # Persist standard alerts (status=EXTRACTED — awaits editor review before PUBLISH)
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

        # Persist quarantine items (status=QUARANTINE_REVIEW — never published without
        # human promotion; stored so admins can audit what the gate almost surfaced)
        for q in quarantine_items:
            try:
                source_id, trial_id = sb.upsert_source_and_trial(
                    q.candidate, raw_xml=q.candidate.raw_xml_hash
                )
                if not trial_id:
                    synth = sb._client.table("trials").insert({
                        "canonical_name": q.candidate.title[:200],
                        "phase": None,
                        "disease_site_id": sb.get_disease_site_id(site_code),
                        "keywords": q.candidate.modality_keywords_present[:20],
                    }).execute()
                    trial_id = synth.data[0]["id"]

                sb.insert_alert(
                    q.candidate, q.pass1,
                    # QuarantineOutput has no Pass2 — synthesise a minimal one
                    _quarantine_pass2_stub(q),
                    source_id, trial_id,
                    grounded=False,
                    unverified_quotes=[],
                    status="QUARANTINE_REVIEW",
                )
            except Exception as qe:
                log.warning(
                    "[%s] quarantine persist failed pmid=%s: %s",
                    site_code, q.candidate.pmid, qe,
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


def _quarantine_pass2_stub(q: QuarantineOutput):
    """
    Build a minimal Pass2Result for a quarantined item so _persist() can call
    sb.insert_alert() with the same signature it uses for normal alerts.

    A quarantined item never had a full Pass 2 deep review, so we synthesise
    a stub with tier=NOISE, reject_recommendation=True, and the quarantine
    reason in the one_liner. The status column is set to QUARANTINE_REVIEW in
    the Supabase insert so editors can find and promote these items manually.
    """
    from .triage.pass2 import Pass2Result
    parsed = {
        "reject_recommendation": True,
        "carcinos_one_liner": f"[QUARANTINE] {q.quarantine_reason}",
        "rejection_reason": q.rejection_reason,
        "quarantine_reason": q.quarantine_reason,
        "tier": "NOISE",
        "signal_type": "OTHER",
        "elevates_to_practice_changing": False,
    }
    return Pass2Result(
        parsed=parsed,
        raw_response=json.dumps(parsed),
        final_tier_code="NOISE",
        tier_rationale_text=f"QUARANTINE_REVIEW — {q.quarantine_reason}",
        cost_usd_estimate=0.0,
    )
