from __future__ import annotations

from dataclasses import dataclass

from app.rag.query_intent import QueryIntent, source_type_score
from app.rag.text_utils import token_overlap_score

VECTOR_WEIGHT = 0.75
KEYWORD_WEIGHT = 0.15
SOURCE_TYPE_WEIGHT = 0.10


@dataclass
class HybridScore:
    vector_score: float
    keyword_score: float
    source_type_component: float
    final_score: float


def compute_hybrid_score(
    query: str,
    title: str | None,
    chunk_text: str | None,
    source_type: str,
    vector_score: float,
    intent: QueryIntent,
) -> HybridScore:
    keyword_score = token_overlap_score(query, title, chunk_text)
    source_type_component = source_type_score(source_type, intent)
    final_score = (
        VECTOR_WEIGHT * vector_score
        + KEYWORD_WEIGHT * keyword_score
        + SOURCE_TYPE_WEIGHT * source_type_component
    )
    return HybridScore(
        vector_score=vector_score,
        keyword_score=keyword_score,
        source_type_component=source_type_component,
        final_score=final_score,
    )
