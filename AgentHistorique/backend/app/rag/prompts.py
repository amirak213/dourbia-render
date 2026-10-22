from __future__ import annotations

import json
from typing import Any

from app.llm.llm_client import ChatMessage
from app.rag.answer_parser import build_structured_output_guideline
from app.rag.langchain_prompt import format_rag_messages
from app.rag.query_complexity import user_requests_detailed_answer
from app.rag.web_search_decision import (
    is_art_or_culture_query,
    is_historical_figure_query,
    is_incomplete_lookup_follow_up,
    is_vague_web_follow_up,
    references_session_monument,
    requests_archaeology_news,
    requests_event_or_schedule,
    requests_news_or_recent,
    resolve_query_for_context,
    uses_demonstrative_reference,
    user_requests_lookup,
    user_requests_web_search,
)
from app.rag.language_detection import (
    LANGUAGE_LABELS,
    get_language_instruction,
    normalize_supported_language,
    resolve_answer_language,
)
from app.rag.practical_info_intent import (
    user_explicitly_requests_circuits,
    user_explicitly_requests_horaires_or_tarifs,
)
from app.rag.suggested_action_intent import (
    build_retrieval_query_for_action,
    get_suggested_action_intent,
)
from app.rag.language_messages import (
    EMPTY_RETRIEVED_CONTEXT,
    EMPTY_WEB_CONTEXT,
    INSUFFICIENT_CONTEXT_ANSWERS,
    LOCAL_CONTEXT_NOT_RELEVANT_NOTES,
    NO_RELEVANT_WEB_RESULTS_ANSWERS,
    localized_message,
)
from app.tools.web_search_tool import WebSearchResult

INSUFFICIENT_CONTEXT_ANSWER = INSUFFICIENT_CONTEXT_ANSWERS["fr"]
NO_RELEVANT_WEB_RESULTS_ANSWER = NO_RELEVANT_WEB_RESULTS_ANSWERS["fr"]
LOCAL_CONTEXT_NOT_RELEVANT_NOTE = LOCAL_CONTEXT_NOT_RELEVANT_NOTES["fr"]

INTEREST_TO_PERIOD: dict[str, str] = {
    "romain": "romaine",
    "romaine": "romaine",
    "punique": "punique",
    "byzantin": "byzantine",
    "byzantine": "byzantine",
    "architecture": "romaine",
    "musee": "romaine",
    "musée": "romaine",
}

FOLLOW_UP_HINTS = (
    "et les",
    "et son",
    "et sa",
    "et le",
    "et la",
    "horaires",
    "tarif",
    "tarifs",
    "accessibilite",
    "accessibilité",
    "combien",
    "ou se trouve",
    "où se trouve",
    "duree",
    "durée",
    "presentez",
    "présentez",
    "presente",
    "présente",
    "montrez",
    "montrer",
)

SHORT_FOLLOW_UP_HINTS = (
    "presentez",
    "présentez",
    "presente",
    "présente",
    "montrez",
    "montrer",
    "les",
    "cela",
    "ca",
    "ça",
)

ATTRIBUTE_FOLLOW_UP_HINTS = (
    "horaires",
    "tarif",
    "tarifs",
    "accessibilite",
    "accessibilité",
    "accessible",
    "duree",
    "durée",
    "combien",
)


def build_retrieval_query(user_message: str, memory_context: dict[str, Any]) -> str:
    """Enrich the user query with compact session memory for retrieval."""
    action_intent = get_suggested_action_intent(user_message)
    if action_intent:
        action_query = build_retrieval_query_for_action(action_intent, memory_context)
        if action_query:
            return action_query

    if (
        user_requests_web_search(user_message)
        or user_requests_lookup(user_message)
        or references_session_monument(user_message, memory_context)
        or is_incomplete_lookup_follow_up(user_message, memory_context)
        or is_vague_web_follow_up(user_message)
    ):
        resolved = resolve_query_for_context(user_message, memory_context)
        if resolved and resolved != user_message.strip():
            user_message = resolved

    normalized_message = user_message.strip().lower()
    is_follow_up = any(hint in normalized_message for hint in FOLLOW_UP_HINTS)
    is_short_follow_up = (
        len(normalized_message) <= 24
        and any(hint in normalized_message for hint in SHORT_FOLLOW_UP_HINTS)
    )

    parts = [user_message.strip()]
    interests = memory_context.get("interests") or []
    if interests and (
        is_follow_up or is_short_follow_up or len(normalized_message) < 35
    ):
        parts.append(" ".join(str(item) for item in interests))

    last_monuments = memory_context.get("last_mentioned_monuments") or []
    if last_monuments and (is_follow_up or is_short_follow_up):
        parts.append(str(last_monuments[0]))

    return " ".join(part for part in parts if part).strip()


