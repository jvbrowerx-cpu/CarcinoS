"""
CarcinoS Lane Diagnostic — run this locally to find where FDA/news ingestion breaks.

Usage:
    cd pipeline
    python diagnose_lanes.py

Checks in order:
  1. feedparser installed?
  2. FDA drug-approvals RSS reachable + returning entries?
  3. FDA press-releases RSS reachable + returning entries?
  4. Oncology filter passing any entries?
  5. Date window matching any entries?
  6. Abstract enrichment (page fetch) working?
  7. Lane 6 primary feeds (spot-check NEJM + OncLive)
  8. Lane 6 secondary trial-name extraction (spot-check OncLive)
  9. full retrieve_fda_records() end-to-end
"""

from __future__ import annotations
import sys
from datetime import date, timedelta

# ── helpers ───────────────────────────────────────────────────────────────────

PASS  = "\033[92m✓\033[0m"
FAIL  = "\033[91m✗\033[0m"
WARN  = "\033[93m⚠\033[0m"
INFO  = "\033[94m·\033[0m"

def ok(msg):   print(f"  {PASS} {msg}")
def fail(msg): print(f"  {FAIL} {msg}");
def warn(msg): print(f"  {WARN} {msg}")
def info(msg): print(f"  {INFO} {msg}")

def section(title):
    print(f"\n\033[1m{'─'*60}\033[0m")
    print(f"\033[1m{title}\033[0m")

# ── 1. feedparser ─────────────────────────────────────────────────────────────
section("1. feedparser")
try:
    import feedparser
    ok(f"feedparser {feedparser.__version__} installed")
except ImportError:
    fail("feedparser NOT installed — run: pip install feedparser")
    sys.exit(1)

# ── 2 + 3. FDA RSS feeds ──────────────────────────────────────────────────────
import requests

FDA_FEEDS = {
    "drug-approvals": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drug-approvals-and-databases/rss.xml",
    "press-releases": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
}

raw_entries: dict[str, list] = {}
for feed_name, url in FDA_FEEDS.items():
    section(f"2/3. FDA RSS — {feed_name}")
    info(f"URL: {url}")
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "CarcinoS/1.0"})
        r.raise_for_status()
        ok(f"HTTP {r.status_code} — {len(r.text):,} chars")
    except Exception as e:
        fail(f"HTTP fetch failed: {e}")
        raw_entries[feed_name] = []
        continue

    feed = feedparser.parse(r.text)
    entries = feed.entries
    info(f"Entries in feed: {len(entries)}")
    if not entries:
        warn("Feed returned 0 entries — might be empty or wrong URL")
        raw_entries[feed_name] = []
        continue

    ok(f"{len(entries)} entries found")
    # Show the 3 most recent
    for e in entries[:3]:
        title = getattr(e, "title", "(no title)")
        pub   = getattr(e, "published", "?")
        info(f"  [{pub}] {title[:90]}")
    raw_entries[feed_name] = entries

# ── 4. Oncology + approval filter ─────────────────────────────────────────────
section("4. Oncology + approval filter")
import re

_ONCO_RE = re.compile(
    r"\b(cancer|carcinoma|lymphoma|leukemia|myeloma|melanoma|sarcoma"
    r"|glioma|tumor|tumour|oncol|neoplasm|malignant|metastatic"
    r"|breast|lung|colon|colorectal|prostate|bladder|renal|ovarian"
    r"|hepatocellular|pancreatic|biliary|cholangiocarcinoma"
    r"|head.{1,5}neck|nsclc|sclc|cll|aml|dlbcl|mds|myelofibrosis)\b",
    re.IGNORECASE,
)
_APPROVAL_RE = re.compile(
    r"\b(approv|granted|clearance|label.{1,10}update|new indication"
    r"|accelerated approval|regular approval|full approval|NDA|BLA)\b",
    re.IGNORECASE,
)

for feed_name, entries in raw_entries.items():
    onco_pass = []
    for e in entries:
        title   = getattr(e, "title",   "") or ""
        summary = getattr(e, "summary", "") or getattr(e, "description", "") or ""
        combined = f"{title} {summary}"
        if _ONCO_RE.search(combined) and _APPROVAL_RE.search(combined):
            onco_pass.append(e)
    if onco_pass:
        ok(f"{feed_name}: {len(onco_pass)}/{len(entries)} entries pass oncology+approval filter")
        for e in onco_pass[:3]:
            info(f"  {getattr(e, 'title','')[:90]}")
    else:
        warn(f"{feed_name}: 0/{len(entries)} entries pass filter — showing 3 raw titles:")
        for e in entries[:3]:
            info(f"  {getattr(e, 'title','')[:90]}")

# ── 5. Date window ────────────────────────────────────────────────────────────
section("5. Date window (last 7 days)")
from email.utils import parsedate_to_datetime

cutoff = date.today() - timedelta(days=7)
info(f"Cutoff: {cutoff.isoformat()}  (today={date.today().isoformat()})")

