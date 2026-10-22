"""
llm_bridge.py — Appel Groq pour l'Agent Historique

INTEGRATION NOTE: Utilise httpx directement (pas le client Groq de Dourbia)
car ce worker tourne en subprocess isolé. Il lit GROQ_API_KEY_PRINCIPAL
(fallback GROQ_API_KEY) depuis l'env, comme le reste de Dourbia.
"""
from __future__ import annotations

import os
import logging
import httpx

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# INTEGRATION NOTE: Même modèle que celui utilisé par Aziz pour les tâches
# de génération de texte.
HISTORICAL_MODEL = os.environ.get(
    "HISTORICAL_LLM_MODEL",
    os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
)
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30.0"))
LLM_MAX_TOKENS = int(os.environ.get("HISTORICAL_MAX_TOKENS", "700"))
LLM_TEMPERATURE = float(os.environ.get("HISTORICAL_TEMPERATURE", "0.2"))


def call_groq_for_history(messages: list[dict[str, str]]) -> str:
    """
    Appelle l'API Groq avec les messages RAG construits et retourne la réponse.

    Args:
        messages: Liste de dicts {"role": ..., "content": ...}

    Returns:
        Texte de la réponse (déjà strippé).

    Raises:
        RuntimeError: Si l'appel échoue ou la clé est absente.
    """
    api_key = (
        os.environ.get("GROQ_API_KEY_PRINCIPAL", "").strip()
        or os.environ.get("GROQ_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY_PRINCIPAL (ou GROQ_API_KEY) manquant dans l'environnement du worker historique."
        )

    payload = {
        "model": HISTORICAL_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
        "reasoning_effort": "low",
        "include_reasoning": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(connect=5.0, read=LLM_TIMEOUT, write=5.0, pool=5.0)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(GROQ_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            raise RuntimeError("Groq : clé API invalide (401).") from exc
        if status == 429:
            raise RuntimeError("Groq : rate limit atteint (429). Réessayer.") from exc
        raise RuntimeError(f"Groq : erreur HTTP {status}.") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Groq : erreur réseau — {exc}") from exc

    try:
        choice = data["choices"][0]
        logger.info(
            "Historical Groq response: finish_reason=%s usage=%s",
            choice.get("finish_reason"),
            data.get("usage"),
        )
        return choice["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise RuntimeError(f"Groq : format de réponse inattendu — {exc}") from exc
