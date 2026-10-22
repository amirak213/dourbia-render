from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol, runtime_checkable

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@runtime_checkable
class Reranker(Protocol):
    """Abstraction for a neural (learned) query/passage relevance scorer."""

    @property
    def model_name(self) -> str: ...

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    """Neural reranker backed by a sentence-transformers CrossEncoder.

    Remplace le scoring heuristique à poids fixes (vector + token-overlap +
    type de source) par un modèle réellement entraîné à évaluer la pertinence
    query/passage. Contrairement à l'embedding bi-encoder (qui encode query et
    passage séparément), le cross-encoder les lit ensemble, ce qui donne un
    score de pertinence bien plus fin — au prix d'un coût par paire, donc à
    n'appliquer qu'sur le shortlist de candidats déjà récupérés par la
    recherche vectorielle, jamais sur tout le corpus.
    """

    def __init__(self, model_name: str, *, device: str = "cpu") -> None:
        from sentence_transformers import CrossEncoder

        self._model_name = model_name
        logger.info("Loading cross-encoder reranker %s on %s", model_name, device)
        self._model = CrossEncoder(model_name, device=device)

    @property
    def model_name(self) -> str:
        return self._model_name

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        pairs = [(query, passage) for passage in passages]
        raw_scores = self._model.predict(pairs)
        return [float(score) for score in raw_scores]


@lru_cache(maxsize=1)
def _cached_reranker() -> Reranker | None:
    """Charge le modèle une seule fois par process (comme pour les embeddings)."""
    return _create_reranker(get_settings())


def create_reranker(settings: Settings | None = None) -> Reranker | None:
    """Retourne le reranker configuré, ou None s'il est désactivé ou indisponible.

    Ne lève jamais d'exception : un reranker manquant/en échec doit dégrader
    gracieusement vers le scoring heuristique existant (voir retriever.py),
    pas casser la recherche.
    """
    if settings is None:
        return _cached_reranker()
    return _create_reranker(settings)


def _create_reranker(settings: Settings) -> Reranker | None:
    if not settings.reranker_enabled:
        return None
    try:
        return CrossEncoderReranker(
            settings.reranker_model_name, device=settings.reranker_device
        )
    except Exception:
        logger.exception(
            "Échec du chargement du reranker cross-encoder %r ; "
            "retour au scoring heuristique (vector + keyword + source_type).",
            settings.reranker_model_name,
        )
        return None
