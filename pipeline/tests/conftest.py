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
    # Register with Python's module cache so imports resolve to the stub.
    sys.modules[name] = m
    # Also attach as an attribute on the parent package so dotted access works.
    parts = name.rsplit(".", 1)
    if len(parts) == 2:
        parent_name, child_name = parts
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, child_name, m)
    return m


# IMPORTANT: Do NOT stub `carcinos_ingestion` itself — the real package must
# remain importable as a proper package (with __path__) so that subpackages
# like .retrieval.pubmed and .filters can be found on disk.

# ── carcinos_ingestion.config ─────────────────────────────────────────────────
_stub("carcinos_ingestion.config", Config=object)

# ── disease_sites ─────────────────────────────────────────────────────────────
class _FakeDiseaseSiteConfig:
    pass

_stub(
    "carcinos_ingestion.disease_sites",
    get=lambda *a, **kw: _FakeDiseaseSiteConfig(),
    __path__=[],          # pretend to be a package so child imports don't fail
)
_stub(
    "carcinos_ingestion.disease_sites.base",
    DiseaseSiteConfig=_FakeDiseaseSiteConfig,
    TIER1_JOURNAL_WHITELIST=[],
    SITE_QUICK_TERMS={},
    _or_block=lambda *a, **kw: "",
)

# ── filters ───────────────────────────────────────────────────────────────────
_stub("carcinos_ingestion.filters", __path__=[])
_stub("carcinos_ingestion.filters.dedupe",    dedupe=lambda *a, **kw: [])
_stub("carcinos_ingestion.filters.pubtype",   filter_by_pubtype=lambda *a, **kw: [])
_stub("carcinos_ingestion.filters.relevance", score_relevance=lambda *a, **kw: 0)
_stub(
    "carcinos_ingestion.filters.signal_score",
    SignalResult=object,
    SignalScore=object,
    score_signal=lambda *a, **kw: None,
    score_candidate=lambda *a, **kw: None,
    SIGNAL_LABELS=[],
    QS_NONE="QS_NONE",
    QS_FORCE_KEEP="QS_FORCE_KEEP",
    _journal_is_top_tier=lambda *a, **kw: False,
)

# ── normalize ─────────────────────────────────────────────────────────────────
_stub("carcinos_ingestion.normalize", __path__=[])
_stub(
    "carcinos_ingestion.normalize.canonical",
    to_canonical=lambda *a, **kw: None,
    CanonicalCandidate=object,
)

# ── triage ────────────────────────────────────────────────────────────────────
_stub("carcinos_ingestion.triage", __path__=[])
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

# ── retrieval (partial) ───────────────────────────────────────────────────────
# Only web_search is stubbed; pubmed.py is the real module under test and must
# NOT be stubbed.  We do NOT register carcinos_ingestion.retrieval itself so
# that Python can find the real retrieval/ package on disk.
_stub("carcinos_ingestion.retrieval.web_search", run_web_search_lane=lambda *a, **kw: [])
