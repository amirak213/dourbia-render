"""
API Flask — WeatherAgent v4
- Authentification par API key
- Rate limiting applicatif
- Endpoints séparés : chat / health / metrics / sessions
- Toujours du JSON valide en sortie
"""

from __future__ import annotations

import os
import time
import threading
from collections import defaultdict
from pathlib import Path

from flask import Flask, request, jsonify, g
from flask_cors import CORS

from core.agent import WeatherAgent
from core.model_router import ModelRouter, TaskType
from core.prompts import get_synthesis_system_prompt
from memory.context import ContextManager
from observability.tracer import AgentTracer
from tools.weather_tools import registry as tool_registry

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# ──────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────

WEATHER_PORT   = int(os.getenv("WEATHER_PORT", 5001))
MEMORY_FILE    = Path(os.getenv("WEATHER_MEMORY_FILE", "weather_memory.json"))
LOG_FILE       = Path(os.getenv("WEATHER_LOG_FILE", "weather_agent.log"))
API_KEYS       = set(filter(None, os.getenv("WEATHER_API_KEYS", "dev-key-local").split(",")))
RATE_LIMIT_RPM = int(os.getenv("WEATHER_RATE_LIMIT_RPM", 60))  # req/min par IP
ENV            = os.getenv("FLASK_ENV", "production")
DEV_MODE       = ENV == "development"

# ──────────────────────────────────────────────────────────────
# DÉPENDANCES — initialisées une seule fois
# ──────────────────────────────────────────────────────────────

_router  = ModelRouter()
_context = ContextManager(MEMORY_FILE)
_tracer  = AgentTracer(LOG_FILE if not DEV_MODE else None)

def _llm_factory(task_type: TaskType = TaskType.SYNTHESIZE):
    """
    Factory LLM qui respecte le TaskType.
    - PLAN / EVALUATE  → modèle léger (llama-3.1-8b)
    - SYNTHESIZE / CHAT → modèle puissant (llama-3.3-70b)
    Avant ce fix, tout passait par SYNTHESIZE — le routing était annulé.
    """
    return _router.get(task_type)

_agent = WeatherAgent(
    llm_client_factory = _llm_factory,
    tool_registry      = tool_registry,
    context_manager    = _context,
    tracer             = _tracer,
)

