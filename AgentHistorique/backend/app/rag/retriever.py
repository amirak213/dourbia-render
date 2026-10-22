from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Integer, String, cast, or_, select
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.rag.embeddings import EmbeddingProvider, create_embedding_provider
from app.rag.query_intent import QueryIntent, QueryIntentType, detect_query_intent
from app.rag.scoring import HybridScore, compute_hybrid_score

DEFAULT_VECTOR_CANDIDATES = 10
DEFAULT_TOP_K = 5


@dataclass
class RetrievalFilters:
    source_type: str | None = None
    destination: str | None = None
    period: str | None = None
    language: str | None = None
    site_id: int | None = None


@dataclass
class RetrievedChunk:
    source_type: str
    source_id: Decimal
    title: str | None
    score: float
    chunk_text: str
    metadata: dict[str, Any]
    vector_score: float | None = None
    keyword_score: float | None = None
    source_type_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_type": self.source_type,
            "source_id": float(self.source_id),
            "title": self.title,
            "score": self.score,
            "chunk_text": self.chunk_text,
            "metadata": self.metadata,
        }
        if self.vector_score is not None:
            payload["vector_score"] = self.vector_score
        if self.keyword_score is not None:
            payload["keyword_score"] = self.keyword_score
        if self.source_type_score is not None:
            payload["source_type_score"] = self.source_type_score
        return payload


class SemanticRetriever:
    """Retrieve document chunks using pgvector and hybrid reranking."""

    def __init__(
        self,
        db: Session,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        vector_candidates: int = DEFAULT_VECTOR_CANDIDATES,
        candidate_multiplier: int | None = None,
    ) -> None:
        self._db = db
        self._embedding_provider = embedding_provider or create_embedding_provider()
        if candidate_multiplier is not None:
            self._vector_candidates = max(vector_candidates, candidate_multiplier)
        else:
            self._vector_candidates = vector_candidates

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        filters: RetrievalFilters | None = None,
    ) -> list[dict[str, Any]]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        intent = detect_query_intent(cleaned_query)
        if filters and filters.source_type:
            filtered_type = filters.source_type.strip().lower()
            if filtered_type == "monument":
                intent = QueryIntent(
                    intent_type=QueryIntentType.MONUMENT,
                    monument_score=1,
                    circuit_score=0,
                )
            elif filtered_type == "circuit":
                intent = QueryIntent(
                    intent_type=QueryIntentType.CIRCUIT,
                    monument_score=0,
                    circuit_score=1,
                )

        query_vector = self._embedding_provider.embed_query(cleaned_query)
        vector_limit = max(self._vector_candidates, top_k)
        rows = self._search(query_vector, vector_limit, filters)

        reranked = self._rerank(cleaned_query, rows, intent)
        deduplicated = self._deduplicate_by_source(reranked)
        return [row.to_dict() for row in deduplicated[:top_k]]

    def _search(
        self,
        query_vector: list[float],
        limit: int,
        filters: RetrievalFilters | None,
    ) -> list[RetrievedChunk]:
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        score_expr = (1 - distance).label("score")

        stmt = (
            select(
                DocumentChunk.source_type,
                DocumentChunk.source_id,
                DocumentChunk.title,
                DocumentChunk.chunk_text,
                DocumentChunk.metadata_json,
                score_expr,
            )
            .where(DocumentChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        stmt = self._apply_filters(stmt, filters)

        rows = self._db.execute(stmt).all()
        return [
            RetrievedChunk(
                source_type=row.source_type,
                source_id=row.source_id,
                title=row.title,
                score=float(row.score),
                chunk_text=row.chunk_text,
                metadata=dict(row.metadata_json or {}),
                vector_score=float(row.score),
            )
            for row in rows
        ]

    def _rerank(
        self,
        query: str,
        rows: list[RetrievedChunk],
        intent: QueryIntent,
    ) -> list[RetrievedChunk]:
        reranked: list[RetrievedChunk] = []
        for row in rows:
            vector_score = row.vector_score if row.vector_score is not None else row.score
            hybrid = compute_hybrid_score(
                query=query,
                title=row.title,
                chunk_text=row.chunk_text,
                source_type=row.source_type,
                vector_score=vector_score,
                intent=intent,
            )
            reranked.append(self._with_hybrid_score(row, hybrid))
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked

    def _with_hybrid_score(self, row: RetrievedChunk, hybrid: HybridScore) -> RetrievedChunk:
        return RetrievedChunk(
            source_type=row.source_type,
            source_id=row.source_id,
            title=row.title,
            score=hybrid.final_score,
            chunk_text=row.chunk_text,
            metadata=row.metadata,
            vector_score=hybrid.vector_score,
            keyword_score=hybrid.keyword_score,
            source_type_score=hybrid.source_type_component,
        )

    def _apply_filters(self, stmt: Any, filters: RetrievalFilters | None) -> Any:
        if filters is None:
            return stmt

        if filters.source_type:
            stmt = stmt.where(DocumentChunk.source_type == filters.source_type.strip())

        if filters.language:
            stmt = stmt.where(DocumentChunk.language == filters.language.strip())

        if filters.destination:
            destination = filters.destination.strip()
            stmt = stmt.where(
                DocumentChunk.metadata_json["destination_name"].astext.ilike(f"%{destination}%")
            )

        if filters.period:
            period = filters.period.strip()
            stmt = stmt.where(
                or_(
                    DocumentChunk.metadata_json["dominant_period"].astext.ilike(f"%{period}%"),
                    DocumentChunk.metadata_json["secondary_period"].astext.ilike(f"%{period}%"),
                    cast(DocumentChunk.metadata_json["dominant_periods"], String).ilike(
                        f"%{period}%"
                    ),
                )
            )

        if filters.site_id is not None:
            stmt = stmt.where(
                DocumentChunk.metadata_json["site_id"].astext.cast(Integer) == filters.site_id
            )

        return stmt

    def _deduplicate_by_source(self, rows: list[RetrievedChunk]) -> list[RetrievedChunk]:
        best_by_source: dict[tuple[str, Decimal], RetrievedChunk] = {}
        for row in rows:
            key = (row.source_type, row.source_id)
            existing = best_by_source.get(key)
            if existing is None or row.score > existing.score:
                best_by_source[key] = row

        deduplicated = list(best_by_source.values())
        deduplicated.sort(key=lambda row: row.score, reverse=True)
        return deduplicated
