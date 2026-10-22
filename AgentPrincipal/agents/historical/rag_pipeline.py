"""
rag_pipeline.py — Pipeline RAG adapté pour Dourbia (Windows, sans pgvector)

Remplace SemanticRetriever de l'agent historique original.
Utilise FLOAT[] + similarité cosinus numpy sur sig_dourbia:5432.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# Poids du score hybride (identiques à l'original)
VECTOR_WEIGHT = 0.75
KEYWORD_WEIGHT = 0.15
SOURCE_TYPE_WEIGHT = 0.10

# Nombre de candidats vectoriels avant reranking
VECTOR_CANDIDATES = 20
DEFAULT_TOP_K = 5


@dataclass
class RetrievedChunk:
    source_type: str
    source_id: float
    title: str | None
    score: float
    chunk_text: str
    metadata: dict[str, Any]
    vector_score: float = 0.0
    keyword_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "score": self.score,
            "chunk_text": self.chunk_text,
            "metadata": self.metadata,
            "vector_score": self.vector_score,
            "keyword_score": self.keyword_score,
        }


class HistoricalRAGPipeline:
    """
    Retrieval hybride (cosinus numpy + keyword + intent scoring).
    Se connecte directement à sig_dourbia sans SQLAlchemy ni pgvector.
    """

    def __init__(self, db_url: str) -> None:
        # INTEGRATION NOTE: db_url au format psycopg2 standard
        # ex: "postgresql://postgres:password@localhost:5432/sig_dourbia"
        self._db_url = db_url
        self._conn: psycopg2.extensions.connection | None = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        """Connexion lazy avec reconnexion automatique."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                self._db_url,
                options="-c client_encoding=UTF8",
            )
        return self._conn

    def retrieve(
        self,
        query: str,
        query_embedding: list[float],
        *,
        top_k: int = DEFAULT_TOP_K,
        source_type: str | None = None,
        language: str | None = None,
        destination: str | None = None,
        site_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Récupère les chunks les plus pertinents.

        Args:
            query: Texte de la requête (pour scoring keyword).
            query_embedding: Vecteur de la requête (384 dims, calculé par Aziz).
            top_k: Nombre de résultats à retourner.
            source_type: Filtre optionnel ('monument', 'circuit').
            language: Filtre optionnel ('fr', 'en', 'ar').
            destination: Filtre optionnel sur metadata_json->destination_name.
            site_id: Filtre optionnel sur metadata_json->site_id.
        """
        query_vec = np.array(query_embedding, dtype=np.float32)

        # 1. Récupérer les candidats depuis PostgreSQL
        rows = self._fetch_candidates(
            source_type=source_type,
            language=language,
            destination=destination,
            site_id=site_id,
            limit=VECTOR_CANDIDATES,
        )
        if not rows:
            return []

        # 2. Calculer la similarité cosinus pour chaque chunk
        chunks = self._score_candidates(rows, query_vec, query)

        # 3. Filtrer les doublons par source
        chunks = self._deduplicate(chunks)

        # 4. Trier par score final et retourner top_k
        chunks.sort(key=lambda c: c.score, reverse=True)
        return [c.to_dict() for c in chunks[:top_k]]

    def _fetch_candidates(
        self,
        *,
        source_type: str | None,
        language: str | None,
        destination: str | None,
        site_id: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Récupère les chunks avec leurs embeddings depuis historical_chunks."""
        conn = self._get_conn()

        conditions = ["embedding IS NOT NULL"]
        params: list[Any] = []

        if source_type:
            conditions.append("source_type = %s")
            params.append(source_type.strip())

        if language:
            conditions.append("language = %s")
            params.append(language.strip())

        if destination:
            conditions.append("metadata_json->>'destination_name' ILIKE %s")
            params.append(f"%{destination.strip()}%")

        if site_id is not None:
            conditions.append("(metadata_json->>'site_id')::int = %s")
            params.append(site_id)

        where_clause = " AND ".join(conditions)
        

        sql = f"""
            SELECT
                id,
                source_type,
                source_id::float,
                title,
                language,
                chunk_text,
                metadata_json,
                embedding
            FROM historical_chunks
            WHERE {where_clause}
           
        """

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            conn.rollback()
            raise

    def _score_candidates(
        self,
        rows: list[dict[str, Any]],
        query_vec: np.ndarray,
        query: str,
    ) -> list[RetrievedChunk]:
        """Calcule le score hybride cosinus + keyword pour chaque candidat."""
        chunks: list[RetrievedChunk] = []
        query_norm = _normalize_text(query)

        for row in rows:
            raw_embedding = row.get("embedding")
            if raw_embedding is None:
                continue

            # Similarité cosinus via numpy (remplace pgvector)
            chunk_vec = np.array(raw_embedding, dtype=np.float32)
            vector_score = float(_cosine_similarity(query_vec, chunk_vec))

            # Score keyword (overlap de tokens)
            keyword_score = _token_overlap_score(
                query_norm,
                _normalize_text(row.get("title") or ""),
                _normalize_text(row.get("chunk_text") or ""),
            )

            # Score source_type selon intent détecté dans la query
            source_score = _source_type_score(row["source_type"], query_norm)

            # Score hybride final
            final_score = (
                VECTOR_WEIGHT * vector_score
                + KEYWORD_WEIGHT * keyword_score
                + SOURCE_TYPE_WEIGHT * source_score
            )

            chunks.append(RetrievedChunk(
                source_type=row["source_type"],
                source_id=float(row["source_id"]),
                title=row.get("title"),
                score=final_score,
                chunk_text=row["chunk_text"],
                metadata=dict(row.get("metadata_json") or {}),
                vector_score=vector_score,
                keyword_score=keyword_score,
            ))

        return chunks

    def _deduplicate(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Garde le meilleur chunk par (source_type, source_id)."""
        best: dict[tuple[str, float], RetrievedChunk] = {}
        for chunk in chunks:
            key = (chunk.source_type, chunk.source_id)
            if key not in best or chunk.score > best[key].score:
                best[key] = chunk
        return list(best.values())

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()


# ─── Helpers purs ────────────────────────────────────────────────────────────

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similarité cosinus entre deux vecteurs numpy."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _normalize_text(text: str) -> str:
    """Normalisation légère : minuscules, suppression accents de base."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _token_overlap_score(
    query_norm: str,
    title_norm: str,
    chunk_norm: str,
) -> float:
    """Score d'overlap de tokens entre la requête et le chunk (titre + texte)."""
    query_tokens = set(query_norm.split())
    if not query_tokens:
        return 0.0
    target_tokens = set((title_norm + " " + chunk_norm).split())
    overlap = query_tokens & target_tokens
    return len(overlap) / len(query_tokens)


# Mots-clés pour détecter l'intent (monument vs circuit)
_CIRCUIT_KEYWORDS = {"circuit", "parcours", "itineraire", "velo", "cyclable", "pedestre", "etapes"}
_MONUMENT_KEYWORDS = {"monument", "site", "basilique", "theatre", "thermes", "tophet", "byrsa",
                      "odeon", "necropole", "musee", "histoire", "historique", "explique"}


def _source_type_score(source_type: str, query_norm: str) -> float:
    """Score de pertinence du type de source selon l'intent détecté."""
    tokens = set(query_norm.split())
    circuit_hits = len(tokens & _CIRCUIT_KEYWORDS)
    monument_hits = len(tokens & _MONUMENT_KEYWORDS)

    if circuit_hits > monument_hits:
        return 1.0 if source_type == "circuit" else 0.0
    if monument_hits > circuit_hits:
        return 1.0 if source_type == "monument" else 0.0
    return 0.5  # intent mixte
