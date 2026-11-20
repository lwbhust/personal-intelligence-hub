"""Phase 4 event intelligence: deterministic text, entity, clustering,
lifecycle, relation, summary and scoring primitives.

Nothing in this package talks to SQLite or the network; services own
persistence and provider calls. This keeps the core algorithms testable and
gives the product a deterministic fallback when the local model is absent.
"""

from __future__ import annotations

from .clustering import (
    ArticleFeatures,
    EventFeatures,
    PairScore,
    decide,
    score_article_against_event,
)
from .entities import (
    alias_variants,
    clean_entity_name,
    entity_type_of,
    normalized_key,
)
from .lifecycle import next_status
from .relations import RelationCandidate, generate_relation_candidates
from .scoring import ScoreInputs, ScoreResult, compute_scores
from .summary import build_event_summary
from .text import jaccard, time_decay, title_similarity, tokens

__all__ = [
    "ArticleFeatures",
    "EventFeatures",
    "PairScore",
    "RelationCandidate",
    "ScoreInputs",
    "ScoreResult",
    "alias_variants",
    "build_event_summary",
    "clean_entity_name",
    "compute_scores",
    "decide",
    "entity_type_of",
    "generate_relation_candidates",
    "jaccard",
    "next_status",
    "normalized_key",
    "score_article_against_event",
    "time_decay",
    "title_similarity",
    "tokens",
]
