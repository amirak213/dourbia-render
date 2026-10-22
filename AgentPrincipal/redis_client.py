"""
redis_client.py — Connexion Redis singleton pour AgentPrincipal.

Aligné sur le pattern déjà utilisé dans AgentLocation/core/infra.py
(get_redis() / close_redis(), redis.asyncio, singleton global).

Utilisé par wizard_state_machine.py pour stocker l'état du wizard
conversationnel (WizardSession) — séparé de session_memory.py qui
reste en dict RAM pour l'historique/profil général.

Usage :
    from redis_client import get_redis

    async def quelque_part():
        r = await get_redis()
        await r.set("clé", "valeur")
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from constants import REDIS_URL

log = logging.getLogger("chatbot.redis_client")

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Retourne l'instance singleton du client Redis async.
    Crée la connexion au premier appel, la réutilise ensuite."""
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(
            REDIS_URL, encoding="utf-8", decode_responses=True
        )
        log.info("[REDIS] Connecté (AgentPrincipal)")
    return _redis


async def close_redis() -> None:
    """Ferme proprement la connexion Redis (à appeler au shutdown FastAPI)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        log.info("[REDIS] Déconnecté (AgentPrincipal)")
