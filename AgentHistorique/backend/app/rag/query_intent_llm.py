from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.llm.llm_client import (
    ChatMessage,
    LLMClient,
    LLMClientError,
    ToolDefinition,
)
from app.rag.web_search_decision import (
    is_art_or_culture_query,
    is_domain_related_query,
    is_historical_figure_query,
    is_local_context_insufficient,
    local_chunks_relevant_to_query,
    requests_archaeology_news,
    requests_event_or_schedule,
    user_requests_lookup,
    user_requests_web_search,
)

logger = logging.getLogger(__name__)

_TOOL_NAME = "classify_historical_query_intent"

CLASSIFY_INTENT_TOOL: ToolDefinition = {
    "name": _TOOL_NAME,
    "description": (
        "Classifie l'intention d'une question utilisateur adressée à un agent "
        "spécialisé sur l'histoire, l'archéologie et le patrimoine culturel "
        "tunisien (Carthage, guerres puniques, monuments, personnages "
        "historiques), afin de décider si une recherche web est nécessaire."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "is_domain_related": {
                "type": "boolean",
                "description": (
                    "La question concerne l'histoire, l'archéologie ou le "
                    "patrimoine culturel tunisien."
                ),
            },
            "explicit_web_request": {
                "type": "boolean",
                "description": (
                    "L'utilisateur demande explicitement une recherche web "
                    "('cherche sur internet', 'fais une recherche', etc.)."
                ),
            },
            "requests_archaeology_news": {
                "type": "boolean",
                "description": (
                    "La question porte sur des découvertes archéologiques "
                    "récentes ou une actualité liée au patrimoine."
                ),
            },
            "is_art_or_culture": {
                "type": "boolean",
                "description": (
                    "La question porte sur une oeuvre d'art, la culture ou "
                    "une production culturelle (ex. Salammbô, une exposition)."
                ),
            },
            "is_historical_figure": {
                "type": "boolean",
                "description": (
                    "La question porte sur un personnage historique précis "
                    "(ex. Hannibal, Didon, Scipion)."
                ),
            },
            "requests_event_or_schedule": {
                "type": "boolean",
                "description": (
                    "La question porte sur un évènement, horaire, date "
                    "d'ouverture ou programme actuel."
                ),
            },
            "user_requests_lookup": {
                "type": "boolean",
                "description": (
                    "L'utilisateur demande de vérifier/rechercher une "
                    "information précise plutôt qu'un résumé général."
                ),
            },
        },
        "required": [
            "is_domain_related",
            "explicit_web_request",
            "requests_archaeology_news",
            "is_art_or_culture",
            "is_historical_figure",
            "requests_event_or_schedule",
            "user_requests_lookup",
        ],
    },
}


@dataclass(frozen=True)
class QueryIntentFlags:
    is_domain_related: bool
    explicit_web_request: bool
    requests_archaeology_news: bool
    is_art_or_culture: bool
    is_historical_figure: bool
    requests_event_or_schedule: bool
    user_requests_lookup: bool
    source: str  # "llm" ou "regex_fallback", utile pour les logs/observabilité


def classify_query_intent(
    llm_client: LLMClient,
    user_query: str,
    memory_context: dict[str, Any],
) -> QueryIntentFlags:
    """Classifie l'intention via tool-calling LLM, avec fallback regex.

    Ne lève jamais d'exception : toute erreur (provider down, JSON invalide,
    champ manquant) retombe sur `_classify_via_regex`, qui donne exactement
    le même comportement qu'avant l'introduction du tool-calling.
    """
    try:
        return _classify_via_llm(llm_client, user_query, memory_context)
    except (LLMClientError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "LLM intent classification failed (%s); falling back to regex heuristics.",
            exc,
        )
        return _classify_via_regex(user_query, memory_context)


def _classify_via_llm(
    llm_client: LLMClient,
    user_query: str,
    memory_context: dict[str, Any],
) -> QueryIntentFlags:
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": (
                "Tu classifies l'intention de questions posées à un agent "
                "historique tunisien spécialisé sur Carthage. Réponds "
                "uniquement en appelant l'outil fourni, avec des valeurs "
                "booléennes fidèles au contenu réel de la question — "
                "n'invente rien, ne suppose pas d'intention non exprimée."
            ),
        },
        {"role": "user", "content": user_query},
    ]

    response = llm_client.complete_with_tools(
        messages,
        [CLASSIFY_INTENT_TOOL],
        tool_choice="required",
        temperature=0.0,
        max_tokens=500,
    )
    if response.finish_reason == "length":
        raise ValueError(
            f"LLM response truncated (finish_reason=length) during intent "
            f"classification; tool_calls={len(response.tool_calls)}."
     )

    if not response.tool_calls:
        raise ValueError("LLM did not return a tool call for intent classification.")

    call = next(
        (tc for tc in response.tool_calls if tc.name == _TOOL_NAME),
        response.tool_calls[0],
    )
    args = call.arguments

    return QueryIntentFlags(
        is_domain_related=bool(args["is_domain_related"]),
        explicit_web_request=bool(args["explicit_web_request"]),
        requests_archaeology_news=bool(args["requests_archaeology_news"]),
        is_art_or_culture=bool(args["is_art_or_culture"]),
        is_historical_figure=bool(args["is_historical_figure"]),
        requests_event_or_schedule=bool(args["requests_event_or_schedule"]),
        user_requests_lookup=bool(args["user_requests_lookup"]),
        source="llm",
    )


def _classify_via_regex(
    user_query: str,
    memory_context: dict[str, Any],
) -> QueryIntentFlags:
    """Reproduit exactement l'ancien comportement 100% regex (fallback)."""
    return QueryIntentFlags(
        is_domain_related=is_domain_related_query(user_query, memory_context),
        explicit_web_request=user_requests_web_search(user_query),
        requests_archaeology_news=requests_archaeology_news(user_query, memory_context),
        is_art_or_culture=is_art_or_culture_query(user_query, memory_context),
        is_historical_figure=is_historical_figure_query(user_query),
        requests_event_or_schedule=requests_event_or_schedule(user_query),
        user_requests_lookup=user_requests_lookup(user_query),
        source="regex_fallback",
    )


def should_use_web_search_from_flags(
    flags: QueryIntentFlags,
    user_query: str,
    retrieved_chunks: list[dict[str, Any]],
    best_score: float | None,
    memory_context: dict[str, Any],
    *,
    settings: Settings,
) -> bool:
    """Équivalent structuré de `web_search_decision.should_use_web_search`,
    mais consommant les flags déjà classifiés au lieu de ré-exécuter les
    regex en interne (la fonction regex d'origine reste inchangée et
    disponible telle quelle en fallback/tests)."""
    if flags.explicit_web_request:
        return True

    if not flags.is_domain_related:
        return False

    if not settings.web_search_enabled:
        return False

    if flags.requests_archaeology_news:
        return True

    local_relevant = local_chunks_relevant_to_query(
        user_query, retrieved_chunks, memory_context
    )

    if flags.is_art_or_culture and not local_relevant:
        return True

    if flags.is_historical_figure and not local_relevant:
        return True

    if flags.requests_event_or_schedule or (
        flags.user_requests_lookup and flags.is_domain_related
    ):
        return True

    return is_local_context_insufficient(
        retrieved_chunks,
        best_score,
        min_relevance_score=settings.rag_min_score,
    )
