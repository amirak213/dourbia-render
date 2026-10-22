from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.memory.memory_service import MemoryService
from app.memory.preference_extractor import extract_preferences_from_message
from app.rag.language_detection import resolve_answer_language
from app.rag.web_search_decision import (
    is_incomplete_lookup_follow_up,
    is_archaeology_lookup_follow_up,
    is_substantive_user_message,
)
from app.models.memory import UserSession

logger = logging.getLogger(__name__)


class MemoryAgent:
    """Session memory facade for chat orchestration."""

    def __init__(self, db: Session, *, memory_service: MemoryService | None = None) -> None:
        self._db = db
        self._memory_service = memory_service or MemoryService(db)

    def get_or_create_session(self, session_id: str, *, language: str = "fr") -> UserSession:
        return self._memory_service.get_or_create_session(session_id, language=language)

    def get_context(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        return self._memory_service.get_memory_context(session)

    def record_turn(
        self,
        session_id: str,
        *,
        user_message: str,
        assistant_answer: str,
        request_language: str = "fr",
        memory_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._memory_service.get_or_create_session(
            session_id,
            language=request_language,
        )
        self._memory_service.store_message(session, role="user", content=user_message)
        self._memory_service.store_message(session, role="assistant", content=assistant_answer)

        extracted = extract_preferences_from_message(user_message)
        session_context = self._memory_service.get_memory_context(session)
        extracted["preferred_language"] = resolve_answer_language(
            user_message,
            request_language=request_language,
            memory_context=session_context,
        )
        if is_substantive_user_message(user_message) and not is_incomplete_lookup_follow_up(
            user_message, session_context
        ) and not is_archaeology_lookup_follow_up(user_message):
            extracted["last_substantive_user_message"] = user_message.strip()

        logger.info(
            "Memory turn recorded session=%s extracted_keys=%s agent_updates=%s",
            session_id,
            sorted(extracted.keys()),
            sorted((memory_updates or {}).keys()),
        )

        return self._memory_service.update_memory(
            session,
            extracted=extracted,
            memory_updates=memory_updates,
        )

    def _require_session(self, session_id: str) -> UserSession:
        session = self._memory_service.get_session_by_external_id(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        return session
