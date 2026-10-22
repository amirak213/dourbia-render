from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol, runtime_checkable

from app.config import Settings, get_settings
from app.models.document_chunk import EMBEDDING_DIMENSION

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Abstraction for embedding models used by indexing and retrieval."""

    @property
    def model_name(self) -> str:
        ...

    @property
    def dimension(self) -> int:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class SentenceTransformerEmbeddingProvider:
    """Local embedding provider backed by sentence-transformers."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        document_prefix: str = "",
        query_prefix: str = "",
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix
        logger.info("Loading embedding model %s on %s", model_name, device)
        self._model = SentenceTransformer(model_name, device=device)
        probe = self._model.encode("dimension probe", convert_to_numpy=True)
        self._dimension = int(probe.shape[-1])

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prefixed = [self._apply_prefix(text, self._document_prefix) for text in texts]
        vectors = self._model.encode(
            prefixed,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        prefixed = self._apply_prefix(text, self._query_prefix)
        vector = self._model.encode(
            prefixed,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vector.tolist()

    def _apply_prefix(self, text: str, prefix: str) -> str:
        cleaned = text.strip()
        if not prefix:
            return cleaned
        if cleaned.startswith(prefix):
            return cleaned
        return f"{prefix}{cleaned}"


class E5EmbeddingProvider(SentenceTransformerEmbeddingProvider):
    """Embedding provider for intfloat E5 models."""

    def __init__(self, model_name: str, *, device: str = "cpu") -> None:
        super().__init__(
            model_name,
            device=device,
            document_prefix="passage: ",
            query_prefix="query: ",
        )


@lru_cache(maxsize=1)
def _cached_embedding_provider() -> EmbeddingProvider:
    """Load the embedding model once per process (avoids multi-second reload per request)."""
    return _create_embedding_provider(get_settings())


def create_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    if settings is None:
        return _cached_embedding_provider()
    return _create_embedding_provider(settings)


def _create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    model_name = settings.embedding_model_name

    if settings.embedding_provider == "e5":
        return E5EmbeddingProvider(model_name, device=settings.embedding_device)

    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformerEmbeddingProvider(
            model_name,
            device=settings.embedding_device,
        )

    raise ValueError(
        f"Unsupported embedding provider: {settings.embedding_provider!r}. "
        "Expected 'e5' or 'sentence-transformers'."
    )


def validate_embedding_dimension(provider: EmbeddingProvider) -> None:
    if provider.dimension != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Embedding model dimension ({provider.dimension}) does not match "
            f"document_chunks schema ({EMBEDDING_DIMENSION}). "
            "Update EMBEDDING_DIMENSION and run a migration before using this model."
        )
