"""
Lane 5: GPT-4o web search retrieval.

Runs in parallel with the PubMed lanes. Uses the OpenAI Responses API with the
`web_search` built-in tool, giving the LLM browsing capability to surface:

  • ASCO, ESMO, ASTRO abstract pages not yet indexed in PubMed
  • JCO/NEJM/Lancet online-first papers in the 24-48h indexing lag window
  • FDA.gov approval pages (supplement to the RSS lane)
  • ClinicalTrials.gov result postings (Phase III completion data)

Architecture
------------
One web-search call per disease site per run. The LLM browses the web and
returns a structured JSON list of papers it found. Each paper is converted into
a CanonicalCandidate with:

  - pmid="WS_{uuid_hex}"   (synthetic — no PMID yet)
  - conference_source="WEB_SEARCH"
  - is_conference_abstract=False

These candidates are injected into the pipeline BEFORE Gate 1 signal scoring
and flow through the identical Gate 2 → Pass 2 → tier path as PubMed papers.

Title-based deduplication in Step 2 (filters/dedupe.py fuzzy_dedupe) prevents
PubMed + web-search versions of the same paper from both reaching Pass 2.

Cost
----
One gpt-4o call with web_search_preview per site per run.
  Web search requests: 5-15 per call (OpenAI pricing: $25/1k requests as of 2024).
  ~10 sites × 10 searches ≈ 100 requests ≈ $2.50/run.
  Token cost: ~2k in + ~500 out × 10 = ~$0.075.
  Total rough estimate: ~$2.60/run (weekly).

Failure mode
------------
Always returns ([], 0.0) on any error — never blocks the PubMed pipeline.
Logged as WARNING so the operator knows the lane was skipped.

Schema
------
The LLM returns a strict JSON object:
  {
    "papers": [
      {
        "title": "...",
        "authors": "...",         // "First Author et al." or full list
        "journal_or_source": "...",  // e.g. "JCO" or "ASCO 2026 Abstract"
        "publication_date": "...",   // ISO-8601 or "2026-06" or "June 2026"
        "url": "...",
        "abstract_or_summary": "...",  // full abstract or best-effort summary
        "nct_id": "...",           // NCT number if mentioned, else ""
        "doi": "...",              // DOI if visible, else ""
        "why_relevant": "..."      // one sentence: why this is clinically important
      },
      ...
    ],
    "search_queries_used": ["..."],  // what the LLM searched for
    "reasoning": "..."              // brief explanation of selection criteria
  }
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional

from ..retrieval.pubmed import PubMedRecord
from ..disease_sites.base import DiseaseSiteConfig

log = logging.getLogger("carcinos.web_search")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_WEB_SEARCH_SYSTEM = """\
You are CarcinoS Lane 5 — an oncology literature web search agent.

Your mission: find the most clinically important oncology publications and
announcements for a specific cancer disease site from the past 21 days that
may not yet be indexed in PubMed.

Priority targets (search for these):
  1. Conference abstract pages: ASCO (abstracts.asco.org), ESMO, ASTRO, ASH,
     AACR — especially Late-Breaking Abstracts and Plenary sessions
  2. Journal online-first / ahead-of-print: JCO (ascopubs.org/journal/jco),
     NEJM, Lancet, Lancet Oncology, JAMA Oncology, JAMA, Nature Medicine
  3. FDA approval pages: fda.gov/drugs/drug-approvals-and-databases
  4. Phase III trial results posted on ClinicalTrials.gov

Rules:
  • Retrieve only papers/abstracts from the past 21 DAYS — do not go further back.
  • Report ONLY Phase II/III clinical trials, FDA approvals, or guideline updates.
    Skip case reports, editorials, reviews, and preclinical papers.
  • 5 to 15 papers maximum — fewer, higher-confidence entries beat a long list.
  • For each paper, provide the best abstract or summary you can find from the page.
    Minimum 2 sentences of actual clinical content (not just the title).
  • If you cannot find any relevant papers for this site in the past 21 days, return
    an empty papers list — do NOT fabricate papers.
  • Do NOT include papers already published >21 days ago.

