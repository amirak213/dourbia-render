"""
historical_agent_proxy.py — Proxy Aziz → Agent Historique

Calqué sur le pattern subprocess isolé existant (Yasmine, Météo).
Aziz instancie HistoricalAgentProxy et appelle .query() pour chaque
intention historique détectée.

Architecture :
    Aziz (orchestrateur.py)
        └── HistoricalAgentProxy.query(...)
                └── [stdin JSON] → worker.py subprocess → [stdout JSON]
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Timeout d'appel au worker (secondes)
WORKER_TIMEOUT = float(os.environ.get("HISTORICAL_WORKER_TIMEOUT", "30.0"))

# Réponses de fallback par langue si le worker est indisponible
_FALLBACK_ANSWERS: dict[str, str] = {
    "fr": "Je ne peux pas accéder aux informations historiques pour le moment. Réessayez dans quelques instants.",
    "en": "Historical information is temporarily unavailable. Please try again shortly.",
    "ar": "المعلومات التاريخية غير متاحة مؤقتاً. يرجى المحاولة مجدداً.",
}


class HistoricalAgentProxy:
    """
    Proxy vers le worker subprocess de l'agent historique.

    Usage dans orchestrateur.py :
        historical_agent = HistoricalAgentProxy()
        historical_agent.start()

        result = historical_agent.query(
            query="Explique les Thermes d'Antonin",
            query_embedding=[...],   # fourni par le modèle d'embedding Dourbia
            language="fr",
            session_context={},      # contexte Redis L1
        )
        # result["answer"] → str
        # result["sources"] → list
        # result["retrieval_score"] → float
        # result["used_web_fallback"] → bool
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> bool:
        """
        Démarre le worker subprocess.
        Retourne True si le démarrage est réussi, False sinon.

        INTEGRATION NOTE: Appeler dans start.ps1 ou au démarrage de FastAPI,
        après que PostgreSQL et Redis sont confirmés sains.
        """
        worker_path = os.path.join(
            os.path.dirname(__file__), "worker.py"
        )

        env = {**os.environ}  # hérite de l'env Dourbia (GROQ_API_KEY etc.)

        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "AgentPrincipal.agents.historical.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,  # line-buffered
                cwd=os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", "..", "..")
                ),
                env=env,
            )
        except Exception as exc:
            logger.error("Impossible de démarrer le worker historique: %s", exc)
            return False

        # Attendre le signal "ready" du worker (avec timeout)
        ready = self._wait_for_ready(timeout=30.0)
        if ready:
            self._started = True
            logger.info("Worker historique prêt (PID=%s)", self._process.pid)
        else:
            logger.error("Worker historique n'a pas envoyé le signal ready dans les délais.")
            self.stop()
        return ready

    def _wait_for_ready(self, timeout: float) -> bool:
        """Lit la première ligne stdout du worker et vérifie {"status": "ready"}."""
        if self._process is None or self._process.stdout is None:
            return False

        result: list[bool] = [False]

        def _read() -> None:
            try:
                line = self._process.stdout.readline()  # type: ignore[union-attr]
                if line:
                    data = json.loads(line.strip())
                    result[0] = data.get("status") == "ready"
            except Exception as exc:
                logger.warning("Erreur lecture ready signal: %s", exc)

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=timeout)
        return result[0]

    def query(
        self,
        *,
        query: str,
        query_embedding: list[float],
        language: str = "fr",
        session_context: dict[str, Any] | None = None,
        web_search_enabled: bool = False,
    ) -> dict[str, Any]:
        """
        Envoie une requête au worker et retourne sa réponse.

        En cas d'erreur (timeout, worker mort), retourne un dict de fallback
        avec un message d'erreur localisé — sans lever d'exception vers Aziz.
        """
        if not self._started or self._process is None:
            logger.warning("HistoricalAgentProxy.query() appelé avant start()")
            return self._fallback_response(language, "Worker non démarré")

        payload = {
            "query": query,
            "query_embedding": query_embedding,
            "language": language,
            "session_context": session_context or {},
            "web_search_enabled": web_search_enabled,
        }

        result: list[dict | None] = [None]
        error: list[str] = ["timeout"]

        # APRÈS
        def _call() -> None:
            acquired = self._lock.acquire(timeout=WORKER_TIMEOUT)
            if not acquired:
                error[0] = "lock_occupe"
                logger.error(
                    "Worker historique: verrou occupé depuis plus de %.0fs — "
                    "un appel précédent est probablement bloqué (query=%r)",
                    WORKER_TIMEOUT,
                    query[:80],
                )
                return
            try:
                if self._process is None or self._process.stdin is None:
                    error[0] = "Processus mort"
                    return
                self._process.stdin.write(
                    json.dumps(payload, ensure_ascii=False) + "\n"
                )
                self._process.stdin.flush()
                line = self._process.stdout.readline()  # type: ignore[union-attr]
                if line:
                    result[0] = json.loads(line.strip())
                    error[0] = ""
            except Exception as exc:
                error[0] = str(exc)
                logger.error("Erreur communication worker historique: %s", exc)
            finally:
                self._lock.release()

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=WORKER_TIMEOUT)

        if result[0] is None:
            logger.error("Worker historique: %s (query=%r)", error[0], query[:80])
            # Tenter redémarrage si le process est mort
            if self._process.poll() is not None:
                logger.warning("Worker historique mort, tentative de redémarrage...")
                self._started = False
                self.start()
            return self._fallback_response(language, error[0])

        # Propager une éventuelle erreur interne du worker
        if result[0].get("error"):
            logger.error(
                "Worker historique erreur interne: %s (query=%r)",
                result[0]["error"],
                query[:120],
            )
        else:
            logger.info(
                "Worker historique réponse reçue: answer_len=%d sources=%d retrieval_score=%s",
                len(result[0].get("answer") or ""),
                len(result[0].get("sources") or []),
                result[0].get("retrieval_score"),
            )

        return result[0]

    def stop(self) -> None:
        """Arrête proprement le worker subprocess."""
        if self._process is not None:
            try:
                self._process.stdin.close()  # type: ignore[union-attr]
                self._process.wait(timeout=5.0)
            except Exception:
                self._process.kill()
            finally:
                self._process = None
                self._started = False
        logger.info("Worker historique arrêté.")

    def is_alive(self) -> bool:
        """Vérifie si le subprocess tourne encore."""
        return (
            self._process is not None
            and self._process.poll() is None
        )

    @staticmethod
    def _fallback_response(language: str, reason: str) -> dict[str, Any]:
        answer = _FALLBACK_ANSWERS.get(language, _FALLBACK_ANSWERS["fr"])
        return {
            "answer": answer,
            "sources": [],
            "retrieval_score": 0.0,
            "used_web_fallback": False,
            "language": language,
            "error": reason,
        }
