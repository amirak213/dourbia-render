import asyncio
import json
import logging
import sys
import os
import subprocess
import threading
from typing import Optional
from unittest import result

log = logging.getLogger("chatbot.agent_reservation")

WORKER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "agent_reservation_worker.py")
)
DOURBIA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "AgentLocation")
)


class AgentReservationWrapper:
    def __init__(self):
        self._available = (
            os.environ.get("RESERVATION_ENABLED", "1") != "0"
            and os.path.exists(WORKER_PATH)
            and os.path.exists(DOURBIA_PATH))
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        if self._available:
            self._start_worker()

    def _start_worker(self):
        """Démarre le process worker persistant."""
        self._proc = subprocess.Popen(
            [sys.executable, "-u", WORKER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,  # logs worker → stderr principal
            cwd=DOURBIA_PATH,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
        )
        log.info(f"[RESERVATION] Worker démarré (pid={self._proc.pid})")

    def _ensure_worker(self):
        """Redémarre le worker s'il est mort."""
        if self._proc is None or self._proc.poll() is not None:
            log.warning("[RESERVATION] Worker mort — redémarrage")
            self._start_worker()

    # agent_reservation_wrapper.py

    def _run_worker_sync(self, payload: str) -> dict:
        with self._lock:
            try:
                self._ensure_worker()
                proc = self._proc
                if proc is None or proc.stdin is None or proc.stdout is None:
                    raise RuntimeError(
                        "Worker réservation indisponible : process ou pipes stdin/stdout manquants"
                    )

                proc.stdin.write((payload + "\n").encode("utf-8"))
                proc.stdin.flush()

                # Timeout via thread — compatible Windows
                result: list[Optional[str]] = [None]
                error: list[Optional[BaseException]] = [None]
                stdout = proc.stdout

                def read_line():
                    try:

                        result[0] = stdout.readline().decode("utf-8", errors="replace").strip()
                    except Exception as e:

                        error[0] = e

                t = threading.Thread(target=read_line, daemon=True)
                t.start()
                t.join(timeout=45)  # 45s max

                if t.is_alive():
                    raise RuntimeError("Worker timeout — pas de réponse après 45s")
                if error[0] is not None:
                    raise error[0]
                if not result[0]:
                    raise RuntimeError("Worker a fermé stdout")

                return json.loads(result[0])

            except Exception as e:
                log.error(f"[RESERVATION] Erreur worker sync : {e}", exc_info=True)
                if self._proc and self._proc.poll() is not None:
                    self._proc = None
                raise

    def shutdown(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=5)

    async def handle_message(self, message: str, session_id: str) -> dict:
        if not self._available:
            return self._fallback_response()
        try:
            payload = json.dumps({"message": message, "session_id": session_id})
            loop = asyncio.get_event_loop()

            result = await loop.run_in_executor(None, self._run_worker_sync, payload)
            return {
                "disponible": True,
                "response": result["reply"],
                "error": result.get("error"),
                "payload": {
                    "_raw": {
                        "tokens_used": result.get("tokens", 0),
                    }
                },
            }
        except Exception as e:
            log.error(f"[RESERVATION] Erreur : {e}", exc_info=True)
            return self._fallback_response(erreur=str(e))

    def _fallback_response(self, erreur=None):
        return {
            "disponible": False,
            "response": "Notre service de réservation est momentanément indisponible. Réessayez dans quelques instants.",
            "error": erreur or "service_indisponible",
            "payload": {
                "_raw": {
                    "tokens_used": 0,
                }
            },
        }


_reservation_wrapper_instance: Optional[AgentReservationWrapper] = None


def get_reservation_wrapper() -> AgentReservationWrapper:
    global _reservation_wrapper_instance
    if _reservation_wrapper_instance is None:
        _reservation_wrapper_instance = AgentReservationWrapper()
    return _reservation_wrapper_instance