# ──────────────────────────────────────────────────────────────
# RATE LIMITER
# ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Rate limiter sliding window par clé (IP ou session)."""

    def __init__(self, max_per_minute: int):
        self._max   = max_per_minute
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._lock  = threading.Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Retourne (allowed, retry_after_seconds)."""
        now = time.time()
        window_start = now - 60

        with self._lock:
            self._calls[key] = [t for t in self._calls[key] if t > window_start]

            if len(self._calls[key]) >= self._max:
                oldest    = self._calls[key][0]
                retry_in  = int(60 - (now - oldest)) + 1
                return False, retry_in

            self._calls[key].append(now)
            return True, 0

_rate_limiter = RateLimiter(RATE_LIMIT_RPM)

# ──────────────────────────────────────────────────────────────
# FLASK APP
# ──────────────────────────────────────────────────────────────

weather_app = Flask(__name__)
CORS(weather_app, origins=os.getenv("CORS_ORIGINS", "*").split(","))

@weather_app.route("/")
def index():
    return jsonify({
        "service": "WeatherAgent v4",
        "endpoints": {
            "chat":    "/weather/chat",
            "health":  "/weather/health",
            "metrics": "/weather/metrics",
            "tools":   "/weather/tools",
        }
    }), 200
    
# ── Middlewares ──
# Routes publiques — pas d'auth requise
PUBLIC_ROUTES = {"/weather/health", "/weather/metrics", "/weather/tools"}

@weather_app.before_request
def _auth_and_rate_limit():
    if not request.path.startswith("/weather/"):
        return

    # Skip auth sur les routes de monitoring
    if request.path in PUBLIC_ROUTES:
        pass  # pas d'auth, mais rate limiting quand même
    elif not DEV_MODE:
        api_key = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
            or (request.get_json(silent=True) or {}).get("api_key")
        )
        if api_key not in API_KEYS:
            return jsonify({"error": "Unauthorized", "code": 401}), 401

    # Rate limiting par IP (toujours actif)
    client_ip = request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown"
    allowed, retry_after = _rate_limiter.is_allowed(client_ip)
    if not allowed:
        return jsonify({
            "error":       "Rate limit exceeded",
            "retry_after": retry_after,
            "code":        429,
        }), 429

@weather_app.after_request
def _cors_and_security_headers(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["X-Content-Type-Options"]       = "nosniff"
    response.headers["X-Frame-Options"]              = "DENY"
    return response


# ──────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────

@weather_app.route("/weather/chat", methods=["POST", "OPTIONS"])
def weather_chat():
    if request.method == "OPTIONS":
        return "", 204

    try:
        data       = request.get_json(silent=True) or {}
        question   = str(data.get("message", "")).strip()
        session_id = str(data.get("session_id", "default"))

        # Validation
        if not question:
            return jsonify({"reply": "", "session_id": session_id}), 200

        if len(question) > 500:
            return jsonify({
                "reply": "Message trop long (max 500 caractères).",
                "session_id": session_id,
            }), 200

        # Enregistre le turn utilisateur
        _context.add_user_turn(session_id, question)

        # Exécute l'agent
        state = _agent.run(session_id=session_id, user_query=question)

        # Enregistre dans la mémoire long terme
        _context.record_query(
            query    = question,
            city     = state.plan.city if state.plan else None,
            response = state.final_answer,
        )

        # Tente de persister en DB (non bloquant)
        _try_save_db(session_id, question, state.final_answer)

        return jsonify({
            "reply":       state.final_answer,
            "session_id":  session_id,
            "run_id":      state.run_id,
            "iterations":  state.iterations,
            "tools_used":  [r.get("tool_name") for r in state.tool_results],
            "eval_score":  state.eval_result.score if state.eval_result else None,
        }), 200

    except Exception as e:
        _tracer.logger.error("chat.fatal", extra={"extra": {"error": str(e)}})
        return jsonify({
            "reply":      "⚠️ Erreur interne. Réessaie dans un moment.",
            "session_id": (request.get_json(silent=True) or {}).get("session_id", "default"),
        }), 200  # 200 — le client reçoit toujours du JSON valide


@weather_app.route("/weather/health", methods=["GET"])
def health():
    return jsonify({
        **_tracer.get_health(),
        "providers":  _router.status(),
        "sessions":   _context.get_session_count(),
        "env":        ENV,
    }), 200


@weather_app.route("/weather/metrics", methods=["GET"])
def metrics():
    """Endpoint métriques pour Prometheus / Grafana."""
    return jsonify(_tracer.get_metrics_snapshot()), 200


@weather_app.route("/weather/sessions/<session_id>", methods=["DELETE"])
def reset_session(session_id: str):
    _context.reset_session(session_id)
    return jsonify({"status": "reset", "session_id": session_id}), 200


@weather_app.route("/weather/tools", methods=["GET"])
def list_tools():
    """Découverte dynamique des tools disponibles."""
    return jsonify({
        "tools":   tool_registry.list_names(),
        "schemas": tool_registry.to_openai_format(),
    }), 200


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _try_save_db(session_id: str, question: str, answer: str) -> None:
    """Persistance DB optionnelle — ne jamais crasher sur ça."""
    try:
        import sys, os
        sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
        from db import save_message
        save_message(session_id=session_id, agent_type="meteo",
                     role="user",      content=question, model_used="router")
        save_message(session_id=session_id, agent_type="meteo",
                     role="assistant", content=answer,   model_used="router")
    except Exception:
        pass  # DB optionnelle


# ──────────────────────────────────────────────────────────────
# LANCEMENT
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    groq_ok = bool(os.getenv("GROQ_API_KEY"))
    or_ok   = bool(os.getenv("OPENROUTER_API_KEY"))

    if not groq_ok and not or_ok:
        print("ERREUR : Aucune clé API configurée (GROQ_API_KEY ou OPENROUTER_API_KEY)")
        exit(1)

    print("=" * 65)
    print("  WeatherAgent v4 — Agent IA Autonome 2026")
    print(f"  Endpoint : http://localhost:{WEATHER_PORT}/weather/chat")
    print(f"  Health   : http://localhost:{WEATHER_PORT}/weather/health")
    print(f"  Metrics  : http://localhost:{WEATHER_PORT}/weather/metrics")
    print(f"  Tools    : http://localhost:{WEATHER_PORT}/weather/tools")
    print(f"  Groq     : {'✓' if groq_ok else '✗'} | OpenRouter : {'✓' if or_ok else '✗'}")
    print(f"  Mode     : {ENV} | Rate limit : {RATE_LIMIT_RPM} req/min")
    print(f"  Cycle    : Observe → Plan → Act → Evaluate → Respond")
    print("=" * 65)

    weather_app.run(
        host     = "0.0.0.0",
        port     = WEATHER_PORT,
        debug    = DEV_MODE,
        threaded = True,
    )