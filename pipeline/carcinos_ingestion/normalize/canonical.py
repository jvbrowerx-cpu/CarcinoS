"""
Canonical input object for the LLM (spec §2.6).

The LLM only ever sees these fields. This guarantees:
  - Uniform input shape across sites
  - No raw HTML/XML reaching the model
  - Same fields available for triage and deep review
"""

from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Optional

from ..retrieval.pubmed import PubMedRecord
from ..filters.pubtype import PubTypeDecision
from ..filters.relevance import RelevanceResult
from ..disease_sites.base import DiseaseSiteConfig


@dataclass
class CanonicalCandidate:
    # Identity
    pmid: str
    doi: Optional[str]
    nct_ids: list[str]
    text_hash: str

    # Editorial-feed metadata
    title: str
    abstract: str
    journal: str
    publication_date: str
    publication_types: list[str]
    mesh_terms: list[str]

    # Site context
    cancer_site_code: str
    cancer_site_name: str
    modality_keywords_present: list[str]

    # Deterministic decisions made before the LLM
    deterministic_relevance_score: int
    deterministic_low_confidence: bool
    deterministic_rationale: list[str]
    pubtype_keep: bool
    pubtype_low_priority: bool
    pubtype_rationale: str
    force_keep_reason: Optional[str] = None

    # For the persistence layer
    raw_xml_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def to_canonical(
    record: PubMedRecord,
    config: DiseaseSiteConfig,
    pubtype_decision: PubTypeDecision,
    relevance: RelevanceResult,
    force_keep_reason: Optional[str] = None,
) -> CanonicalCandidate:
    # Surface which modality keywords actually fired (for prompt context)
    modalities_present = []
    text_lower = (record.title + "\n" + record.abstract).lower()
    for term in config.modality_terms:
        if term.lower() in text_lower:
            modalities_present.append(term)

    return CanonicalCandidate(
        pmid=record.pmid,
        doi=record.doi,
        nct_ids=list(record.nct_ids),
        text_hash=record.text_hash,
        title=record.title,
        abstract=record.abstract,
        journal=record.journal,
        publication_date=record.pub_date,
        publication_types=list(record.publication_types),
        mesh_terms=list(record.mesh_terms),
        cancer_site_code=config.code,
        cancer_site_name=config.name,
        modality_keywords_present=modalities_present[:12],
        deterministic_relevance_score=relevance.score,
        deterministic_low_confidence=relevance.low_confidence,
        deterministic_rationale=list(relevance.rationale),
        pubtype_keep=pubtype_decision.keep,
        pubtype_low_priority=pubtype_decision.low_priority,
        pubtype_rationale=pubtype_decision.rationale,
        force_keep_reason=force_keep_reason,
        raw_xml_hash=record.text_hash,
    )
