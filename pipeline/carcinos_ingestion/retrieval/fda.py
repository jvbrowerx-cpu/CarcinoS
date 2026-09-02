"""
FDA Oncology approvals ingestion lane.

PRIMARY SOURCE: HTML scrape of the FDA oncology approval notifications page.

  https://www.fda.gov/drugs/resources-information-approved-drugs/
      oncology-cancerhematologic-malignancies-approval-notifications

This page is the canonical, continuously updated table of ALL oncology drug
approvals, label expansions, and safety notifications. Each row already
contains the full indication text, so no secondary page fetches are needed.

FALLBACK: dual RSS feeds (drug-approvals + press-releases) used if the HTML
page is unreachable. The RSS feeds are less reliable (one is often empty,
the other returns gzip that some environments can't parse), so they are
secondary.

Records are returned as synthetic PubMedRecord objects tagged with:
  publication_types = ["FDA Drug Approval"]
  conference_source = "FDA"

The pipeline treats conference_source == "FDA" as force-keep, bypassing
signal scoring and going directly to Pass 2 for summarisation.

Usage:
    from .fda import retrieve_fda_records
    records = retrieve_fda_records(lookback_days=7)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from .pubmed import PubMedRecord

log = logging.getLogger("carcinos.fda")

# ── Source URLs ───────────────────────────────────────────────────────────────

# Primary: HTML approval notifications table (most reliable, most complete)
FDA_ONCO_APPROVALS_PAGE = (
    "https://www.fda.gov/drugs/resources-information-approved-drugs"
    "/oncology-cancerhematologic-malignancies-approval-notifications"
)

# Fallback: RSS feeds (use only if page scrape yields nothing)
FDA_DRUG_APPROVALS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/drug-approvals-and-databases/rss.xml"
)
FDA_PRESS_RSS = (
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
    "/press-releases/rss.xml"
)
_ALL_FDA_FEEDS = [FDA_DRUG_APPROVALS_RSS, FDA_PRESS_RSS]

# OpenFDA REST API — NOT subject to Akamai CDN blocking.
# Used as a guaranteed always-on parallel source alongside the HTML scrape.
OPENFDA_DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"

# Pharmacological class EPC terms that reliably indicate oncology drugs
_ONCO_PHARM_CLASS_RE = re.compile(
    r"("
    r"kinase inhibitor|antineoplastic|immunotherapy|checkpoint inhibitor"
    r"|monoclonal antibody.{0,30}(cancer|tumor|oncol|leukemia|lymphoma|myeloma)"
    r"|pd.?[l1]{1,2}.{0,15}inhibitor|ctla.?4|vegf.{0,10}inhibitor"
    r"|her2|bcl.?2|btk inhibitor|alk inhibitor|proteasome inhibitor"
    r"|car.{0,3}t|chimeric antigen receptor|targeted therapy.{0,20}cancer"
    r"|hormone receptor.{0,20}(cancer|breast|prostate)"
    r"|cdk.{0,5}inhibitor|mtor inhibitor|parp inhibitor"
    r"|antibody.drug conjugate|adc.{0,10}(cancer|tumor)"
    r"|oncolytic|oncolytic virus|viral vector.{0,20}(cancer|tumor|oncol)"
    r"|bispecific.{0,20}(cancer|tumor|oncol|t.cell)"
    r"|radioligand|radiopharmaceutical|lutetium|radium.223|actinium"
    r"|tumor.infiltrating lymphocyte|til.{0,5}therap"
    r")",
    re.IGNORECASE,
)

# ── Non-oncology exclusion filter ────────────────────────────────────────────
# Some FDA approvals appear on the hematology-oncology notifications page
# despite being for non-cancer indications (e.g. REZDIFFRA for NASH,
# thyroid hormone replacement, lipid disorders). These match broad terms like
# "thyroid" or "hematologic" but are not oncology drugs. Exclude them early
# before FORCE_KEEP is applied.
_NON_ONCO_EXCLUDE_RE = re.compile(
    r"\b("
    r"steatohepatitis|nash|nafld|non.alcoholic fatty liver"
    r"|thyroid hormone receptor.{0,20}agonist"
    r"|hypothyroidism|hyperthyroidism|thyroid replacement"
    r"|lipid.lowering|hypercholesterolemia|hyperlipidemia"
    r"|type.{1,5}diabetes|insulin resistance"
    r"|rheumatoid arthritis|psoriatic arthritis|ankylosing spondylitis"
    r"|multiple sclerosis|crohn.s disease|ulcerative colitis"
    r"|atopic dermatitis|eczema"
    r"|heart failure|hypertension|anticoagulant"
    r"|rare disease.{0,30}non.oncology|enzyme replacement"
    r")\b",
    re.IGNORECASE,
)

# ── Oncology / approval filters ───────────────────────────────────────────────

_ONCO_RE = re.compile(
    r"\b("
    r"cancer|carcinoma|lymphoma|leukemia|leukaemia|myeloma|melanoma"
    r"|sarcoma|glioma|glioblastoma|tumor|tumour|oncol|neoplasm"
    r"|malignant|malignancy|metastatic|metastasis"
    r"|breast|lung|colon|colorectal|rectal|ovarian|cervical|endometrial"
    r"|uterine|prostate|bladder|renal|kidney|hepatocellular|pancreatic"
    r"|gastric|esophageal|biliary|cholangiocarcinoma"
    r"|head.{1,5}neck|laryngeal|oropharyngeal|nasopharyngeal|thyroid"
    r"|gbm|astrocytoma|medulloblastoma|gist|osteosarcoma"
    r"|nsclc|sclc|mesothelioma|thymoma"
    r"|cll|aml|cml|dlbcl|mds|myelofibrosis|myelodysplastic"
    r"|merkel|cutaneous|hematolog|haematolog"
    r"|oncolytic|unresectable|advanced.{1,15}(disease|stage)"
    r")\b",
    re.IGNORECASE,
)

_APPROVAL_RE = re.compile(
    r"\b("
    r"approv|granted|clearance|label.{1,10}update|label.{1,10}change"
    r"|new indication|indication.{1,10}expand|expanded indication"
    r"|priority review|breakthrough therapy|accelerated approval"
    r"|regular approval|full approval|biologics license"
    r"|supplemental.{1,10}application|sNDA|sBLA|NDA|BLA"
    r"|safety.{1,10}notification|safety labeling"
    r")\b",
    re.IGNORECASE,
)

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FDAItem:
    """Parsed FDA approval record before conversion to PubMedRecord."""
    uid: str        # sha256[:16] of the URL
    title: str
    summary: str    # Full indication text (from page) or RSS summary
    url: str
    pub_date: str   # ISO 8601 (YYYY-MM-DD) or ""
    source: str     # "page" | "rss"


# ── Primary source: HTML table scraper ───────────────────────────────────────

# The approval page table columns:
#   col 0: <a href="/drugs/...">Title text</a>
#   col 1: Full description / indication text
#   col 2: Date like "6/12/2026"

_TD_RE    = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
_A_RE     = re.compile(r'href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_TAG_RE   = re.compile(r"<[^>]+>")
_WS_RE    = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _parse_fda_date(raw: str) -> tuple[Optional[date], str]:
    """Parse dates like '6/12/2026' or 'June 12, 2026'. Returns (date, iso_str)."""
    raw = raw.strip()
    # M/D/YYYY or M/DD/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return d, d.isoformat()
        except ValueError:
            pass
    # "Month D, YYYY"
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            d = datetime.strptime(raw, fmt).date()
            return d, d.isoformat()
        except ValueError:
            pass
    return None, ""


def _scrape_approval_page(
    cutoff: date,
    timeout: int = 20,
) -> list[FDAItem]:
    """
    Scrape the FDA oncology approval notifications HTML page.

    The page contains a table with one approval per row. Each row has:
      - A link to the approval-specific page (with the title as link text)
      - The full indication description text
      - The approval date

    We stop consuming rows once the date falls before `cutoff`, since the
    table is always ordered newest-first.
    """
    try:
        resp = requests.get(
            FDA_ONCO_APPROVALS_PAGE,
            timeout=timeout,
            headers={"User-Agent": "CarcinoS/1.0"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        log.warning("FDA approval page fetch failed: %s", exc)
        return []

    # Find the main content table. The page has exactly one data table.
    # Split into <tr> blocks and parse each.
    tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    if not tr_blocks:
        log.warning("FDA approval page: no <tr> blocks found")
        return []

    items: list[FDAItem] = []
    for tr in tr_blocks:
        tds = _TD_RE.findall(tr)
        if len(tds) < 3:
            continue

        # Column 0: link cell  →  extract href + title text
        link_cell = tds[0]
        a_match = _A_RE.search(link_cell)
        if not a_match:
            continue
        href  = a_match.group(1).strip()
        title = _strip_html(a_match.group(2))
        if not title:
            title = _strip_html(link_cell)

        # Build absolute URL
        if href.startswith("/"):
            url = "https://www.fda.gov" + href
        elif href.startswith("http"):
            url = href
        else:
            continue  # skip malformed

        # Column 1: description / indication text
        summary = _strip_html(tds[1])

        # Column 2: date
        raw_date = _strip_html(tds[2])
        pub_date_obj, pub_date_str = _parse_fda_date(raw_date)

        # Date filtering — skip rows outside the lookback window.
        # Use `continue` (not `break`) in case the FDA table has any rows
        # slightly out of chronological order; we want to scan the full
        # recent portion rather than stopping on the first out-of-window row.
        if pub_date_obj and pub_date_obj < cutoff:
            continue

        # Non-oncology exclusion — drop known non-cancer drug classes that
        # occasionally appear on the hematology-oncology notifications page
        combined = f"{title} {summary}"
        if _NON_ONCO_EXCLUDE_RE.search(combined):
            log.info("FDA scraper: excluded non-oncology record: %s", title)
            continue

        # Oncology / approval filter (belt-and-suspenders; the page is already oncology-only)
        if not _ONCO_RE.search(combined) and not _APPROVAL_RE.search(combined):
            continue

        uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        items.append(FDAItem(
            uid=uid,
            title=title,
            summary=summary,
            url=url,
            pub_date=pub_date_str,
            source="page",
        ))

    log.info("FDA scraper: %d items from approval notifications page (cutoff=%s)",
             len(items), cutoff.isoformat())
    return items


# ── Fallback: RSS feeds ───────────────────────────────────────────────────────

def _fetch_rss_feed(url: str, timeout: int = 20) -> list:
    """Fetch and parse a single RSS feed. Returns feedparser entries."""
    try:
        import feedparser  # type: ignore
    except ImportError:
        log.warning("feedparser not installed — RSS fallback disabled. "
                    "Run: pip install feedparser")
        return []

    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "CarcinoS/1.0"})
        resp.raise_for_status()
        # feedparser can handle both text and bytes
        feed = feedparser.parse(resp.content)
        return feed.entries
    except Exception as exc:
        log.warning("FDA RSS fetch failed (%s): %s", url, exc)
        return []


def _fetch_rss_items(cutoff: date, timeout: int = 20) -> list[FDAItem]:
    """
    Fallback RSS ingestion. Fetches both FDA RSS feeds, deduplicates by URL,
    filters for oncology approvals within the date window.
    """
    from email.utils import parsedate_to_datetime

    seen_urls: set[str] = set()
    items: list[FDAItem] = []

    for feed_url in _ALL_FDA_FEEDS:
        for entry in _fetch_rss_feed(feed_url, timeout=timeout):
            url = (getattr(entry, "link", None) or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Date parsing
            pub_date_obj: Optional[date] = None
            pub_date_str = ""
            try:
                raw = (getattr(entry, "published", None)
                       or getattr(entry, "updated", None))
                if raw:
                    dt = parsedate_to_datetime(raw)
                    pub_date_obj = dt.date()
                    pub_date_str = pub_date_obj.isoformat()
            except Exception:
                pass

            if pub_date_obj and pub_date_obj < cutoff:
                continue

            title   = (getattr(entry, "title",   None) or "").strip()
            summary = (getattr(entry, "summary", None)
                       or getattr(entry, "description", None) or "").strip()

            combined = f"{title} {summary}"
            if not _ONCO_RE.search(combined):
                continue
            if not _APPROVAL_RE.search(combined):
                continue

            uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            items.append(FDAItem(
                uid=uid,
                title=title,
                summary=summary,
                url=url,
                pub_date=pub_date_str,
                source="rss",
            ))

    log.info("FDA RSS fallback: %d oncology items (cutoff=%s)", len(items), cutoff.isoformat())
    return items


# ── Always-on parallel source: OpenFDA REST API ───────────────────────────────
#
# The FDA's openFDA drug applications database (api.fda.gov/drug/drugsfda.json)
# is a public REST API that is NOT subject to Akamai bot-detection.  It returns
# structured JSON for all NDA/BLA submissions, including approval status dates.
#
# We filter for oncology by checking:
#   1. openfda.pharm_class_epc — pharmacological class (e.g. "Kinase Inhibitor")
#   2. Brand / generic drug name against _ONCO_RE (catches drugs with clear names)
#   3. Submission class description (e.g. "Type 1 - New Molecular Entity")
#
# This source runs ALWAYS, in parallel with the HTML scrape, so GitHub Actions
# Akamai blocks cannot cause a total FDA coverage gap.

def _fetch_fda_via_openfda(cutoff: date, timeout: int = 20) -> list[FDAItem]:
    """
    Fetch recently approved oncology drug applications from the OpenFDA REST API.

    Searches for NDA/BLA submissions with status AP (approved) within the
    lookback window.  Filters for oncology using pharmacological class codes.
    This endpoint is not CDN-blocked, making it the most reliable GitHub Actions
    source for FDA approvals.
    """
    cutoff_str = cutoff.strftime("%Y%m%d")
    today_str  = date.today().strftime("%Y%m%d")

    try:
        resp = requests.get(
            OPENFDA_DRUGSFDA_URL,
            params={
                "search": (
                    f'submissions.submission_status:"AP"'
                    f' AND submissions.submission_status_date:'
                    f'[{cutoff_str} TO {today_str}]'
                ),
                "limit": 100,
            },
            timeout=timeout,
            headers={"User-Agent": "CarcinoS/1.0 (oncology intelligence; contact: info@carcino-s.com)"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("OpenFDA drugsfda API failed: %s", exc)
        return []

    results = data.get("results", [])
    if not results:
        log.info("OpenFDA API: 0 approved submissions in window (cutoff=%s)", cutoff.isoformat())
        return []

    items: list[FDAItem] = []

    for result in results:
        openfda     = result.get("openfda", {})
        brand_names = openfda.get("brand_name", [])
        generic_names = openfda.get("generic_name", [])
        pharm_classes = (
            openfda.get("pharm_class_epc", [])
            + openfda.get("pharm_class_cs", [])
            + openfda.get("pharm_class_moa", [])
        )
        manufacturer = (openfda.get("manufacturer_name") or ["Unknown Manufacturer"])[0]
        app_number   = result.get("application_number", "")

        drug_name = (
            (brand_names[0] if brand_names else "")
            or (generic_names[0] if generic_names else "")
        )
        if not drug_name:
            continue

        # Find approved submissions in the date window
        approved: list[tuple[date, dict]] = []
        for sub in result.get("submissions", []):
            if sub.get("submission_status") != "AP":
                continue
            raw_date = sub.get("submission_status_date", "")
            if len(raw_date) == 8:
                try:
                    d = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:]))
                    if d >= cutoff:
                        approved.append((d, sub))
                except ValueError:
                    pass

        if not approved:
            continue

        latest_date, latest_sub = max(approved, key=lambda x: x[0])
        sub_type  = latest_sub.get("submission_type", "ORIG")   # ORIG | SUPPL
        sub_class = latest_sub.get("submission_class_code_description", "")

        # Oncology filter: check pharm class, drug name, brand name, and sub class.
        # Novel drug classes (oncolytic viruses, radioligands, bispecifics, TIL therapy)
        # often have generic names with no cancer keywords — so include brand name and
        # be permissive: if pharm class OR brand name OR sub_class matches, keep it.
        # The non-oncology exclusion filter (_NON_ONCO_EXCLUDE_RE) handles false positives.
        all_brand_names = " ".join(brand_names)
        check_text = " ".join([
            " ".join(pharm_classes),
            drug_name,
            all_brand_names,
            sub_class,
        ])
        is_onco = (
            _ONCO_RE.search(check_text)
            or _ONCO_PHARM_CLASS_RE.search(" ".join(pharm_classes))
            or _ONCO_PHARM_CLASS_RE.search(check_text)
        )
        if not is_onco:
            # Last resort: if it's a new molecular entity or biologic approval
            # and the sub_class suggests it could be oncology, let it through to
            # the non-oncology exclusion filter below.
            is_new_therapeutic = any(
                kw in sub_class.lower()
                for kw in ("new molecular entity", "new biologic", "biologics license",
                           "therapeutic biological", "virus", "cell therapy",
                           "gene therapy", "immunotherapy")
            )
            if not is_new_therapeutic:
                continue

        # Non-oncology exclusion — drop known non-cancer drug classes.
        if _NON_ONCO_EXCLUDE_RE.search(check_text):
            log.debug("OpenFDA: excluded non-oncology drug: %s", drug_name)
            continue

        # Build title and summary
        action  = "Approves" if sub_type == "ORIG" else "Grants Supplemental Approval for"
        title   = f"FDA {action} {drug_name}"
        if app_number:
            title += f" ({app_number})"

        pharm_str = "; ".join(pharm_classes[:3]) if pharm_classes else "oncology agent"
        summary = (
            f"{title}. Manufacturer: {manufacturer}. "
            f"Pharmacological class: {pharm_str}. "
            f"Approval type: {sub_type} — {sub_class}."
        ).strip()

        # Enrich with indication text so disease-site routing can match
        # cancer-type keywords (e.g. "non-small cell lung cancer", "myeloma").
        # Without this, OpenFDA summaries contain only pharm-class strings that
        # never appear in SITE_QUICK_TERMS and the record is dropped by all sites.
        indication = _fetch_label_indication(app_number)
        if indication:
            summary = f"{summary} Indication: {indication}"

        url = (
            f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
            f"?event=overview.process&ApplNo={app_number}"
            if app_number else FDA_ONCO_APPROVALS_PAGE
        )
        uid = hashlib.sha256(
            f"openfda|{app_number}|{latest_date.isoformat()}".encode("utf-8")
        ).hexdigest()[:16]

        items.append(FDAItem(
            uid=uid,
            title=title,
            summary=summary,
            url=url,
            pub_date=latest_date.isoformat(),
            source="openfda",
        ))

    log.info(
        "OpenFDA API: %d oncology approval(s) (cutoff=%s)",
        len(items), cutoff.isoformat(),
    )
    return items


# ── Label indication lookup ───────────────────────────────────────────────────

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"

def _fetch_label_indication(app_number: str, timeout: int = 10) -> str:
    """
    Fetch the first 400 characters of the approved indication text for a
    drug application from the FDA label API.

    This is called for every OpenFDA drugsfda result so that the summary
    contains cancer-type keywords (e.g. "non-small cell lung cancer", "multiple
    myeloma") that the site routing filter in pipeline._retrieve() can match
    against SITE_QUICK_TERMS.

    Without this, OpenFDA summaries only contain pharmacological class strings
    like "Kinase Inhibitor" — which never match site terms like "lung" or
    "myeloma" — causing every OpenFDA item to be silently dropped by all 11
    disease-site routing filters.

    Returns "" on any failure (safe fallback — routing just works less well).
    """
    if not app_number:
        return ""
    try:
        resp = requests.get(
            OPENFDA_LABEL_URL,
            params={
                "search": f'openfda.application_number:"{app_number}"',
                "limit": 1,
            },
            timeout=timeout,
            headers={"User-Agent": "CarcinoS/1.0"},
        )
        if not resp.ok:
            return ""
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return ""
        label = results[0]
        # indications_and_usage is a list; take the first entry and trim
        iu_list = label.get("indications_and_usage", [])
        if iu_list:
            raw = _WS_RE.sub(" ", iu_list[0]).strip()
            return raw[:400]
        # Some labels use purpose field instead
        purpose_list = label.get("purpose", [])
        if purpose_list:
            return _WS_RE.sub(" ", purpose_list[0]).strip()[:400]
    except Exception as exc:
        log.debug("Label indication lookup failed for %s: %s", app_number, exc)
    return ""


# ── Third-tier supplement: LLM web search ────────────────────────────────────

def _fetch_fda_via_llm(
    cutoff: date,
    openai_api_key: str,
    model: str = "gpt-4o-mini-search-preview",
) -> list[FDAItem]:
    """
    LLM web search supplement for recent FDA oncology approvals.

    Uses the OpenAI Responses API with web_search_preview tool.  IMPORTANT: this
    requires a model that supports web search — use gpt-4o-mini-search-preview
    or gpt-4o-search-preview.  Standard gpt-4o-mini does NOT support
    web_search_preview and will throw a 400 error that is silently swallowed.

    Runs alongside the HTML scrape + OpenFDA API; results are merged by URL dedup.
    """
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("FDA LLM fallback: openai package not installed")
        return []

    prompt = (
        f"Search the FDA website (fda.gov) for FDA oncology drug approvals announced "
        f"on or after {cutoff.isoformat()}. Check the FDA Hematology/Oncology Approvals "
        f"& Safety Notifications page and any recent FDA press releases.\n\n"
        f"Include ALL cancer drug approvals, including:\n"
        f"- New drug approvals and expanded indications\n"
        f"- Accelerated approvals and regular approvals\n"
        f"- Novel drug classes: oncolytic viruses, cell therapies (CAR-T, TIL), "
        f"  radioligands (lutetium, actinium), bispecific antibodies, antibody-drug "
        f"  conjugates, gene therapies for cancer\n"
        f"- Drugs with complex generic names (e.g. '-vec', '-mab', '-nib', '-tug')\n\n"
        f"For each approval, output EXACTLY this format:\n\n"
        f"TITLE: [drug brand name + brief indication, e.g. 'FDA Grants Accelerated Approval "
        f"to Tudriqev (vusolimogene oderparepvec-wtpg) Plus Nivolumab for Melanoma']\n"
        f"DATE: [YYYY-MM-DD]\n"
        f"URL: [fda.gov approval page URL if found]\n"
        f"SUMMARY: [2-3 sentences: brand name, generic name, cancer type/indication, "
        f"approval type (regular/accelerated), key trial and patient population]\n\n"
        f"Only output approvals on or after {cutoff.isoformat()}. "
        f"Do not include trial results without FDA action. "
        f"Output every approval found — do not limit to the most important ones."
    )

    try:
        client = OpenAI(api_key=openai_api_key)
        try:
            response = client.responses.create(
                model=model,
                tools=[{"type": "web_search_preview"}],
                input=prompt,
            )
            raw = response.output_text or ""
        except Exception as primary_exc:
            primary_err = str(primary_exc)
            log.error(
                "FDA LLM fallback: model='%s' failed: %s", model, primary_err
            )
            # If the primary model is not found / not supported, try the full
            # search-preview variant as a one-time fallback.
            fallback_model = (
                "gpt-4o-search-preview"
                if "mini" in model
                else "gpt-4o-mini-search-preview"
            )
            if fallback_model == model:
                return []
            log.warning(
                "FDA LLM fallback: retrying with fallback model '%s'", fallback_model
            )
            try:
                response = client.responses.create(
                    model=fallback_model,
                    tools=[{"type": "web_search_preview"}],
                    input=prompt,
                )
                raw = response.output_text or ""
            except Exception as fallback_exc:
                log.error(
                    "FDA LLM fallback: fallback model '%s' also failed: %s",
                    fallback_model, fallback_exc,
                )
                return []
    except Exception as exc:
        log.error("FDA LLM fallback: OpenAI client init failed: %s", exc)
        return []

    if not raw:
        log.warning("FDA LLM fallback: empty response")
        return []

    log.info("FDA LLM fallback: raw response (%d chars): %s", len(raw), raw[:500])

    # Parse structured output
    _FDA_ITEM_RE = re.compile(
        r"TITLE:\s*(.+?)\s*\n"
        r"DATE:\s*(\S+)\s*\n"
        r"URL:\s*(\S+)\s*\n"
        r"SUMMARY:\s*(.+?)(?=\nTITLE:|\Z)",
        re.DOTALL,
    )

    items: list[FDAItem] = []
    for m in _FDA_ITEM_RE.finditer(raw):
        title   = m.group(1).strip()
        raw_date = m.group(2).strip()
        url     = m.group(3).strip()
        summary = m.group(4).strip()

        if not title or not summary:
            continue

        pub_date_obj, pub_date_str = _parse_fda_date(raw_date)
        if pub_date_obj and pub_date_obj < cutoff:
            continue

        # Apply the same oncology filter as the other sources
        if not _ONCO_RE.search(f"{title} {summary}"):
            continue

        uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        items.append(FDAItem(
            uid=uid,
            title=title,
            summary=summary,
            url=url,
            pub_date=pub_date_str,
            source="llm",
        ))

    log.info("FDA LLM fallback: %d items (cutoff=%s)", len(items), cutoff.isoformat())
    return items


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_fda_oncology_items(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,  # kept for API compat; page scrape already has full text
    openai_api_key: Optional[str] = None,
    llm_model: str = "gpt-4o-mini-search-preview",
) -> list[FDAItem]:
    """
    Fetch FDA oncology approval items within the lookback window.

    Strategy:
      1. Scrape the oncology approval notifications HTML page (primary).
         The page description column already contains the full indication text.
      2. If the page scrape yields 0 items, fall back to dual RSS feeds.
      3. If RSS also yields 0 items AND an openai_api_key is provided, fall
         back to LLM web search (handles GitHub Actions IPs blocked by FDA's
         Akamai CDN where both the HTML page and RSS feeds return 404).

    Args:
        lookback_days:    Days to look back (default 7).
        reference_date:   Window end date (default today).
        enrich_abstracts: Unused (kept for backward compat). Page scrape
                          already provides full indication text without a
                          secondary fetch.
        openai_api_key:   OpenAI API key for LLM web search fallback.
                          If None, LLM fallback is skipped.
        llm_model:        Model to use for LLM fallback.
                          Must support the web_search_preview tool.
                          Default: gpt-4o-mini-search-preview.
                          Standard gpt-4o-mini does NOT support web search
                          and will fail silently.
    """
    if reference_date is None:
        reference_date = date.today()
    cutoff = reference_date - timedelta(days=lookback_days)

    # ── Source 1: HTML approval notifications page (primary, Akamai-blocked on GHA) ──
    items = _scrape_approval_page(cutoff=cutoff)
    if not items:
        log.warning("FDA page scrape returned 0 items — trying RSS fallback")
        items = _fetch_rss_items(cutoff=cutoff)

    # ── Source 2: OpenFDA REST API (ALWAYS runs, not CDN-blocked) ────────────
    # This is the key fix for GitHub Actions: api.fda.gov is a public REST API
    # that is never blocked by Akamai.  Merge with HTML/RSS results by URL dedup
    # so we get coverage even when the HTML scrape returns nothing.
    openfda_items = _fetch_fda_via_openfda(cutoff=cutoff)
    if openfda_items:
        existing_urls = {i.url for i in items}
        new_from_api  = [i for i in openfda_items if i.url not in existing_urls]
        if new_from_api:
            log.info(
                "OpenFDA API: %d additional approval(s) not in HTML/RSS: %s",
                len(new_from_api),
                [i.title[:80] for i in new_from_api],
            )
        items = items + new_from_api

    # ── Source 3: LLM web search supplement (always runs when API key available) ─
    # Uses gpt-4o-mini-search-preview which supports web_search_preview.
    # Standard gpt-4o-mini does NOT support this tool and silently returns [].
    # This is the most reliable fallback for novel drug classes (oncolytic viruses,
    # TIL therapy, radioligands) that the OpenFDA pharm-class filter may miss,
    # and for cases where the HTML page is blocked by Akamai CDN (GitHub Actions).
    if openai_api_key:
        if not items:
            log.warning(
                "FDA HTML+RSS+OpenFDA all returned 0 items — running LLM as primary fallback"
            )
        else:
            log.info(
                "FDA LLM supplement: cross-checking %d item(s) — will add any missed approvals",
                len(items),
            )
        llm_items = _fetch_fda_via_llm(
            cutoff=cutoff, openai_api_key=openai_api_key, model=llm_model
        )
        if llm_items:
            existing_urls = {i.url for i in items}
            new_items = [i for i in llm_items if i.url not in existing_urls]
            if new_items:
                log.info(
                    "FDA LLM supplement: %d new item(s) not found by other sources: %s",
                    len(new_items),
                    [i.title[:80] for i in new_items],
                )
            items = items + new_items

    # ── Final dedup by URL ────────────────────────────────────────────────────
    seen: set[str] = set()
    deduped: list[FDAItem] = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            deduped.append(item)

    log.info(
        "FDA lane total: %d oncology approval items "
        "(lookback=%dd, cutoff=%s, page=%d, rss=%d, openfda=%d, llm=%d)",
        len(deduped),
        lookback_days,
        cutoff.isoformat(),
        sum(1 for i in deduped if i.source == "page"),
        sum(1 for i in deduped if i.source == "rss"),
        sum(1 for i in deduped if i.source == "openfda"),
        sum(1 for i in deduped if i.source == "llm"),
    )
    return deduped


def _item_to_pubmed_record(item: FDAItem) -> PubMedRecord:
    """
    Convert an FDAItem to a synthetic PubMedRecord so it flows through the
    standard pipeline. Key tags:
      - publication_types = ["FDA Drug Approval"]  → pubtype filter passes it
      - conference_source = "FDA"                  → pipeline force-keeps it
      - pmid = ""                                  → no PubMed identity
    """
    raw = f"FDA|{item.url}|{item.title}"
    text_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return PubMedRecord(
        pmid="",
        title=item.title,
        abstract=item.summary,
        journal="FDA Hematology-Oncology",
        pub_date=item.pub_date,
        publication_types=["FDA Drug Approval"],
        doi=None,
        pmc_id=None,
        nct_ids=[],
        mesh_terms=[],
        authors=["U.S. Food and Drug Administration"],
        language="eng",
        raw_xml=raw,
        text_hash=text_hash,
        conference_source="FDA",
    )


def retrieve_fda_records(
    lookback_days: int = 7,
    reference_date: Optional[date] = None,
    enrich_abstracts: bool = True,
    openai_api_key: Optional[str] = None,
    llm_model: str = "gpt-4o-mini-search-preview",
) -> list[PubMedRecord]:
    """
    Main entry point for the FDA ingestion lane.
    Returns synthetic PubMedRecord objects ready to merge into the pipeline.

    Pass openai_api_key to enable LLM web search as a third-tier fallback
    when the HTML page and RSS feeds are both unreachable (e.g. bot-blocked).
    """
    items = fetch_fda_oncology_items(
        lookback_days=lookback_days,
        reference_date=reference_date,
        enrich_abstracts=enrich_abstracts,
        openai_api_key=openai_api_key,
        llm_model=llm_model,
    )
    return [_item_to_pubmed_record(item) for item in items]
