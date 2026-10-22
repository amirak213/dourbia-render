from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.agents.historical_agent import HistoricalAgent, SourceRef
from app.agents.memory_agent import MemoryAgent
from app.config import get_settings
from app.rag.language_detection import resolve_answer_language
from app.observability.latency import LatencyReport, StepTimer
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    LatencyDebugSchema,
    MemoryContextSchema,
    SourceRefSchema,
)

logger = logging.getLogger(__name__)


class LocalOrchestrator:
    """Simple local chat orchestrator for standalone MVP testing."""

    def __init__(
        self,
        db: Session,
        *,
        memory_agent: MemoryAgent | None = None,
        historical_agent: HistoricalAgent | None = None,
    ) -> None:
        self._db = db
        self._memory_agent = memory_agent or MemoryAgent(db)
        self._historical_agent = historical_agent or HistoricalAgent(db)

    def handle_chat(self, request: ChatRequest) -> ChatResponse:
        settings = get_settings()
        started = time.perf_counter()
        latency = LatencyReport()

        logger.info(
            "Chat request received for session=%s message_length=%s",
            request.session_id,
            len(request.message),
        )

        with StepTimer() as memory_retrieval_timer:
            self._memory_agent.get_or_create_session(
                request.session_id,
                language=request.language,
            )
            memory_context = self._memory_agent.get_context(request.session_id)
        latency.memory_retrieval_ms = memory_retrieval_timer.elapsed_ms

        answer_language = resolve_answer_language(
            request.message,
            request_language=request.language,
            memory_context=memory_context,
        )
        memory_context = {
            **memory_context,
            "preferred_language": answer_language,
        }

        agent_result = self._historical_agent.answer(
            user_message=request.message,
            memory_context=memory_context,
            language=answer_language,
        )

        with StepTimer() as memory_update_timer:
            updated_context = self._memory_agent.record_turn(
                request.session_id,
                user_message=request.message,
                assistant_answer=agent_result.answer,
                request_language=request.language,
                memory_updates=agent_result.memory_updates,
            )
            self._db.commit()
        latency.memory_update_ms = memory_update_timer.elapsed_ms

        latency.total_ms = (time.perf_counter() - started) * 1000
        if agent_result.latency is not None:
            agent_latency = agent_result.latency
            latency.retrieval_ms = agent_latency.retrieval_ms
            latency.prompt_construction_ms = agent_latency.prompt_construction_ms
            latency.llm_generation_ms = agent_latency.llm_generation_ms
            latency.web_search_ms = agent_latency.web_search_ms
            latency.extra.update(agent_latency.extra)

        latency.log_debug(settings=settings, session_id=request.session_id)

        latency_debug = None
        if settings.debug:
            latency_debug = LatencyDebugSchema(
                memory_retrieval_ms=latency.memory_retrieval_ms,
                retrieval_ms=latency.retrieval_ms,
                prompt_construction_ms=latency.prompt_construction_ms,
                llm_generation_ms=latency.llm_generation_ms,
                memory_update_ms=latency.memory_update_ms,
                web_search_ms=latency.web_search_ms,
            )

        return ChatResponse(
            session_id=request.session_id,
            answer=agent_result.answer,
            sources=[self._to_source_schema(source) for source in agent_result.sources],
            memory_context=MemoryContextSchema(**updated_context),
            suggested_actions=agent_result.suggested_actions,
            latency_ms=latency.total_ms,
            latency_debug=latency_debug,
        )

    def _to_source_schema(self, source: SourceRef) -> SourceRefSchema:
        if source.source_type == "web":
            return SourceRefSchema(
                source_type="web",
                source_id=None,
                title=source.title,
                score=None,
                url=source.url,
            )

        source_type = "circuit" if source.source_type == "circuit" else "monument"
        return SourceRefSchema(
            source_type=source_type,
            source_id=source.source_id,
            title=source.title,
            score=source.score,
        )
