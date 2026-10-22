"""
worker.py — Worker subprocess isolé pour l'Agent Historique Dourbia

Reçoit une requête JSON via stdin, retourne une réponse JSON via stdout.
Complètement stateless : le contexte session est injecté par Aziz à chaque appel.

Usage (Aziz spawne ce script) :
    python -m AgentPrincipal.agents.historical.worker

Format entrée (stdin, une ligne JSON) :
    {
        "query": "Explique les Thermes d'Antonin",
        "query_embedding": [0.12, -0.34, ...],   // 384 floats
        "language": "fr",
        "session_context": {},                    // dict Redis L1 injecté par Aziz
        "web_search_enabled": false
    }

Format sortie (stdout, une ligne JSON) :
    {
        "answer": "...",
        "sources": [{"title": "...", "score": 0.82, "source_type": "monument"}],
        "retrieval_score": 0.82,
        "used_web_fallback": false,
        "language": "fr",
        "error": null
    }
"""
from __future__ import annotations

import json
import logging
import os
import sys, io
import traceback
from typing import Any

# INTEGRATION NOTE: Pas d'imports de app/ Dourbia ici — isolation namespace totale.
# Tous les modules nécessaires sont dans AgentPrincipal/agents/historical/
from AgentPrincipal.agents.historical.rag_pipeline import HistoricalRAGPipeline
from AgentPrincipal.agents.historical.llm_bridge import call_groq_for_history
from AgentPrincipal.agents.historical.prompts import build_rag_prompt, INSUFFICIENT_CONTEXT
from dotenv import load_dotenv
load_dotenv(r"E:\claude\.env")
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [historical_worker] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "worker_debug.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)

# On garde notre propre logger en WARNING utile, mais on fait taire
# le bruit interne d'httpx/httpcore (TLS, cipher suites, etc.)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger.setLevel(logging.WARNING)

RAG_MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.65"))
RAG_SCORE_GAP = float(os.environ.get("RAG_SCORE_GAP", "0.08"))
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))

# DB URL ciblant sig_dourbia (Dourbia, pas l'agent externe)
DB_URL = os.environ.get(
    "HISTORICAL_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/sig_dourbia",
)


def _ok(answer: str, sources: list, retrieval_score: float, used_web: bool, language: str) -> str:
    return json.dumps({
        "answer": answer,
        "sources": sources,
        "retrieval_score": retrieval_score,
        "used_web_fallback": used_web,
        "language": language,
        "error": None,
    }, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({
        "answer": "",
        "sources": [],
        "retrieval_score": 0.0,
        "used_web_fallback": False,
        "language": "fr",
        "error": message,
    }, ensure_ascii=False)


def process_request(payload: dict[str, Any], pipeline: HistoricalRAGPipeline) -> str:
    """Traite une requête et retourne la réponse JSON."""
    query: str = payload.get("query", "").strip()
    query_embedding: list[float] = payload.get("query_embedding", [])
    language: str = payload.get("language", "fr")
    session_context: dict = payload.get("session_context", {})
    # L'agent historique décide lui-même via son propre .env,
    # indépendamment de ce que l'orchestrateur envoie.
    web_search_enabled: bool = (
        os.environ.get("WEB_SEARCH_ENABLED", "false").lower() == "true"
    )

    if not query:
        return _err("query vide")
    if not query_embedding:
        return _err("query_embedding manquant")

    # --- Retrieval RAG ---
    try:
        chunks = pipeline.retrieve(
            query=query,
            query_embedding=query_embedding,
            top_k=RAG_TOP_K,
            language=language if language in ("fr", "en", "ar") else None,
        )
    except Exception as exc:
        logger.error("Retrieval error: %s", exc)
        return _err(f"Erreur retrieval: {exc}")

    retrieval_score = float(chunks[0]["score"]) if chunks else 0.0
    used_web = False

    # Filtrer les chunks sous le score minimum
    good_chunks = [c for c in chunks if c["score"] >= RAG_MIN_SCORE]

    logger.warning(
        "DEBUG query=%r nb_chunks=%d nb_good_chunks=%d web_search_enabled=%s",
        query,
        len(chunks),
        len(good_chunks),
        web_search_enabled,
    )

    # --- Fallback web (optionnel) ---
    web_context = ""
    if not good_chunks and web_search_enabled:
        try:
            from AgentPrincipal.agents.historical.web_fallback import search_web
            web_results = search_web(query, language=language)
            if web_results:
                used_web = True
                web_context = "\n\n".join(
                    f"[Web] {r['title']}: {r['body']}" for r in web_results[:3]
                )
        except Exception as exc:
            logger.warning("Web fallback failed: %s", exc)

    # --- Réponse si aucun contexte ---
    if not good_chunks and not web_context:
        no_info = INSUFFICIENT_CONTEXT.get(language, INSUFFICIENT_CONTEXT["fr"])
        return _ok(no_info, [], retrieval_score, False, language)

    # --- Construction du prompt et appel LLM ---
    try:
        prompt_messages = build_rag_prompt(
            query=query,
            chunks=good_chunks,
            language=language,
            session_context=session_context,
            web_context=web_context or None,
        )
        answer = call_groq_for_history(prompt_messages)
    except Exception as exc:
        logger.error("LLM call error: %s", exc)
        return _err(f"Erreur LLM: {exc}")

    # --- Formatter les sources pour Aziz ---
    # Si le web a servi de fallback, on n'affiche pas les chunks locaux
    # sous le seuil (ils étaient insuffisants, pas des sources fiables).
    if used_web:
        sources = [{"title": "Recherche web", "score": None, "source_type": "web"}]
    else:
        sources = [
            {
                "title": c.get("title") or "",
                "score": round(c["score"], 4),
                "source_type": c["source_type"],
                "chunk_text": c.get("chunk_text") or "",
            }
            for c in good_chunks[:3]
        ]
    return _ok(answer, sources, retrieval_score, used_web, language)

def main() -> None:
    """Boucle principale stdin/stdout JSON."""
    logger.info("Worker historique démarré (DB=%s)", DB_URL)

    try:
        pipeline = HistoricalRAGPipeline(DB_URL)
    except Exception as exc:
        # Signal d'erreur critique au démarrage
        print(_err(f"Impossible d'initialiser le pipeline RAG: {exc}"), flush=True)
        sys.exit(1)

    # Signaler à Aziz que le worker est prêt
    print(json.dumps({"status": "ready"}), flush=True)

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            print(_err(f"JSON invalide: {exc}"), flush=True)
            continue

        try:
            result = process_request(payload, pipeline)
        except Exception as exc:
            logger.error("Erreur interne lors du traitement de la requête: %s", exc)
            result = _err(f"Erreur interne: {exc}")

        try:
            print(result, flush=True)
        except Exception:
            tb = traceback.format_exc()
            logger.error("Erreur d'écriture stdout: %s", tb)
            try:
                print(_err("Erreur d'encodage de la réponse"), flush=True)
            except Exception:
                pass

    pipeline.close()
    logger.info("Worker historique arrêté proprement")


if __name__ == "__main__":
    main()