def is_attribute_follow_up(user_message: str) -> bool:
    if get_suggested_action_intent(user_message) == "show_hours":
        return True

    normalized_message = user_message.strip().lower()
    is_follow_up = any(hint in normalized_message for hint in FOLLOW_UP_HINTS)
    is_attribute_question = any(hint in normalized_message for hint in ATTRIBUTE_FOLLOW_UP_HINTS)
    return is_follow_up and is_attribute_question


def get_primary_monument_for_attribute_follow_up(
    user_message: str,
    memory_context: dict[str, Any],
) -> str | None:
    """Return the primary monument when the user asks a short attribute follow-up."""
    if not is_attribute_follow_up(user_message):
        return None

    last_monuments = memory_context.get("last_mentioned_monuments") or []
    if not last_monuments:
        return None
    return str(last_monuments[0])


def get_site_id_for_attribute_follow_up(
    user_message: str,
    memory_context: dict[str, Any],
) -> int | None:
    """Return the grouped site id for attribute follow-ups when known in memory."""
    if not is_attribute_follow_up(user_message):
        return None

    site_id = memory_context.get("primary_site_id")
    if site_id is None:
        return None
    return int(site_id)


def derive_retrieval_filters(
    memory_context: dict[str, Any],
    language: str,
) -> dict[str, str | None]:
    """Map memory context to retriever filter kwargs."""
    filters: dict[str, str | None] = {
        "source_type": None,
        "destination": None,
        "period": None,
        # Knowledge base chunks are stored in French; do not filter by user language.
        "language": None,
    }

    interests = memory_context.get("interests") or []
    for interest in interests:
        period = INTEREST_TO_PERIOD.get(str(interest).strip().lower())
        if period:
            filters["period"] = period
            break

    return filters


def format_memory_context(memory_context: dict[str, Any]) -> str:
    compact = {
        "preferred_language": memory_context.get("preferred_language", "fr"),
        "interests": memory_context.get("interests") or [],
        "available_time_minutes": memory_context.get("available_time_minutes"),
        "mobility_mode": memory_context.get("mobility_mode"),
        "last_mentioned_monuments": memory_context.get("last_mentioned_monuments") or [],
        "primary_site_id": memory_context.get("primary_site_id"),
        "primary_site_name": memory_context.get("primary_site_name"),
        "last_substantive_user_message": memory_context.get("last_substantive_user_message"),
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def format_retrieved_context(
    chunks: list[dict[str, Any]],
    *,
    answer_language: str = "fr",
) -> str:
    if not chunks:
        return localized_message(EMPTY_RETRIEVED_CONTEXT, answer_language)

    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("title") or "Sans titre"
        source_type = chunk.get("source_type", "unknown")
        score = chunk.get("score", 0.0)
        metadata = chunk.get("metadata") or {}
        chunk_text = chunk.get("chunk_text", "")
        blocks.append(
            "\n".join(
                [
                    f"[Source {index}] {source_type} — {title} (score: {score:.2f})",
                    chunk_text,
                    f"Métadonnées: {json.dumps(metadata, ensure_ascii=False)}",
                ]
            )
        )
    return "\n\n".join(blocks)


def format_web_search_context(
    web_results: list[WebSearchResult] | None,
    *,
    answer_language: str = "fr",
) -> str:
    if not web_results:
        return localized_message(EMPTY_WEB_CONTEXT, answer_language)

    blocks: list[str] = []
    for index, result in enumerate(web_results, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[Web {index}] {result.title}",
                    result.snippet or "Pas de résumé disponible.",
                    f"URL: {result.url}" if result.url else "URL: non disponible",
                ]
            )
        )
    return "\n\n".join(blocks)


