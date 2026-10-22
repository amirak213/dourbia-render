"""
memory.py — Gestion de la mémoire session du chatbot.

Stocke l'historique de conversation (sliding window 6 échanges)
et le profil utilisateur en mémoire (dict en RAM pour la session).

Pour la persistance PostgreSQL, les TODO sont marqués clairement.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from typing import Optional
from constants import HISTORY_WINDOW

log = logging.getLogger("chatbot.memory")

# ─────────────────────────────────────────────────────────────────────────────
# STOCKAGE EN MÉMOIRE (remplacer par PostgreSQL en prod)
# ─────────────────────────────────────────────────────────────────────────────

# { session_id: { "history": [...], "profil": {...}, "created_at": datetime } }
_sessions: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# GESTION HISTORIQUE
# ─────────────────────────────────────────────────────────────────────────────

def get_history(session_id: str) -> list[dict]:
    """
    Retourne l'historique de conversation d'une session.

    Format : [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    Retourne une liste vide si la session n'existe pas.
    """
    session = _sessions.get(session_id, {})
    return list(session.get("history", []))


def set_history(session_id: str, history: list[dict]) -> None:
    """
    Sauvegarde l'historique complet d'une session.
    Applique la fenêtre glissante : garde les HISTORY_WINDOW derniers échanges.
    Un échange = 1 message user + 1 message assistant = 2 entrées.
    """
    _ensure_session(session_id)

    # Sliding window : garder les 2 * HISTORY_WINDOW dernières entrées
    max_entries = HISTORY_WINDOW * 2
    if len(history) > max_entries:
        history = history[-max_entries:]

    _sessions[session_id]["history"] = history
    _sessions[session_id]["last_active"] = datetime.now()

    log.debug(f"[MEMORY] {session_id} — historique sauvegardé ({len(history)} entrées)")

    # TODO: persister en PostgreSQL
    # await db.execute(
    #     "UPDATE sessions SET history = $1, last_active = NOW() WHERE session_id = $2",
    #     json.dumps(history), session_id
    # )


def append_to_history(session_id: str, role: str, content: str) -> None:
    """
    Ajoute un message à l'historique et applique la sliding window.
    Raccourci pour set_history après append.
    """
    history = get_history(session_id)
    history.append({"role": role, "content": content})
    set_history(session_id, history)


def clear_history(session_id: str) -> None:
    """Vide l'historique d'une session (utile pour reset)."""
    _ensure_session(session_id)
    _sessions[session_id]["history"] = []
    log.info(f"[MEMORY] {session_id} — historique effacé")


# ─────────────────────────────────────────────────────────────────────────────
# GESTION PROFIL UTILISATEUR
# ─────────────────────────────────────────────────────────────────────────────

def get_profile(session_id: str) -> dict:
    """
    Retourne le profil utilisateur extrait de la session.
    Contient les signaux accumulés au fil des messages.

    Exemple :
    {
        "langue": "FR",
        "budget": 150,
        "taille_groupe": 4,
        "type_groupe": "famille",
        "duree": "journée",
        "lieux_vus": ["Carthage", "Médina"],
        "preferences": ["outdoor", "histoire"],
        "derniere_intention": "CIRCUIT"
    }
    """
    session = _sessions.get(session_id, {})
    return dict(session.get("profil", {}))


def update_profile(session_id: str, signals: dict) -> None:
    """
    Met à jour le profil utilisateur avec les nouveaux signaux extraits.
    Merge intelligent : ne remplace que les champs non-None.
    Les lieux s'accumulent (liste), les autres champs se mettent à jour.
    """
    _ensure_session(session_id)
    profil = _sessions[session_id].get("profil", {})

    for key, value in signals.items():
        if value is None:
            continue

        # Accumulation des lieux visités
        if key == "lieux_vus" and isinstance(value, list):
            existing = profil.get("lieux_vus", [])
            for lieu in value:
                if lieu not in existing:
                    existing.append(lieu)
            profil["lieux_vus"] = existing

        # Accumulation des préférences
        elif key == "preferences" and isinstance(value, list):
            existing = profil.get("preferences", [])
            for pref in value:
                if pref not in existing:
                    existing.append(pref)
            profil["preferences"] = existing

        # Mise à jour simple pour les autres champs
        else:
            profil[key] = value

    _sessions[session_id]["profil"] = profil
    log.debug(f"[MEMORY] {session_id} — profil mis à jour : {list(signals.keys())}")

    # TODO: persister en PostgreSQL
    # await db.execute(
    #     "UPDATE sessions SET profil = $1 WHERE session_id = $2",
    #     json.dumps(profil), session_id
    # )


# ─────────────────────────────────────────────────────────────────────────────
# GESTION SESSIONS
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_session(session_id: str) -> None:
    """Crée la session si elle n'existe pas."""
    if session_id not in _sessions:
        _sessions[session_id] = {
            "history": [],
            "profil": {},
            "created_at": datetime.now(),
            "last_active": datetime.now(),
        }
        log.info(f"[MEMORY] Nouvelle session créée : {session_id}")

        # TODO: persister en PostgreSQL
        # await db.execute(
        #     "INSERT INTO sessions (session_id, created_at) VALUES ($1, NOW()) ON CONFLICT DO NOTHING",
        #     session_id
        # )


def get_session_info(session_id: str) -> dict:
    """Retourne les métadonnées d'une session (sans l'historique)."""
    session = _sessions.get(session_id, {})
    return {
        "session_id": session_id,
        "exists": bool(session),
        "nb_messages": len(session.get("history", [])),
        "created_at": session.get("created_at"),
        "last_active": session.get("last_active"),
        "profil": session.get("profil", {}),
    }


def list_active_sessions() -> list[str]:
    """Liste les IDs de sessions actives (utile pour debug)."""
    return list(_sessions.keys())


def purge_session(session_id: str) -> None:
    """Supprime complètement une session (RGPD, reset)."""
    if session_id in _sessions:
        del _sessions[session_id]
        log.info(f"[MEMORY] Session supprimée : {session_id}")

SESSION_INACTIVITY_TTL = timedelta(hours=6)

def purge_inactive_sessions(ttl: timedelta = SESSION_INACTIVITY_TTL) -> int:
    """
    Supprime les sessions inactives depuis plus de `ttl`.
    Retourne le nombre de sessions purgées. Appelée périodiquement
    par la tâche de fond du lifespan (app.py).
    """
    now = datetime.now()
    to_purge = [
        sid for sid, session in _sessions.items()
        if now - session.get("last_active", now) > ttl
    ]
    for sid in to_purge:
        purge_session(sid)
    if to_purge:
        log.info(f"[MEMORY] Purge auto : {len(to_purge)} session(s) inactive(s) supprimée(s)")
    return len(to_purge)

def set_active_circuit(session_id: str, circuit_id: str) -> None:
    """Enregistre le circuit actif pour cette session (mode guide GPS)."""
    _ensure_session(session_id)
    _sessions[session_id]["circuit_actif"] = circuit_id
    log.info(f"[MEMORY] {session_id} — circuit actif : {circuit_id}")


def get_active_circuit(session_id: str) -> Optional[str]:
    """Retourne le circuit actif de la session, ou None si aucun choisi."""
    session = _sessions.get(session_id, {})
    return session.get("circuit_actif")


def clear_profile_fields(session_id: str, *keys: str) -> None:
    """
    Force la suppression de champs du profil (bypass le filtre anti-None de update_profile).
    Nécessaire pour réinitialiser un état ponctuel (ex: monument_en_attente après traitement).
    """
    _ensure_session(session_id)
    profil = _sessions[session_id].get("profil", {})
    for key in keys:
        profil[key] = None
    _sessions[session_id]["profil"] = profil
    log.debug(f"[MEMORY] {session_id} — champs effacés : {keys}")