Return ONLY a JSON object with this exact structure (no markdown, no prose):
{
  "papers": [
    {
      "title": "...",
      "authors": "...",
      "journal_or_source": "...",
      "publication_date": "YYYY-MM-DD or YYYY-MM",
      "url": "https://...",
      "abstract_or_summary": "...",
      "nct_id": "NCT... or empty string",
      "doi": "10.... or empty string",
      "why_relevant": "one sentence"
    }
  ],
  "search_queries_used": ["..."],
  "reasoning": "..."
}
Start your response with { and end with }. No other text."""

_WEB_SEARCH_USER = """\
Disease site: {site_name} ({site_code})
Search window: past 21 days (from {start_date} to {today})
Key terms to search: {quick_terms}
Watched trials (highest priority): {watched_trials}

Active / recent major conferences (check these first):
{active_meetings}

Search strategy:
  1. Check conference abstract browsers for this disease site
  2. Search JCO, NEJM, Lancet, JAMA for recent Phase II/III results
  3. Check FDA.gov for new approvals in this cancer type
  4. Search for any active watched trials that may have reported results

Return JSON only."""

# JSON schema for structured web-search output
_WEB_SEARCH_SCHEMA = {
    "name": "lane5_web_search",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "papers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title":               {"type": "string", "maxLength": 400},
                        "authors":             {"type": "string", "maxLength": 200},
                        "journal_or_source":   {"type": "string", "maxLength": 120},
                        "publication_date":    {"type": "string", "maxLength": 30},
                        "url":                 {"type": "string", "maxLength": 400},
                        "abstract_or_summary": {"type": "string", "maxLength": 2000},
                        "nct_id":              {"type": "string", "maxLength": 20},
                        "doi":                 {"type": "string", "maxLength": 100},
                        "why_relevant":        {"type": "string", "maxLength": 280},
                    },
                    "required": [
                        "title", "authors", "journal_or_source", "publication_date",
                        "url", "abstract_or_summary", "nct_id", "doi", "why_relevant",
                    ],
                    "additionalProperties": False,
                },
                "maxItems": 15,
            },
            "search_queries_used": {
                "type": "array",
                "items": {"type": "string", "maxLength": 200},
                "maxItems": 20,
            },
            "reasoning": {"type": "string", "maxLength": 500},
        },
        "required": ["papers", "search_queries_used", "reasoning"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Meeting calendar (mirrors context_brief.py)
# ---------------------------------------------------------------------------

_MEETING_WINDOWS: list[tuple[str, int, int]] = [
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
    active = []
    for name, pub_month, window in _MEETING_WINDOWS:
        for year in (today.year, today.year - 1):
            try:
                meeting_start = date(year, pub_month, 1)
            except ValueError:
                continue
            delta = (today - meeting_start).days
            if -7 <= delta <= window:
                active.append(f"  • {name} ({year})")
    return "\n".join(active) if active else "  • None currently active"


# ---------------------------------------------------------------------------
# Conversion: web-search paper → PubMedRecord
# ---------------------------------------------------------------------------

def _paper_to_pubmed_record(paper: dict, site_code: str) -> PubMedRecord:
    """
    Convert a Lane 5 web-search paper dict to a PubMedRecord.

    Uses a synthetic PMID ("WS_{uuid_hex[:12]}") since the paper may not
    yet have a PMID. The text_hash is derived from the title to allow
    deduplication against PubMed results that share the same title.
    """
    title = (paper.get("title") or "").strip()
    abstract = (paper.get("abstract_or_summary") or "").strip()
    journal = (paper.get("journal_or_source") or "").strip()
    pub_date = (paper.get("publication_date") or "").strip()
    url = (paper.get("url") or "").strip()
    nct_id = (paper.get("nct_id") or "").strip()
    doi = (paper.get("doi") or "").strip()
    authors_str = (paper.get("authors") or "").strip()

    # Synthetic PMID — deterministic per title to enable idempotent re-runs
    title_hash = hashlib.sha256(title.lower().encode()).hexdigest()
    synthetic_pmid = f"WS_{title_hash[:12]}"

    # text_hash from title for fuzzy dedup against PubMed results
    text_hash = title_hash

    nct_ids = [nct_id] if nct_id else []
    authors = [a.strip() for a in authors_str.split(",") if a.strip()][:10]

    # Detect conference from journal_or_source so the signal scorer can apply
    # the correct QS_MAJOR_CONFERENCE rules. Without this, ASCO/ESMO abstracts
    # found by web search are tagged "WEB_SEARCH" and miss conference scoring.
    _CONF_KEYWORDS = {
        "ASCO": ["asco", "american society of clinical oncology"],
        "ESMO": ["esmo", "european society for medical oncology"],
        "ASTRO": ["astro", "american society for radiation oncology"],
        "ASH": ["ash", "american society of hematology"],
        "AACR": ["aacr", "american association for cancer research"],
        "SITC": ["sitc", "society for immunotherapy of cancer"],
        "SABCS": ["sabcs", "san antonio breast cancer"],
        "ESGO": ["esgo"],
        "SGO": ["sgo", "society of gynecologic oncology"],
    }
    journal_lower = journal.lower()
    conference_source = "WEB_SEARCH"
    for conf_name, keywords in _CONF_KEYWORDS.items():
        if any(kw in journal_lower for kw in keywords):
            conference_source = conf_name
            break

    rec = PubMedRecord(
        pmid=synthetic_pmid,
        title=title,
        abstract=abstract,
        journal=journal,
        pub_date=pub_date,
        publication_types=["Journal Article"],
        doi=doi or None,
        pmc_id=None,
        nct_ids=nct_ids,
        mesh_terms=[],
        authors=authors,
        language="eng",
        raw_xml="",
        text_hash=text_hash,
        conference_source=conference_source,
        url_override=url or None,  # carry real article URL through to persistence layer
    )
    return rec


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> "dict | None":
    """
    Extract a JSON object from text that may be wrapped in markdown code fences.
    Tries:
      1. Direct json.loads (cleanest case)
      2. Strip ```json ... ``` or ``` ... ``` fences
      3. Find first { ... } block in the text
    Returns None if no valid JSON object found.
    """
    import json
    import re

    text = text.strip()

    # 1. Direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 3. Find first balanced { ... } block
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i+1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break

    return None


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def _estimate_web_search_cost(usage: dict) -> float:
    """
    Estimate cost for gpt-4o with web_search_preview.
    Pricing as of late 2024:
      gpt-4o input:  $2.50 / 1M tokens
      gpt-4o output: $10.00 / 1M tokens
      web_search_preview: $25.00 / 1000 requests (billed per search call, not per token)
    We don't know the exact number of search calls, so we estimate 10 per site call.
    """
    in_per_million = 2.50
    out_per_million = 10.00
    search_cost_per_call = 0.025   # $25 / 1000 = $0.025 per search request; estimate 1 req

    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    # web_search_preview makes multiple search requests internally;
    # usage dict doesn't expose request count, so we assume 5 average search requests
    return (
        (pt / 1_000_000) * in_per_million
        + (ct / 1_000_000) * out_per_million
        + 5 * search_cost_per_call
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_web_search_lane(
    openai_api_key: str,
    *,
    site: DiseaseSiteConfig,
    watched_trials: list[str],
    today: Optional[date] = None,
    model: str = "gpt-4o-mini",
) -> tuple[list[PubMedRecord], float]:
    """
    Run Lane 5 web search for a disease site.

    Returns:
        (records, cost_usd_estimate)
        records: list of PubMedRecord-like objects with conference_source="WEB_SEARCH"
                 Empty list on any failure or if no relevant papers found.
        cost_usd_estimate: rough per-run cost.

    Always returns ([], 0.0) on any error — never blocks the PubMed pipeline.
    """
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("[%s] web_search: openai package not installed", site.code)
        return [], 0.0

    if not openai_api_key:
        log.warning("[%s] web_search: no OPENAI_API_KEY", site.code)
        return [], 0.0

    if today is None:
        today = date.today()

    start_date = (today - timedelta(days=21)).isoformat()
    active_mtg = _active_meetings_str(today)
    quick_terms_str = ", ".join(list(site.free_text_core)[:15]) if site.free_text_core else site.name
    watched_str = ", ".join(watched_trials[:20]) if watched_trials else "none specified"

    user_msg = _WEB_SEARCH_USER.format(
        site_name=site.name,
        site_code=site.code,
        start_date=start_date,
        today=today.isoformat(),
        quick_terms=quick_terms_str,
        watched_trials=watched_str,
        active_meetings=active_mtg,
    )

    try:
        client = OpenAI(api_key=openai_api_key)

        # Use the Responses API with web_search_preview tool.
        # IMPORTANT: Do NOT pass response_format / text.format here — the API
        # rejects JSON mode when a web search tool is present (400 error:
        # "Web Search cannot be used with JSON mode"). Rely on _extract_json
        # below to parse JSON from the free-form text response.
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search_preview"}],
            input=[
                {"role": "system", "content": _WEB_SEARCH_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
        )

    except Exception as exc:
        log.warning("[%s] web_search: Responses API call failed: %s", site.code, exc)
        return [], 0.0

    # Extract text output from the response.
    # The Responses API exposes output_text as a convenience attribute,
    # but we also handle the older iteration-based approach as fallback.
    try:
        import json

        # Preferred: output_text convenience attribute (openai >= 1.66)
        text_content = ""
        if hasattr(response, "output_text") and response.output_text:
            text_content = response.output_text
        else:
            # Fallback: iterate over output items
            for block in (getattr(response, "output", None) or []):
                # Skip web search tool call items — only collect message content
                if getattr(block, "type", "") in ("web_search_call", "web_search_result"):
                    continue
                if hasattr(block, "content"):
                    for c in (block.content or []):
                        if hasattr(c, "text"):
                            text_content += c.text
                elif hasattr(block, "text"):
                    text_content += block.text

        if not text_content.strip():
            log.warning("[%s] web_search: empty text output from Responses API", site.code)
            return [], 0.0

        # Robust JSON extraction — handle markdown code fences if present
        parsed = _extract_json(text_content)
        if parsed is None:
            log.warning("[%s] web_search: could not extract JSON from response", site.code)
            return [], 0.0

    except Exception as exc:
        log.warning("[%s] web_search: failed to parse response: %s", site.code, exc)
        return [], 0.0

    # Usage for cost estimation
    usage = {}
    try:
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, "input_tokens", 0),
                "completion_tokens": getattr(u, "output_tokens", 0),
            }
    except Exception:
        pass

    papers_raw = parsed.get("papers") or []
    reasoning = parsed.get("reasoning") or ""
    queries = parsed.get("search_queries_used") or []

    log.info(
        "[%s] web_search: found %d papers (queries: %s; reasoning: %s)",
        site.code,
        len(papers_raw),
        queries[:3],
        reasoning[:100],
    )

    records: list[PubMedRecord] = []
    for paper in papers_raw:
        if not isinstance(paper, dict):
            continue
        title = (paper.get("title") or "").strip()
        if not title:
            continue
        rec = _paper_to_pubmed_record(paper, site.code)
        records.append(rec)
        log.debug(
            "[%s] web_search: %s | %s | %s",
            site.code, rec.pmid, rec.journal, title[:80],
        )

    cost = _estimate_web_search_cost(usage)
    return records, cost