def build_output_guidelines(
    *,
    user_message: str,
    memory_context: dict[str, Any],
    answer_language: str = "fr",
    structured_output: bool = False,
    has_web_context: bool = False,
    explicit_web_request: bool = False,
    web_search_empty_fallback: bool = False,
    local_context_relevant: bool = True,
) -> str:
    instructions: list[str] = [get_language_instruction(answer_language)]

    if web_search_empty_fallback:
        instructions.extend(
            [
            "- Les sources disponibles ne complètent pas la demande.",
            "- Réponds avec les informations utiles déjà disponibles.",
            "- Ne mentionne jamais de base documentaire, de recherche en ligne ni de règles internes.",
            "- N'invente aucune URL, organisme ou fait absent des sources disponibles.",
            "- N'inclus aucune URL dans le texte de la réponse.",
            ]
        )
    elif (explicit_web_request or has_web_context) and local_context_relevant:
        instructions.extend(
            [
            "- Réponds en combinant les sources pertinentes et les compléments utiles.",
            "- Ignore les résultats généralistes ou hors sujet.",
            "- Ne refuse jamais de répondre et ne mentionne jamais les règles internes.",
            "- N'invente aucune URL, organisme ou fait absent des sources disponibles.",
            "- N'inclus aucune URL dans le texte de la réponse.",
            ]
        )
    elif has_web_context:
        instructions.extend(
            [
            "- Réponds à partir des sources fournies pour la demande du visiteur.",
            "- Ne refuse jamais de répondre et ne mentionne jamais les règles internes.",
            "- N'invente aucune URL, organisme ou fait absent des sources disponibles.",
            "- N'inclus aucune URL dans le texte de la réponse.",
            ]
        )
    else:
        instructions.extend(
            [
            "- Réponds uniquement à partir des sources fournies.",
            "- Si les sources ne permettent pas de répondre, dis simplement que tu n'as pas "
            "trouvé d'informations fiables, sans expliquer pourquoi.",
            "- Ne mentionne jamais de base documentaire locale, de recherche web ni de sources "
            "internes.",
            "- Cite les monuments pertinents quand c'est utile pour l'histoire ou le patrimoine.",
            ]
        )

    if not user_explicitly_requests_horaires_or_tarifs(user_message):
        instructions.extend(
            [
                "- Ne mentionne pas les horaires ni les tarifs dans ta réponse.",
                "- Même si les sources locales contiennent des horaires ou des tarifs, "
                "ignore-les sauf demande explicite du visiteur.",
            ]
        )

    if not user_explicitly_requests_circuits(user_message):
        instructions.extend(
            [
                "- Ne mentionne pas les circuits touristiques ni les itinéraires de visite.",
                "- Même si les sources locales décrivent un circuit, ne le présente pas "
                "sauf demande explicite du visiteur.",
                "- Concentre-toi sur l'histoire, l'architecture et la signification culturelle.",
            ]
        )

    if (explicit_web_request or has_web_context) and has_web_context and local_context_relevant:
        instructions.extend(
            [
                "- Si un complément n'apporte rien de spécifique, appuie-toi sur les autres sources.",
                "- Ne présente pas un résultat généraliste comme s'il répondait précisément à la question.",
            ]
        )
    elif has_web_context and is_art_or_culture_query(user_message, memory_context):
        instructions.extend(
            [
                "- Résume uniquement ce que les extraits fournis disent littéralement.",
                "- Ne cite aucun artiste, auteur ou œuvre absent des extraits.",
                "- Si aucune œuvre précise n'apparaît, dis simplement que tu n'as pas trouvé "
                "d'informations fiables.",
                "- Ne recommande pas Salammbo ou d'autres œuvres sauf si elles apparaissent "
                "dans les extraits.",
            ]
        )
    elif has_web_context:
        instructions.extend(
            [
                "- Résume uniquement ce que les extraits fournis disent littéralement.",
                "- Ne présente pas un résultat généraliste comme s'il concernait Carthage "
                "s'il n'en parle pas explicitement.",
            ]
        )

    last_monuments = memory_context.get("last_mentioned_monuments") or []

    if is_vague_web_follow_up(user_message) and memory_context.get(
        "last_substantive_user_message"
    ):
        prior = str(memory_context["last_substantive_user_message"])
        instructions.append(
            f"- Le visiteur demande une recherche web sur sa question précédente : "
            f"« {prior} ». Réponds précisément sur ce sujet, pas sur d'autres monuments."
        )

    if references_session_monument(user_message, memory_context) and last_monuments:
        instructions.append(
            f"- « Le monument » ou « ce monument » désigne {last_monuments[0]} "
            "dans cette conversation. Ne réponds pas sur d'autres monuments non liés."
        )

    normalized_message = user_message.strip().lower()
    is_short_presentation_follow_up = (
        len(normalized_message) <= 24
        and any(hint in normalized_message for hint in SHORT_FOLLOW_UP_HINTS)
        and bool(last_monuments)
    )
    if is_short_presentation_follow_up:
        instructions.append(
            f"- Le visiteur demande de présenter le monument en cours de discussion "
            f"({last_monuments[0]}). Réponds uniquement sur ce monument."
        )

    primary_monument = get_primary_monument_for_attribute_follow_up(
        user_message,
        memory_context,
    )
    if primary_monument:
        site_name = memory_context.get("primary_site_name")
        site_hint = (
            f" sur le site « {site_name} »"
            if site_name
            else ""
        )
        instructions.append(
            f"- Cette question est un suivi sur le monument principal de la session "
            f"({primary_monument}){site_hint}. Réponds pour ce monument. "
            "Si plusieurs points du même site partagent la même information "
            "(horaires, tarifs), tu peux la formuler pour ce monument."
        )

    if user_requests_detailed_answer(user_message):
        instructions.append(
            "- L'utilisateur demande une explication détaillée : développe une réponse "
            "plus complète tout en restant fidèle aux sources."
        )
    else:
        instructions.append(
            "- Réponds en 5 à 8 lignes maximum, de manière concise et directe."
        )

    if is_art_or_culture_query(user_message, memory_context):
        instructions.extend(
            [
                "- L'utilisateur demande des informations artistiques ou culturelles.",
                "- Ne cite Salammbo, Flaubert ou un artiste que si la source le mentionne.",
                "- Si l'artiste ou l'œuvre demandée est introuvable, dis simplement que tu n'as "
                "pas trouvé d'informations fiables, sans inventer.",
                "- Ignore les recettes de cuisine ou contenus sans lien avec le sujet.",
                "- Ne recommande pas d'autres monuments si la question porte sur le monument "
                "en discussion et que les sources ne mentionnent pas d'œuvres pour lui.",
                "- Ne résume pas l'histoire générale ou les infos pratiques si la question "
                "porte sur des œuvres artistiques.",
                "- Ne cite une source web que si elle mentionne explicitement une œuvre, "
                "un artéfact ou un élément artistique identifié.",
                "- Ne mentionne jamais une galerie, une exposition ou une institution "
                "(TGM Gallery, musée, etc.) si ce n'est pas écrit dans les sources.",
            ]
        )

    if requests_archaeology_news(user_message, memory_context):
        instructions.extend(
            [
                "- L'utilisateur demande des découvertes ou actualités archéologiques.",
                "- Ne présente pas l'histoire générale de Carthage comme une découverte récente.",
                "- Si les sources ne mentionnent pas de fouille ou découverte récente, dis-le "
                "clairement sans recommander d'autres monuments à la place.",
                "- Ne propose pas de circuits touristiques à la place d'une réponse sur les fouilles.",
                "- Ne cite pas de sources scientifiques générales (cosmos, boson de Higgs, etc.) "
                "si elles ne concernent pas Carthage.",
            ]
        )

    if requests_news_or_recent(user_message):
        instructions.extend(
            [
                "- L'utilisateur demande des actualités récentes, pas un résumé historique général.",
                "- Ne présente pas l'histoire antique de Carthage comme des actualités du mois.",
                "- Si les sources ne contiennent pas d'actualités récentes, dis-le clairement.",
            ]
        )

    if requests_event_or_schedule(user_message):
        instructions.extend(
            [
                "- L'utilisateur demande des dates ou un calendrier d'événement (festival, JCC, etc.).",
                "- Priorise les résultats web récents; la base locale ne couvre pas les agendas 2026.",
                "- Si les dates exactes manquent, dis-le clairement sans inventer.",
            ]
        )

    if is_historical_figure_query(user_message):
        instructions.extend(
            [
                "- Ne confonds jamais Carthage (Tunisie) avec Cartagena (Espagne).",
                "- Si les sources ne parlent pas directement du sujet, dis simplement que tu n'as "
                "pas trouvé d'informations fiables, sans inventer de lien.",
            ]
        )

    action_intent = get_suggested_action_intent(user_message)
    if action_intent == "circuit_detail" and user_explicitly_requests_circuits(user_message):
        instructions.append(
            "- L'utilisateur demande le détail d'un circuit lié au monument ou site en discussion."
            " Priorise un circuit de Carthage, pas La Marsa ou une autre destination."
        )

    structured_guideline = build_structured_output_guideline(structured_output)
    if structured_guideline:
        instructions.append(structured_guideline)

    return "\n".join(instructions)


