"""
AgentTracer — Observabilité production.
Traces structurées, métriques, logs JSON.
Plus jamais de print() en production.
"""

from __future__ import annotations

import json
import logging
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Generator


# ──────────────────────────────────────────────────────────────
# STRUCTURED LOGGER
# ──────────────────────────────────────────────────────────────

def _setup_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)

        if log_file:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(_JsonFormatter())
            logger.addHandler(fh)

    return logger


class _JsonFormatter(logging.Formatter):
    """Formatter JSON pour ingestion par Datadog / Grafana / ELK."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level":     record.levelname,
            "logger":    record.name,
            "message":   record.getMessage(),
        }
        if hasattr(record, "extra"):
            extra = getattr(record, "extra", {})
            if isinstance(extra, dict):
                log.update(extra)
            
        return json.dumps(log, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# SPAN — unité de trace
# ──────────────────────────────────────────────────────────────

@dataclass
class Span:
    name:       str
    run_id:     str
    started_at: float = field(default_factory=time.perf_counter)
    _meta:      dict  = field(default_factory=dict)
    _error:     str | None = None
    _logger:    Any   = None

    def set_meta(self, data: dict) -> None:
        self._meta.update(data)

    def error(self, msg: str) -> None:
        self._error = msg

    def finish(self) -> dict:
        duration_ms = int((time.perf_counter() - self.started_at) * 1000)
        record = {
            "span":        self.name,
            "run_id":      self.run_id,
            "duration_ms": duration_ms,
            "status":      "error" if self._error else "ok",
            **self._meta,
        }
        if self._error:
            record["error"] = self._error

        if self._logger:
            if self._error:
                self._logger.error(self.name, extra={"extra": record})
            else:
                self._logger.debug(self.name, extra={"extra": record})

        return record


# ──────────────────────────────────────────────────────────────
# METRICS — compteurs en mémoire
# ──────────────────────────────────────────────────────────────

class Metrics:
    """Métriques simples thread-safe en mémoire."""

    def __init__(self):
        self._data: dict[str, float] = {}
        self._lock = threading.Lock()

    def increment(self, key: str, by: float = 1.0) -> None:
        with self._lock:
            self._data[key] = self._data.get(key, 0) + by

    def gauge(self, key: str, value: float) -> None:
        with self._lock:
            self._data[key] = value

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)


# ──────────────────────────────────────────────────────────────
# AGENT TRACER — façade principale
# ──────────────────────────────────────────────────────────────

class AgentTracer:
    """
    Tracer production pour l'agent météo.
    
    Usage:
        with tracer.run_span(run_id, session_id, query) as span:
            with tracer.span("plan", run_id) as s:
                s.set_meta({"steps": 2})
    """

    def __init__(self, log_file: Path | None = None):
        self.logger  = _setup_logger("weather_agent", log_file)
        self.metrics = Metrics()
        self._runs:  dict[str, dict] = {}  # run_id → metadata
        self._lock   = threading.Lock()

    @contextmanager
    def run_span(
        self,
        run_id:     str,
        session_id: str,
        query:      str,
    ) -> Generator[Span, None, None]:
        """Context manager pour un run complet."""
        self.metrics.increment("runs.total")
        self.logger.info("run.start", extra={"extra": {
            "run_id": run_id, "session_id": session_id,
            "query":  query[:100],
        }})

        span = Span(name="run", run_id=run_id, _logger=self.logger)

        with self._lock:
            self._runs[run_id] = {
                "session_id": session_id,
                "started_at": datetime.utcnow().isoformat(),
                "query":      query[:100],
            }

        try:
            yield span
        except Exception as e:
            span.error(str(e))
            self.metrics.increment("runs.error")
            raise
        finally:
            record = span.finish()
            self.metrics.increment("runs.duration_ms_total", record["duration_ms"])

            if record["status"] == "ok":
                self.metrics.increment("runs.success")
            self.logger.info("run.end", extra={"extra": record})

            # Purge LRU des runs en mémoire
            with self._lock:
                if len(self._runs) > 500:
                    oldest = next(iter(self._runs))
                    del self._runs[oldest]

    @contextmanager
    def span(self, name: str, run_id: str) -> Generator[Span, None, None]:
        """Context manager pour un span individuel."""
        s = Span(name=name, run_id=run_id, _logger=self.logger)
        try:
            yield s
        except Exception as e:
            s.error(str(e))
            raise
        finally:
            s.finish()

    def log_tool_call(
        self,
        run_id:      str,
        tool_name:   str,
        tool_args:   dict,
        duration_ms: int,
        success:     bool,
        error:       str | None = None,
    ) -> None:
        self.metrics.increment(f"tools.{tool_name}.calls")
        self.metrics.increment(f"tools.{tool_name}.{'success' if success else 'error'}")
        self.metrics.increment(f"tools.{tool_name}.duration_ms_total", duration_ms)

        level = logging.DEBUG if success else logging.WARNING
        self.logger.log(level, f"tool.{tool_name}", extra={"extra": {
            "run_id":      run_id,
            "tool_name":   tool_name,
            "duration_ms": duration_ms,
            "success":     success,
            "error":       error,
        }})

    def log_llm_call(
        self,
        run_id:      str,
        model:       str,
        provider:    str,
        tokens_used: int,
        duration_ms: int,
        purpose:     str,  # "plan" | "evaluate" | "synthesize"
    ) -> None:
        self.metrics.increment(f"llm.{provider}.calls")
        self.metrics.increment(f"llm.{provider}.tokens", tokens_used)
        self.metrics.increment(f"llm.{purpose}.calls")

        self.logger.debug("llm.call", extra={"extra": {
            "run_id":      run_id,
            "model":       model,
            "provider":    provider,
            "tokens":      tokens_used,
            "duration_ms": duration_ms,
            "purpose":     purpose,
        }})

    def get_metrics_snapshot(self) -> dict:
        """Retourne les métriques pour /health et /metrics."""
        return self.metrics.snapshot()

    def get_health(self) -> dict:
        """Résumé de santé pour l'endpoint /health."""
        m = self.metrics.snapshot()
        total   = m.get("runs.total", 0)
        success = m.get("runs.success", 0)
        errors  = m.get("runs.error", 0)
        avg_dur = (
            m.get("runs.duration_ms_total", 0) / total
            if total > 0 else 0
        )
        return {
            "status":          "ok",
            "version":         "4.0",
            "runs_total":      int(total),
            "runs_success":    int(success),
            "runs_error":      int(errors),
            "success_rate":    round(success / total, 3) if total > 0 else 1.0,
            "avg_duration_ms": round(avg_dur, 1),
            "active_sessions": len(self._runs),
        }
