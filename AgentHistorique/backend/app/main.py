import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_chat import router as chat_router
from app.api.routes_circuit_agent import router as circuit_router
from app.api.routes_health import router as health_router
from app.api.routes_monuments import router as monuments_router
from app.config import get_settings
from app.llm.llm_client import validate_llm_settings
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if request.url.path.startswith("/api/"):
        logger.info(
            "HTTP %s %s status=%s elapsed_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response


@app.on_event("startup")
def log_llm_configuration() -> None:
    get_settings.cache_clear()
    runtime_settings = get_settings()
    from app.rag.embeddings import create_embedding_provider

    logger.info("Preloading embedding model (first request latency optimization)...")
    create_embedding_provider()
    logger.info("Embedding model ready.")
    logger.info(
        "LLM configuration: provider=%s model=%s",
        runtime_settings.llm_provider,
        runtime_settings.llm_model_name,
    )
    logger.info(
        "Web search configuration: enabled=%s provider=%s region=%s max_results=%s",
        runtime_settings.web_search_enabled,
        runtime_settings.web_search_provider,
        runtime_settings.web_search_region,
        runtime_settings.web_search_max_results,
    )
    for warning in validate_llm_settings(runtime_settings):
        logger.warning(warning)


_STATIC_DIR = Path(__file__).resolve().parent / "static"

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(circuit_router)
app.include_router(monuments_router)

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/chat-ui", include_in_schema=False)
def chat_ui() -> FileResponse:
    """Zero-dependency demo UI (no Node.js required)."""
    return FileResponse(_STATIC_DIR / "chat.html")