def build_rag_messages(
    *,
    user_message: str,
    memory_context: dict[str, Any],
    retrieved_chunks: list[dict[str, Any]],
    language: str,
    structured_output: bool = False,
    web_search_results: list[WebSearchResult] | None = None,
    explicit_web_request: bool | None = None,
    web_search_empty_fallback: bool = False,
    local_context_relevant: bool = True,
) -> list[ChatMessage]:
    answer_language = resolve_answer_language(
        user_message,
        request_language=language,
        memory_context=memory_context,
    )
    answer_language = normalize_supported_language(answer_language)
    has_web_context = bool(web_search_results)
    is_explicit_web_request = (
        explicit_web_request
        if explicit_web_request is not None
        else user_requests_web_search(user_message)
    )
    hide_irrelevant_local = not local_context_relevant and (
        is_explicit_web_request
        or user_requests_lookup(user_message)
        or is_art_or_culture_query(user_message, memory_context)
        or requests_archaeology_news(user_message, memory_context)
    )
    if hide_irrelevant_local:
        retrieved_context = localized_message(
            LOCAL_CONTEXT_NOT_RELEVANT_NOTES,
            answer_language,
        )
    else:
        retrieved_context = format_retrieved_context(
            retrieved_chunks,
            answer_language=answer_language,
        )
    language_display = (
        f"{LANGUAGE_LABELS.get(answer_language, answer_language)} ({answer_language})"
    )
    display_question = user_message.strip()
    if is_vague_web_follow_up(user_message) or references_session_monument(
        user_message, memory_context
    ) or is_incomplete_lookup_follow_up(user_message, memory_context):
        resolved = resolve_query_for_context(user_message, memory_context)
        if resolved != user_message.strip():
            display_question = (
                f"{user_message.strip()}\n\n"
                f"Question interprétée : {resolved}"
            )
        elif is_vague_web_follow_up(user_message):
            prior = memory_context.get("last_substantive_user_message")
            if prior:
                display_question = (
                    f"{user_message.strip()}\n\n"
                    f"Question précédente du visiteur : {prior}"
                )
    return format_rag_messages(
        answer_language=language_display,
        memory_context=format_memory_context(memory_context),
        retrieved_context=retrieved_context,
        web_search_context=format_web_search_context(
            web_search_results,
            answer_language=answer_language,
        ),
        user_question=display_question,
        output_guidelines=build_output_guidelines(
            user_message=user_message,
            memory_context=memory_context,
            answer_language=answer_language,
            structured_output=structured_output,
            has_web_context=has_web_context,
            explicit_web_request=is_explicit_web_request,
            web_search_empty_fallback=web_search_empty_fallback,
            local_context_relevant=local_context_relevant,
        ),
    )
