"""Source finder: the model may LOOK anywhere, but only verbatim text survives.

The model is given web search and asked to find primary-source passages about
this specific trial (schedule, sequencing, toxicity by arm, patient-reported
outcomes). It returns URLs and exact quotes. Then code, not the model:

  1. drops any URL whose domain is not on the primary-source allowlist;
  2. downloads each remaining page itself;
  3. keeps a quote only if it appears word for word in that downloaded page.

What the model "remembers" or paraphrases can never get through, because the
row writer is only shown these verified excerpts, and the validator checks
every row quote against the downloaded page again.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

from .sources import ALLOWED_DOMAINS, SourceDoc, domain_allowed, fetch_page
from .text import quote_in

log = logging.getLogger("carcinos.care_team.finder")

FINDER_FIELDS = ["schedule", "sequencing", "toxicity", "patient_reported"]
MAX_PAGES = 4
MAX_ITEMS = 12

FINDER_PROMPT = """Find primary-source text about ONE specific clinical trial, for a nurse/APP
reference card. Search the web.

TRIAL
Title: {title}
Journal: {journal}
Trial identifiers: {ids}
Regimen: {regimen}

Look for passages that state, for THIS trial:
  • schedule — how and how often treatment was given (cycle pattern, fractionation, duration)
  • sequencing — timing relative to surgery, radiation or other therapy
  • toxicity — adverse events or toxicity, by arm when compared
  • patient_reported — quality-of-life or symptom outcomes

Use ONLY these kinds of sources: the trial's publication (journal site, PubMed,
PubMed Central), its ClinicalTrials.gov record, its meeting abstract, or FDA
documents. Never use press releases, company websites, news or trade press,
blogs, or summaries written by others.
Allowed domains: {domains}

Copy each passage EXACTLY as it appears on the page (8 to 60 words, no ellipses,
no edits). If you cannot find a passage, return no item for it. Do not answer
from memory.

Reply with ONLY this JSON, nothing else:
{{"items": [{{"field": "schedule|sequencing|toxicity|patient_reported", "url": "https://...", "quote": "exact text"}}]}}
"""


def default_searcher(model: str, fallback: str = "") -> Callable[[str], str]:
    """OpenAI Responses API with web search — the same pattern the news lane uses.

    If the main model does not support web search, the fallback model is tried once.
    """
    def _search(prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI()
        last = None
        for m in [model] + ([fallback] if fallback and fallback != model else []):
            try:
                resp = client.responses.create(model=m, tools=[{"type": "web_search_preview"}], input=prompt)
                return resp.output_text or ""
            except Exception as e:  # try the fallback model
                last = e
                log.info("care-team finder: %s web search failed (%s)", m, e)
        raise last if last else RuntimeError("web search failed")
    return _search


def _parse_items(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for it in (data.get("items") or [])[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        f, u, q = it.get("field"), (it.get("url") or "").strip(), (it.get("quote") or "").strip()
        if f in FINDER_FIELDS and u and q:
            out.append({"field": f, "url": u, "quote": q})
    return out


def find_verified_excerpts(
    alert: dict,
    nct_ids: list[str],
    searcher: Callable[[str], str],
    page_getter: Optional[Callable] = None,
) -> tuple[list[dict], dict[str, SourceDoc], list[dict]]:
    """Return (verified_excerpts, pages_by_url, rejected).

    verified_excerpts: [{field, url, quote, name}] — each quote found word for
    word on a page CarcinoS downloaded itself from an allowed domain.
    """
    s = alert.get("summary_json") or {}
    prompt = FINDER_PROMPT.format(
        title=alert.get("title") or "",
        journal=s.get("journal") or "",
        ids=", ".join(nct_ids) or "none listed",
        regimen=s.get("regimen_description") or s.get("intervention") or "",
        domains=", ".join(ALLOWED_DOMAINS),
    )
    try:
        raw = searcher(prompt)
    except Exception as e:
        log.info("care-team finder search failed: %s", e)
        return [], {}, [{"reason": f"search failed: {str(e)[:120]}"}]

    items = _parse_items(raw)
    pages: dict[str, SourceDoc] = {}
    verified: list[dict] = []
    rejected: list[dict] = []
    for it in items:
        url = it["url"]
        if not domain_allowed(url):
            rejected.append({**it, "reason": "domain not on the primary-source list"})
            continue
        if url not in pages:
            if len(pages) >= MAX_PAGES:
                rejected.append({**it, "reason": "page limit reached"})
                continue
            doc = fetch_page(url, page_getter)
            if doc is None:
                rejected.append({**it, "reason": "page could not be downloaded or read"})
                continue
            pages[url] = doc
        if quote_in(it["quote"], pages[url].text):
            verified.append({**it, "name": pages[url].name})
        else:
            rejected.append({**it, "reason": "quote not found on the downloaded page"})
    # keep only pages that actually contributed a verified quote
    used = {v["url"] for v in verified}
    return verified, {u: d for u, d in pages.items() if u in used}, rejected
