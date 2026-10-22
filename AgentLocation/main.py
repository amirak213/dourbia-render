"""
main.py — Point d'entrée unique de Dourbia v8.

Lance avec :
    python main.py
ou en prod :
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
"""

import asyncio
import logging
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dourbia.main")

from dotenv import load_dotenv
load_dotenv(r"E:\claude\.env")

from api.routes import app  # noqa
from core.config import settings  # noqa

if __name__ == "__main__":
    import uvicorn

    if not settings.groq_api_key:
        log.error("❌ GROQ_API_KEY manquante dans .env")
        sys.exit(1)
    if not settings.admin_api_key:
        log.warning("⚠  ADMIN_API_KEY non définie — endpoints /api/* désactivés")

    log.info(f"🚗 Dourbia Agent Yasmine v8.0 — port {settings.flask_port}")
    log.info(f"   Modèle LLM    : {settings.groq_model}")
    log.info(f"   Guard LLM     : {settings.groq_model_guard}")
    log.info(f"   Guardrails    : {'ON' if settings.guardrails_enabled else 'OFF'}")
    log.info(f"   Reflexion     : {'ON' if settings.reflection_enabled else 'OFF'}")
    log.info(f"   Auto-confirm  : {'ON' if settings.auto_confirm_actif else 'OFF'}")

    os.chdir(ROOT)
    workers = 1 if sys.platform == "win32" else settings.uvicorn_workers
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT") or settings.flask_port),
        reload=False,
        log_level="info",
        workers=workers,
    )
