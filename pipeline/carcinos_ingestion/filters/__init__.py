from .dedupe import dedupe, hard_dedupe, fuzzy_dedupe, journal_rank
from .pubtype import classify, filter_by_pubtype, PubTypeDecision
from .relevance import score_relevance, score_batch, RelevanceResult

__all__ = [
    "dedupe", "hard_dedupe", "fuzzy_dedupe", "journal_rank",
    "classify", "filter_by_pubtype", "PubTypeDecision",
    "score_relevance", "score_batch", "RelevanceResult",
]
