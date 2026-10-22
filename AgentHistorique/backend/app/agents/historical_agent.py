from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.observability.latency import LatencyReport, StepTimer
from app.llm.llm_client import LLMClient, LLMClientError, create_llm_client
from app.rag.answer_parser import parse_llm_answer
from app.rag.language_detection import resolve_answer_language
from app.rag.language_messages import (
    INSUFFICIENT_CONTEXT_ANSWERS,
    NO_ART_WEB_RESULTS_ANSWERS,
    NO_RELEVANT_WEB_RESULTS_ANSWERS,
    localized_action,
    localized_message,
)
from app.rag.prompts import (
    build_rag_messages,
    build_retrieval_query,
    derive_retrieval_filters,
    get_primary_monument_for_attribute_follow_up,
    get_site_id_for_attribute_follow_up,
)
from app.rag.text_utils import normalize_text
from app.rag.query_complexity import is_complex_question
from app.rag.retriever import RetrievalFilters, SemanticRetriever
from app.rag.practical_info_intent import (
    user_explicitly_requests_circuits,
    user_explicitly_requests_horaires_or_tarifs,
)
from app.rag.suggested_action_intent import get_suggested_action_intent
from app.rag.text_utils import normalize_text
from app.rag.web_search_decision import (
    build_emergency_web_queries,
    build_web_search_queries,
    filter_relevant_web_results,
    filter_sources_for_query,
    is_art_or_culture_query,
    is_domain_related_query,
    is_historical_figure_query,
    is_archaeology_lookup_follow_up,
    is_incomplete_lookup_follow_up,
    is_vague_web_follow_up,
    local_chunks_relevant_to_query,
    region_for_web_query,
    requests_event_or_schedule,
    resolve_query_for_context,
    references_session_monument,
    requests_archaeology_news,
    should_use_web_search,
    uses_demonstrative_reference,
    user_requests_lookup,
    user_requests_web_search,
)
from app.tools.web_search_tool import (
    BaseWebSearchTool,
    WebSearchResult,
    create_web_search_tool,
)
from app.rag.query_intent_llm import (
    classify_query_intent,
    should_use_web_search_from_flags,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_SCORE = 0.65
DEFAULT_CONTEXT_CHUNKS = 3
COMPLEX_CONTEXT_CHUNKS = 5
MAX_SUGGESTED_ACTIONS = 3
MAX_CITED_MONUMENTS = 1


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    source_id: float | None
    title: str | None
    score: float | None
    url: str | None = None


@dataclass(frozen=True)
class HistoricalAgentResult:
    answer: str
    sources: list[SourceRef]
    suggested_actions: list[str]
    memory_updates: dict[str, Any]
    latency: LatencyReport | None = None


class HistoricalAgent:
    """Grounded historical guide agent backed by semantic retrieval and an LLM."""

    def __init__(
        self,
        db: Session,
        *,
        retriever: SemanticRetriever | None = None,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        web_search_tool: BaseWebSearchTool | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._retriever = retriever or SemanticRetriever(db)
        self._llm = llm
        self._llm_client = llm
        self._web_search_tool = web_search_tool
        self._min_score = self._settings.rag_min_score

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = create_llm_client(self._settings)
        return self._llm

    def _get_web_search_tool(self) -> BaseWebSearchTool:
        if self._web_search_tool is None:
            self._web_search_tool = create_web_search_tool(self._settings)
        return self._web_search_tool

    def _collect_web_search_results(
        self,
        user_message: str,
        memory_context: dict[str, Any],
    ) -> list[WebSearchResult]:
        tool = self._get_web_search_tool()
        max_results = self._settings.web_search_max_results
        default_region = self._settings.web_search_region
        seen_urls: set[str] = set()
        collected: list[WebSearchResult] = []

        def extend_results(batch: list[WebSearchResult]) -> None:
            for result in batch:
                if result.url and result.url in seen_urls:
                    continue
                if result.url:
                    seen_urls.add(result.url)
                collected.append(result)

        query_plans = [
            (query, region_for_web_query(query, default_region))
            for query in build_web_search_queries(user_message, memory_context)
        ]
        if user_requests_web_search(user_message):
            query_plans.extend(
                (query, "wt-wt") for query in build_emergency_web_queries(user_message)
            )

        for web_query, region in query_plans:
            try:
                batch = tool.search(
                    web_query,
                    max_results=max_results,
                    region=region,
                )
            except Exception:
                logger.exception("Web search tool failed for query=%r", web_query)
                continue

            logger.info(
                "Web search query=%r region=%s raw_results=%s",
                web_query,
                region,
                len(batch),
            )
            for result in batch:
                logger.info(
                    "Web search hit query=%r title=%r url=%s",
                    web_query,
                    result.title,
                    result.url or "(no url)",
                )
            extend_results(batch)

        filtered = filter_relevant_web_results(
            collected,
            user_message,
            memory_context,
        )
        if filtered:
            kept = filtered[:max_results]
            logger.info(
                "Web search kept relevant results=%s urls=%s",
                len(kept),
                [result.url for result in kept if result.url],
            )
            return kept

        logger.warning(
            "Web search returned no Carthage-relevant results (raw_results=%s raw_urls=%s)",
            len(collected),
            [result.url for result in collected if result.url],
        )
        return []

    def answer(
        self,
        *,
        user_message: str,
        memory_context: dict[str, Any] | None = None,
        language: str = "fr",
    ) -> HistoricalAgentResult:
        cleaned_message = user_message.strip()
        if not cleaned_message:
            raise ValueError("user_message must not be empty")

        context = memory_context or {}
        answer_language = resolve_answer_language(
            cleaned_message,
            request_language=language,
            memory_context=context,
        )
        latency = LatencyReport()
        complex_question = is_complex_question(cleaned_message)

        with StepTimer() as retrieval_timer:
            retrieved_chunks = self._retrieve(
                cleaned_message,
                context,
                answer_language,
                complex_question=complex_question,
            )
        latency.retrieval_ms = retrieval_timer.elapsed_ms
        latency.extra["retrieval_top_k"] = self._resolve_top_k(complex_question)
        latency.extra["complex_question"] = complex_question

        sources = self._map_sources(retrieved_chunks)
        best_score = (
            float(retrieved_chunks[0].get("score", 0.0)) if retrieved_chunks else None
        )
        local_sufficient = self._has_sufficient_context(retrieved_chunks)
        local_context_relevant = local_chunks_relevant_to_query(
            cleaned_message,
            retrieved_chunks,
            context,
        )
        intent_flags = classify_query_intent(self._get_llm(), cleaned_message, context)
        explicit_web_request = intent_flags.explicit_web_request
        wants_web_search = should_use_web_search_from_flags(
            intent_flags,
            cleaned_message,
            retrieved_chunks,
            best_score,
            context,
            settings=self._settings,
        )
        needs_topic_web_supplement = intent_flags.requests_archaeology_news or (
            not local_context_relevant
            and (
                intent_flags.is_art_or_culture
                or intent_flags.is_historical_figure
                or intent_flags.requests_event_or_schedule
                or (
                    intent_flags.user_requests_lookup and intent_flags.is_domain_related
                )
            )
        )
        use_web_search = wants_web_search and (
            explicit_web_request or not local_sufficient or needs_topic_web_supplement
        )
        web_search_results: list[WebSearchResult] = []

        if use_web_search:
            with StepTimer() as web_search_timer:
                web_search_results = self._collect_web_search_results(
                    cleaned_message,
                    context,
                )
            latency.web_search_ms = web_search_timer.elapsed_ms
            sources = sources + self._map_web_sources(web_search_results)
            logger.info(
                "Web search used for query (results=%s, explicit=%s, local_sufficient=%s)",
                len(web_search_results),
                explicit_web_request,
                local_sufficient,
            )

            if explicit_web_request and not web_search_results:
                if local_context_relevant and local_sufficient:
                    logger.info(
                        "Explicit web request returned no results; falling back to local context "
                        "(chunks=%s, best_score=%s)",
                        len(retrieved_chunks),
                        best_score,
                    )
                else:
                    return HistoricalAgentResult(
                        answer=localized_message(
                            NO_RELEVANT_WEB_RESULTS_ANSWERS,
                            answer_language,
                        ),
                        sources=sources,
                        suggested_actions=self._build_suggested_actions(
                            sources,
                            context,
                            answer_language,
                            cleaned_message,
                        ),
                        memory_updates=self._build_memory_updates(
                            retrieved_chunks,
                            cleaned_message,
                            context,
                        ),
                        latency=latency,
                    )

            if (
                not web_search_results
                and needs_topic_web_supplement
                and is_art_or_culture_query(cleaned_message, context)
                and not explicit_web_request
            ):
                filtered_sources = filter_sources_for_query(
                    sources,
                    cleaned_message,
                    context,
                )
                return HistoricalAgentResult(
                    answer=localized_message(
                        NO_ART_WEB_RESULTS_ANSWERS,
                        answer_language,
                    ),
                    sources=filtered_sources,
                    suggested_actions=self._build_suggested_actions(
                        filtered_sources,
                        context,
                        answer_language,
                        cleaned_message,
                    ),
                    memory_updates=self._build_memory_updates(
                        retrieved_chunks,
                        cleaned_message,
                        context,
                    ),
                    latency=latency,
                )

            if (
                not web_search_results
                and needs_topic_web_supplement
                and requests_archaeology_news(cleaned_message, context)
                and not explicit_web_request
            ):
                filtered_sources = filter_sources_for_query(
                    sources,
                    cleaned_message,
                    context,
                )
                return HistoricalAgentResult(
                    answer=localized_message(
                        NO_RELEVANT_WEB_RESULTS_ANSWERS,
                        answer_language,
                    ),
                    sources=filtered_sources,
                    suggested_actions=self._build_suggested_actions(
                        filtered_sources,
                        context,
                        answer_language,
                        cleaned_message,
                    ),
                    memory_updates=self._build_memory_updates(
                        retrieved_chunks,
                        cleaned_message,
                        context,
                    ),
                    latency=latency,
                )

        if not local_sufficient and not web_search_results and not use_web_search:
            logger.info(
                "Insufficient retrieval context for query (chunks=%s, best_score=%s)",
                len(retrieved_chunks),
                best_score,
            )
            return HistoricalAgentResult(
                answer=localized_message(
                    INSUFFICIENT_CONTEXT_ANSWERS,
                    answer_language,
                ),
                sources=sources,
                suggested_actions=self._build_suggested_actions(
                    sources,
                    context,
                    answer_language,
                    cleaned_message,
                ),
                memory_updates=self._build_memory_updates(
                    retrieved_chunks,
                    cleaned_message,
                    context,
                ),
                latency=latency,
            )

        if not local_sufficient and not web_search_results and use_web_search:
            logger.info(
                "Web search enabled but returned no results (chunks=%s, best_score=%s)",
                len(retrieved_chunks),
                best_score,
            )
            if not retrieved_chunks:
                return HistoricalAgentResult(
                    answer=localized_message(
                        INSUFFICIENT_CONTEXT_ANSWERS,
                        answer_language,
                    ),
                    sources=sources,
                    suggested_actions=self._build_suggested_actions(
                        sources,
                        context,
                        answer_language,
                        cleaned_message,
                    ),
                    memory_updates=self._build_memory_updates(
                        retrieved_chunks,
                        cleaned_message,
                        context,
                    ),
                    latency=latency,
                )

        web_search_empty_fallback = (
            explicit_web_request
            and use_web_search
            and not web_search_results
            and local_sufficient
            and local_context_relevant
        )
        prompt_explicit_web = (
            explicit_web_request and use_web_search and bool(web_search_results)
        )

        with StepTimer() as prompt_timer:
            messages = build_rag_messages(
                user_message=cleaned_message,
                memory_context=context,
                retrieved_chunks=retrieved_chunks,
                language=answer_language,
                structured_output=self._settings.llm_structured_output,
                web_search_results=web_search_results or None,
                explicit_web_request=prompt_explicit_web,
                web_search_empty_fallback=web_search_empty_fallback,
                local_context_relevant=local_context_relevant,
            )
        latency.prompt_construction_ms = prompt_timer.elapsed_ms

        try:
            with StepTimer() as llm_timer:
                raw_answer = self._get_llm().complete(
                    messages,
                    temperature=self._settings.llm_temperature,
                    max_tokens=self._settings.llm_max_tokens,
                )
            latency.llm_generation_ms = llm_timer.elapsed_ms
        except LLMClientError:
            logger.exception("LLM call failed")
            raise

        answer = parse_llm_answer(
            raw_answer,
            structured=self._settings.llm_structured_output,
        )

        sources = filter_sources_for_query(sources, cleaned_message, context)

        return HistoricalAgentResult(
            answer=answer,
            sources=sources,
            suggested_actions=self._build_suggested_actions(
                sources,
                context,
                answer_language,
                cleaned_message,
            ),
            memory_updates=self._build_memory_updates(
                retrieved_chunks,
                cleaned_message,
                context,
            ),
            latency=latency,
        )

    def _resolve_top_k(self, complex_question: bool) -> int:
        if complex_question:
            return self._settings.rag_top_k_complex
        return self._settings.rag_top_k

    def _resolve_max_context_chunks(self, complex_question: bool) -> int:
        if complex_question:
            return COMPLEX_CONTEXT_CHUNKS
        return DEFAULT_CONTEXT_CHUNKS

    def _retrieve(
        self,
        user_message: str,
        memory_context: dict[str, Any],
        language: str,
        *,
        complex_question: bool = False,
    ) -> list[dict[str, Any]]:
        retrieval_message = user_message
        if (
            is_vague_web_follow_up(user_message)
            or references_session_monument(user_message, memory_context)
            or is_incomplete_lookup_follow_up(user_message, memory_context)
            or is_archaeology_lookup_follow_up(user_message)
        ):
            retrieval_message = resolve_query_for_context(user_message, memory_context)
        query = build_retrieval_query(retrieval_message, memory_context)
        filter_kwargs = derive_retrieval_filters(memory_context, language)
        action_intent = get_suggested_action_intent(user_message)
        if action_intent in {"circuit_detail", "nearby_monuments", "roman_circuit"}:
            filter_kwargs["destination"] = "Carthage"
        filters = RetrievalFilters(**filter_kwargs)

        site_id = get_site_id_for_attribute_follow_up(user_message, memory_context)
        if site_id is not None:
            filters = RetrievalFilters(
                source_type="monument",
                destination=filters.destination,
                period=filters.period,
                language=filters.language,
                site_id=site_id,
            )
            logger.info("Site follow-up retrieval restricted to site_id=%s", site_id)

        top_k = self._resolve_top_k(complex_question)
        chunks = self._retriever.retrieve(query, top_k=top_k, filters=filters)
        chunks = self._post_filter_chunks(
            chunks,
            user_message=user_message,
            complex_question=complex_question,
        )
        return self._prioritize_site_follow_up_chunks(
            chunks,
            user_message,
            memory_context,
            complex_question=complex_question,
        )

    def _post_filter_chunks(
        self,
        chunks: list[dict[str, Any]],
        *,
        user_message: str = "",
        complex_question: bool = False,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        filtered = [
            chunk
            for chunk in chunks
            if not self._is_cartagena_spain_confusion(chunk, user_message)
        ]
        if not filtered:
            filtered = chunks

        best_score = float(filtered[0].get("score", 0.0))
        score_threshold = best_score - self._settings.rag_score_gap_from_best
        filtered = [
            chunk
            for chunk in filtered
            if float(chunk.get("score", 0.0)) >= score_threshold
        ]
        max_chunks = self._resolve_max_context_chunks(complex_question)
        return filtered[:max_chunks]

    def _is_cartagena_spain_confusion(
        self,
        chunk: dict[str, Any],
        user_message: str,
    ) -> bool:
        blob = normalize_text(f"{chunk.get('title', '')} {chunk.get('chunk_text', '')}")
        if "cartagena" not in blob:
            return False
        if any(marker in blob for marker in ("tunisie", "tunisia", "carthage tunis")):
            return False

        query_norm = normalize_text(user_message)
        tunisia_query_markers = (
            "carthage",
            "tunisie",
            "tunisia",
            "baal",
            "hammon",
            "punique",
            "romain",
        )
        return any(marker in query_norm for marker in tunisia_query_markers)

    def _prioritize_site_follow_up_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_message: str,
        memory_context: dict[str, Any],
        *,
        complex_question: bool = False,
    ) -> list[dict[str, Any]]:
        primary_monument = get_primary_monument_for_attribute_follow_up(
            user_message,
            memory_context,
        )
        if not primary_monument or not chunks:
            return chunks

        primary_key = normalize_text(primary_monument)

        def sort_key(chunk: dict[str, Any]) -> tuple[int, int, float]:
            title_key = normalize_text(chunk.get("title"))
            metadata = chunk.get("metadata") or {}
            title_match = 0 if title_key == primary_key else 1
            site_root = 0 if metadata.get("is_site_root") else 1
            score = -float(chunk.get("score", 0.0))
            return (title_match, site_root, score)

        prioritized = sorted(chunks, key=sort_key)
        max_chunks = self._resolve_max_context_chunks(complex_question)
        return prioritized[:max_chunks]

    def _has_sufficient_context(self, retrieved_chunks: list[dict[str, Any]]) -> bool:
        if not retrieved_chunks:
            return False
        best_score = float(retrieved_chunks[0].get("score", 0.0))
        return best_score >= self._min_score

    def _map_sources(self, retrieved_chunks: list[dict[str, Any]]) -> list[SourceRef]:
        sources: list[SourceRef] = []
        for chunk in retrieved_chunks:
            source_id = chunk.get("source_id")
            if source_id is None:
                continue
            sources.append(
                SourceRef(
                    source_type=str(chunk.get("source_type", "")),
                    source_id=self._normalize_source_id(source_id),
                    title=chunk.get("title"),
                    score=float(chunk.get("score", 0.0)),
                    url=None,
                )
            )
        return sources

    def _map_web_sources(
        self,
        web_results: list[WebSearchResult],
    ) -> list[SourceRef]:
        return [
            SourceRef(
                source_type="web",
                source_id=None,
                title=result.title,
                score=None,
                url=result.url or None,
            )
            for result in web_results
        ]

    def _normalize_source_id(self, source_id: Any) -> float:
        if isinstance(source_id, Decimal):
            return float(source_id)
        return float(source_id)

    def _build_suggested_actions(
        self,
        sources: list[SourceRef],
        memory_context: dict[str, Any],
        answer_language: str,
        user_message: str,
    ) -> list[str]:
        actions: list[str] = []
        interests = {
            str(item).lower() for item in (memory_context.get("interests") or [])
        }

        has_monument = any(source.source_type == "monument" for source in sources)
        has_circuit = any(source.source_type == "circuit" for source in sources)
        wants_hours = user_explicitly_requests_horaires_or_tarifs(user_message)
        wants_circuits = user_explicitly_requests_circuits(user_message)

        if has_monument and wants_hours:
            actions.append(localized_action("show_hours", answer_language))
        if has_circuit and wants_circuits:
            actions.append(localized_action("circuit_detail", answer_language))
        if wants_circuits and (
            interests & {"romain", "romaine"}
            or any("romain" in (source.title or "").lower() for source in sources)
        ):
            actions.append(localized_action("roman_circuit", answer_language))
        if wants_circuits and memory_context.get("available_time_minutes"):
            actions.append(localized_action("time_adapted_visit", answer_language))
        if len(sources) > 1:
            actions.append(localized_action("nearby_monuments", answer_language))

        deduplicated: list[str] = []
        seen: set[str] = set()
        for action in actions:
            if action in seen:
                continue
            seen.add(action)
            deduplicated.append(action)

        if not deduplicated:
            deduplicated.append(localized_action("ask_another", answer_language))

        return deduplicated[:MAX_SUGGESTED_ACTIONS]

    def _build_memory_updates(
        self,
        retrieved_chunks: list[dict[str, Any]],
        user_message: str,
        memory_context: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            get_site_id_for_attribute_follow_up(user_message, memory_context)
            is not None
        ):
            return {}

        if references_session_monument(user_message, memory_context) and (
            is_art_or_culture_query(user_message) or user_requests_lookup(user_message)
        ):
            return {}

        primary_chunk = next(
            (
                chunk
                for chunk in retrieved_chunks
                if chunk.get("source_type") == "monument" and chunk.get("title")
            ),
            None,
        )
        if primary_chunk is None:
            return {}

        metadata = primary_chunk.get("metadata") or {}
        primary_title = primary_chunk.get("title")
        updates: dict[str, Any] = {
            "last_mentioned_monuments": [str(primary_title)],
        }
        if metadata.get("site_id") is not None:
            updates["primary_site_id"] = int(metadata["site_id"])
        if metadata.get("site_name"):
            updates["primary_site_name"] = str(metadata["site_name"])
        return updates
