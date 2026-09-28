"""
conftest.py — stubs for pipeline.py's heavy module-level imports.

pipeline.py imports a lot of internal modules that aren't available in the
isolated test environment (some require API keys, optional deps, or other
iCloud-only files).  We stub out only what's needed so the module-level code
in pipeline.py executes without error and the pure helpers (_date_is_fresh,
_date_is_fresh) are importable.

This file is auto-loaded by pytest for every test session that runs from
this directory.
"""
import sys
import types


def _stub(name: str, **attrs):
    """Create and register a minimal stub module."""
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


# ── carcinos_ingestion.config ─────────────────────────────────────────────────
ci = sys.modules.get("carcinos_ingestion") or _stub("carcinos_ingestion")
cfg = _stub("carcinos_ingestion.config", Config=object)
ci.config = cfg

# ── disease_sites ─────────────────────────────────────────────────────────────
class _FakeDiseaseSiteConfig:
    pass

ds = _stub(
    "carcinos_ingestion.disease_sites",
    get=lambda *a, **kw: _FakeDiseaseSiteConfig(),
)
ds_base = _stub(
    "carcinos_ingestion.disease_sites.base",
    DiseaseSiteConfig=_FakeDiseaseSiteConfig,
    TIER1_JOURNAL_WHITELIST=[],
    SITE_QUICK_TERMS={},
)
ci.disease_sites = ds

# ── filters ───────────────────────────────────────────────────────────────────
filters = _stub("carcinos_ingestion.filters")
_stub("carcinos_ingestion.filters.dedupe",   dedupe=lambda *a, **kw: [])
_stub("carcinos_ingestion.filters.pubtype",  filter_by_pubtype=lambda *a, **kw: [])
_stub("carcinos_ingestion.filters.relevance",score_relevance=lambda *a, **kw: 0)
_stub(
    "carcinos_ingestion.filters.signal_score",
    SignalResult=object,
    score_signal=lambda *a, **kw: None,
    SIGNAL_LABELS=[],
)
ci.filters = filters

# ── normalize ─────────────────────────────────────────────────────────────────
_stub("carcinos_ingestion.normalize")
_stub(
    "carcinos_ingestion.normalize.canonical",
    to_canonical=lambda *a, **kw: None,
    CanonicalCandidate=object,
)

# ── triage ────────────────────────────────────────────────────────────────────
_stub("carcinos_ingestion.triage")
_stub("carcinos_ingestion.triage.openai_client", OpenAIClient=object)
_stub(
    "carcinos_ingestion.triage.pass1",
    Pass1Result=object,
    run_pass1=lambda *a, **kw: None,
    enforce_pass1_keep_rules=lambda *a, **kw: None,
)
_stub(
    "carcinos_ingestion.triage.pass2",
    run_pass2=lambda *a, **kw: None,
    run_pass2_guideline=lambda *a, **kw: None,
    verify_evidence_quotes=lambda *a, **kw: None,
    Pass2Result=object,
)
_stub("carcinos_ingestion.triage.context_brief", generate_context_brief=lambda *a, **kw: "")

# ── retrieval ─────────────────────────────────────────────────────────────────
_stub("carcinos_ingestion.retrieval")
_stub("carcinos_ingestion.retrieval.web_search", run_web_search_lane=lambda *a, **kw: [])
# NOTE: pubmed is NOT stubbed — the real module is available and under test.