for feed_name, entries in raw_entries.items():
    in_window = 0
    date_parse_fails = 0
    for e in entries:
        raw_date = getattr(e, "published", None) or getattr(e, "updated", None)
        if not raw_date:
            date_parse_fails += 1
            continue
        try:
            d = parsedate_to_datetime(raw_date).date()
            if d >= cutoff:
                in_window += 1
        except Exception:
            date_parse_fails += 1

    if in_window:
        ok(f"{feed_name}: {in_window} entries within last 7 days")
    else:
        warn(f"{feed_name}: 0 entries within last 7 days (parse fails={date_parse_fails})")
        # Show the most recent dates we do see
        dates = []
        for e in entries[:10]:
            raw = getattr(e, "published", None) or getattr(e, "updated", None)
            if raw:
                try:
                    dates.append(parsedate_to_datetime(raw).date().isoformat())
                except Exception:
                    pass
        if dates:
            info(f"  Most recent dates in feed: {dates[:5]}")

# ── 6. Abstract enrichment ────────────────────────────────────────────────────
section("6. Abstract enrichment (page fetch)")
# Pick the first FDA approval page URL we can find
test_url = None
for feed_name, entries in raw_entries.items():
    for e in entries:
        url = getattr(e, "link", "") or ""
        if "fda.gov/drugs/resources-information-approved-drugs" in url:
            test_url = url
            break
    if test_url:
        break

if not test_url:
    # Use a known approval page as fallback
    test_url = "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-capivasertib-abiraterone-and-prednisone-pten-deficient-androgen-pathway-modulation"
    info(f"No FDA approval URL found in feeds; using hardcoded test URL")

info(f"Fetching: {test_url[:80]}...")
try:
    r = requests.get(test_url, timeout=15, headers={"User-Agent": "CarcinoS/1.0"})
    r.raise_for_status()
    plain = re.sub(r"<[^>]+>", " ", r.text)
    plain = " ".join(plain.split())
    m = re.search(r"(FDA approved\s.{20,400}?\.)", plain, re.IGNORECASE)
    if m:
        ok(f"Page enrichment works — extracted: {m.group(1)[:120]}")
    else:
        warn("Page fetched but 'FDA approved...' pattern not found in body")
        info(f"  Body snippet: {plain[500:700]}")
except Exception as e:
    fail(f"Page fetch failed: {e}")

# ── 7. Lane 6 primary spot-check ──────────────────────────────────────────────
section("7. Lane 6 — primary feed spot-check (NEJM eTOC)")
nejm_url = "https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss"
info(f"URL: {nejm_url}")
try:
    r = requests.get(nejm_url, timeout=15, headers={"User-Agent": "CarcinoS/1.0"})
    r.raise_for_status()
    feed = feedparser.parse(r.text)
    ok(f"NEJM eTOC: HTTP {r.status_code}, {len(feed.entries)} entries")
    for e in feed.entries[:3]:
        info(f"  {getattr(e,'title','')[:90]}")
except Exception as e:
    fail(f"NEJM eTOC fetch failed: {e}")

# ── 8. Lane 6 secondary spot-check ───────────────────────────────────────────
section("8. Lane 6 — secondary feed spot-check (OncLive)")
from carcinos_ingestion.retrieval.news import extract_trial_names
onclive_url = "https://www.onclive.com/rss/news"
info(f"URL: {onclive_url}")
try:
    r = requests.get(onclive_url, timeout=15, headers={"User-Agent": "CarcinoS/1.0"})
    r.raise_for_status()
    feed = feedparser.parse(r.text)
    ok(f"OncLive RSS: HTTP {r.status_code}, {len(feed.entries)} entries")
    all_names: set[str] = set()
    for e in feed.entries[:20]:
        title = getattr(e, "title", "") or ""
        names = extract_trial_names(title)
        if names:
            all_names.update(names)
            info(f"  {names} ← {title[:70]}")
    if all_names:
        ok(f"Trial names extracted: {sorted(all_names)}")
    else:
        warn("No trial names extracted from first 20 headlines")
except Exception as e:
    fail(f"OncLive RSS fetch failed: {e}")

# ── 9. End-to-end retrieve_fda_records ────────────────────────────────────────
section("9. End-to-end retrieve_fda_records(lookback_days=14)")
try:
    from carcinos_ingestion.retrieval.fda import retrieve_fda_records
    records = retrieve_fda_records(lookback_days=14, enrich_abstracts=False)
    if records:
        ok(f"{len(records)} FDA record(s) retrieved")
        for r in records:
            info(f"  [{r.pub_date}] {r.title[:80]}")
    else:
        warn("0 FDA records returned — check steps 2–5 above for root cause")
except Exception as e:
    fail(f"retrieve_fda_records() raised: {e}")
    import traceback; traceback.print_exc()

section("Done")
print()
