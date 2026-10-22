"""
ContextManager — Mémoire multi-niveaux cohérente.
- Court terme : session en RAM (thread-safe)
- Long terme   : fichier JSON structuré
- Source de vérité unique — plus de 3 systèmes qui se marchent dessus
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Turn:
    role:      str
    content:   str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata:  dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionMemory:
    session_id:  str
    turns:       list[Turn]    = field(default_factory=list)
    last_city:   str | None    = None
    created_at:  str           = field(default_factory=lambda: datetime.now().isoformat())

    def add_turn(self, role: str, content: str, metadata: dict | None = None) -> None:
        self.turns.append(Turn(role=role, content=content, metadata=metadata or {}))
        # Garde seulement les 20 derniers turns
        if len(self.turns) > 20:
            self.turns = self.turns[-20:]

    def recent_turns(self, n: int = 6) -> list[dict]:
        return [t.to_dict() for t in self.turns[-n:]]

    def extract_last_city(self) -> str | None:
        """Extrait la dernière ville mentionnée depuis les turns."""
        for turn in reversed(self.turns):
            meta_city = turn.metadata.get("city")
            if meta_city:
                return meta_city
        return self.last_city


@dataclass
class LongTermMemory:
    favorite_cities_by_user: dict[str, list[str]] = field(default_factory=dict)
    query_history:           list[dict]            = field(default_factory=list)

    def add_city(self, city: str, user_id: str = "global") -> None:
        if not city:
            return
        bucket = self.favorite_cities_by_user.setdefault(user_id, [])
        if city.lower() not in [c.lower() for c in bucket]:
            bucket.append(city)
        self.favorite_cities_by_user[user_id] = bucket[-20:]

    def get_favorite_cities(self, user_id: str = "global") -> list[str]:
        return self.favorite_cities_by_user.get(user_id, [])[-5:]

    def add_query(self, query: str, city: str | None, response_preview: str) -> None:
        self.query_history.append({
            "date":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "query":    query[:200],
            "city":     city,
            "response": response_preview[:100],
        })
        self.query_history = self.query_history[-50:]

    def to_dict(self) -> dict:
        return {
            "favorite_cities_by_user": self.favorite_cities_by_user,
            "query_history":           self.query_history,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LongTermMemory":
        cities_by_user = d.get("favorite_cities_by_user", {})
        if not cities_by_user and d.get("favorite_cities"):
            cities_by_user = {"global": d["favorite_cities"]}
        return cls(
            favorite_cities_by_user = cities_by_user,
            query_history           = d.get("query_history", []),
        )
        
        
class ContextManager:
    """
    Gestionnaire de contexte unifié.
    Une seule source de vérité pour toute la mémoire de l'agent.
    """

    def __init__(self, memory_file: Path):
        self._memory_file  = memory_file
        self._sessions:    dict[str, SessionMemory] = {}
        self._long_term:   LongTermMemory = self._load_long_term()
        self._lock         = threading.Lock()

    # ──────────────────────────────────────────────
    # INTERFACE PUBLIQUE
    # ──────────────────────────────────────────────

    def add_turn(
        self,
        session_id: str,
        role:       str,
        content:    str,
        metadata:   dict | None = None,
    ) -> None:
        with self._lock:
            session = self._get_or_create_session(session_id)
            session.add_turn(role, content, metadata or {})

            # Met à jour last_city si présente dans metadata
            if metadata and metadata.get("city"):
                session.last_city = metadata["city"]
                self._long_term.add_city(metadata["city"])
                self._save_long_term()

    def add_user_turn(self, session_id: str, content: str) -> None:
        self.add_turn(session_id, "user", content)

    def build_context(self, session_id: str, query: str) -> dict:
        """
        Construit le contexte complet pour l'agent.
        C'est la seule méthode que l'agent appelle pour obtenir le contexte.
        """
        with self._lock:
            session = self._get_or_create_session(session_id)
            return {
                "session_id":     session_id,
                "recent_turns":   session.recent_turns(6),
                "last_city":      session.extract_last_city(),
                "favorite_cities":self._long_term.get_favorite_cities("global"),
                "session_created":session.created_at,
            }

    def reset_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def get_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def record_query(self, query: str, city: str | None, response: str) -> None:
        with self._lock:
            self._long_term.add_query(query, city, response)
            self._save_long_term()

    # ──────────────────────────────────────────────
    # GESTION DES SESSIONS
    # ──────────────────────────────────────────────

    def _get_or_create_session(self, session_id: str) -> SessionMemory:
        """Thread-unsafe — doit être appelé sous self._lock."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionMemory(session_id=session_id)
        # LRU simple : purge si trop de sessions
        if len(self._sessions) > 1000:
            oldest = next(iter(self._sessions))
            del self._sessions[oldest]
        return self._sessions[session_id]

    # ──────────────────────────────────────────────
    # PERSISTANCE LONG TERME
    # ──────────────────────────────────────────────

    def _load_long_term(self) -> LongTermMemory:
        try:
            if self._memory_file.exists():
                data = json.loads(self._memory_file.read_text(encoding="utf-8"))
                return LongTermMemory.from_dict(data)
        except (json.JSONDecodeError, OSError):
            pass
        return LongTermMemory()

    def _save_long_term(self) -> None:
        """Thread-unsafe — doit être appelé sous self._lock."""
        try:
            self._memory_file.write_text(
                json.dumps(self._long_term.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            pass  # Non bloquant — la mémoire est en RAM de toute façon