from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class LatencyReport:
    """Step-level latency measurements for a single chat request."""

    total_ms: float | None = None
    memory_retrieval_ms: float | None = None
    retrieval_ms: float | None = None
    prompt_construction_ms: float | None = None
    llm_generation_ms: float | None = None
    memory_update_ms: float | None = None
    web_search_ms: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def log_debug(self, *, settings: Settings, session_id: str) -> None:
        if not settings.debug:
            return

        parts = [
            f"session={session_id}",
            f"total_ms={_fmt(self.total_ms)}",
            f"memory_retrieval_ms={_fmt(self.memory_retrieval_ms)}",
            f"retrieval_ms={_fmt(self.retrieval_ms)}",
            f"prompt_construction_ms={_fmt(self.prompt_construction_ms)}",
            f"llm_generation_ms={_fmt(self.llm_generation_ms)}",
            f"memory_update_ms={_fmt(self.memory_update_ms)}",
            f"web_search_ms={_fmt(self.web_search_ms)}",
        ]
        for key, value in self.extra.items():
            parts.append(f"{key}={value}")

        logger.info("Chat latency debug: %s", ", ".join(parts))


class StepTimer:
    """Context manager that records elapsed milliseconds on exit."""

    def __init__(self) -> None:
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> StepTimer:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_args: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._started) * 1000


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"
