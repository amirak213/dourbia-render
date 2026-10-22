from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.preference_extractor import build_memory_context, merge_memory_updates
from app.models.memory import ChatMessage, UserPreference, UserSession

PREFERENCE_KEYS = frozenset(
    {
        "interests",
        "available_time_minutes",
        "mobility_mode",
        "last_mentioned_monuments",
        "primary_site_id",
        "primary_site_name",
        "last_substantive_user_message",
    }
)


class MemoryService:
    """Persistence layer for session memory."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create_session(self, session_id: str, *, language: str = "fr") -> UserSession:
        cleaned_session_id = session_id.strip()
        if not cleaned_session_id:
            raise ValueError("session_id must not be empty")

        session = self._db.scalar(
            select(UserSession).where(UserSession.session_id == cleaned_session_id)
        )
        if session is not None:
            return session

        session = UserSession(
            session_id=cleaned_session_id,
            preferred_language=_normalize_language(language),
        )
        self._db.add(session)
        self._db.flush()
        return session

    def get_session_by_external_id(self, session_id: str) -> UserSession | None:
        cleaned_session_id = session_id.strip()
        if not cleaned_session_id:
            return None
        return self._db.scalar(
            select(UserSession).where(UserSession.session_id == cleaned_session_id)
        )

    def get_preferences(self, session: UserSession) -> dict[str, Any]:
        preferences: dict[str, Any] = {}
        for row in session.preferences:
            if row.preference_key in PREFERENCE_KEYS:
                preferences[row.preference_key] = row.preference_value
        return preferences

    def get_memory_context(self, session: UserSession) -> dict[str, Any]:
        return build_memory_context(
            preferred_language=session.preferred_language,
            preferences=self.get_preferences(session),
        )

    def store_message(self, session: UserSession, *, role: str, content: str) -> ChatMessage:
        cleaned_content = content.strip()
        if not cleaned_content:
            raise ValueError("message content must not be empty")

        message = ChatMessage(
            session_id=session.id,
            role=role,
            content=cleaned_content,
        )
        self._db.add(message)
        self._db.flush()
        return message

    def apply_preference_updates(
        self,
        session: UserSession,
        updates: dict[str, Any],
    ) -> None:
        if "preferred_language" in updates:
            session.preferred_language = _normalize_language(updates["preferred_language"])

        for key in PREFERENCE_KEYS:
            if key not in updates:
                continue
            _upsert_preference(session, key, updates[key])

    def update_memory(
        self,
        session: UserSession,
        *,
        extracted: dict[str, Any],
        memory_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.get_preferences(session)
        merged_preferences = merge_memory_updates(current, extracted, memory_updates)
        self.apply_preference_updates(session, merged_preferences)
        return self.get_memory_context(session)


def _normalize_language(language: str) -> str:
    cleaned = language.strip().lower()
    return cleaned if cleaned else "fr"


def _upsert_preference(session: UserSession, key: str, value: Any) -> None:
    existing = next(
        (row for row in session.preferences if row.preference_key == key),
        None,
    )
    if existing is None:
        session.preferences.append(
            UserPreference(
                session_id=session.id,
                preference_key=key,
                preference_value=value,
            )
        )
        return
    existing.preference_value = value
