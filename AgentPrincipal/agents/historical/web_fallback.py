"""
web_fallback.py — Recherche web DuckDuckGo (HTML scraping via httpx) pour l'Agent Historique

Activé uniquement si WEB_SEARCH_ENABLED=true et RAG insuffisant.

Implémentation directe via httpx contre https://html.duckduckgo.com/html/
plutôt que via le package duckduckgo_search (qui utilise le binding Rust
`primp` en interne — observé comme bloquant indéfiniment dans cet
environnement réseau, sans lever d'exception ni respecter les timeouts).
"""

from __future__ import annotations

import logging
from typing import Any
from ddgs import DDGS

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 8.0
# Mots-clés pour filtrer les résultats non pertinents (Carthage Tunisie uniquement)
_RELEVANCE_KEYWORDS = {
    "carthage",
    "tunisie",
    "tunisia",
    "tunisian",
    "punique",
    "punic",
    "romain",
    "roman",
    "byrsa",
    "tophet",
    "hamilcar",
    "hannibal",
    "baal",
    "tanit",
    "magon",
    "thermes",
    "antonin",
    "patrimoine",
}


def search_web(
    query: str, *, language: str = "fr", max_results: int = 3
) -> list[dict[str, Any]]:
    """
    Effectue une recherche DuckDuckGo (scraping HTML direct) et filtre
    les résultats pertinents.

    Returns:
        Liste de dicts {"title": str, "body": str, "url": str}
    """
    cleaned_query = " ".join(query.split()).strip()
    if not cleaned_query:
        return []

    enriched_query = _enrich_query(cleaned_query, language)
    region = "fr-fr" if language == "fr" else ("us-en" if language == "en" else "wt-wt")

    try:
        with DDGS(timeout=REQUEST_TIMEOUT) as ddgs:
            raw_results = list(
                ddgs.text(enriched_query, region=region, max_results=max_results * 2)
            )
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []

    try:
        normalized = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
            for r in raw_results
        ]
        filtered = [r for r in normalized if _is_relevant(r)]
    except Exception as exc:
        logger.warning("DuckDuckGo result filtering failed: %s", exc)
        return []

    return filtered[:max_results]




def _enrich_query(query: str, language: str) -> str:
    """Ajoute 'Carthage Tunisie' si pas déjà présent."""
    lower = query.lower()
    if "carthage" not in lower and "tunisie" not in lower and "tunisia" not in lower:
        suffix = "Carthage Tunisie" if language == "fr" else "Carthage Tunisia"
        return f"{query} {suffix}"
    return query


def _is_relevant(result: dict[str, Any]) -> bool:
    """Vérifie si un résultat web est pertinent pour Carthage/patrimoine tunisien."""
    text = " ".join(
        [
            (result.get("title") or "").lower(),
            (result.get("body") or "").lower(),
        ]
    )
    return any(keyword in text for keyword in _RELEVANCE_KEYWORDS)
