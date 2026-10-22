"""
db.py — Connexion PostgreSQL partagée entre tous les agents
Utilise psycopg2 avec un pool de connexions thread-safe.
"""

import os
import uuid
import threading
from datetime import datetime
from contextlib import contextmanager
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import psycopg2
from psycopg2 import pool

# ── Config depuis .env ────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "tourisme"),     # ← ton nom de base
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# Pool de 2 à 10 connexions (Flask est multi-thread)
_pool: pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pool.ThreadedConnectionPool(2, 10, **DB_CONFIG)
    return _pool


@contextmanager
def get_conn():
    """Context manager : prend une connexion du pool, la rend après usage."""
    p   = get_pool()
    con = p.getconn()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        p.putconn(con)


# ── Fonctions publiques ───────────────────────────────────────

def save_message(
    session_id: str,
    agent_type: str,
    role: str,           # 'user' | 'assistant' | 'tool' | 'system'
    content: str,
    model_used: str | None = None,
    token_count: int | None = None,
    cost_usd: float | None = None,
    parent_agent: str | None = None,
    tool_call_id: str | None = None,
) -> str:
    """Insère un message dans la table conversations. Retourne l'UUID inséré."""
    msg_id = str(uuid.uuid4())
    sql = """
        INSERT INTO conversations
            (id, session_id, agent_type, role, content,
             model_used, token_count, cost_usd,
             parent_agent, tool_call_id, created_at)
        VALUES
            (%s, %s, %s, %s, %s,
             %s, %s, %s,
             %s, %s, %s)
    """
    with get_conn() as con:
        with con.cursor() as cur:
            cur.execute(sql, (
                msg_id, session_id, agent_type, role, content,
                model_used, token_count, cost_usd,
                parent_agent, tool_call_id,
                datetime.utcnow(),
            ))
    return msg_id


def get_history(session_id: str, agent_type: str | None = None) -> list[dict]:
    """
    Récupère l'historique d'une session.
    Si agent_type=None → tous les agents (pour partage de contexte inter-agents).
    """
    if agent_type:
        sql = """
            SELECT role, content, agent_type, created_at
            FROM conversations
            WHERE session_id = %s AND agent_type = %s
            ORDER BY created_at ASC
        """
        params = (session_id, agent_type)
    else:
        sql = """
            SELECT role, content, agent_type, created_at
            FROM conversations
            WHERE session_id = %s
            ORDER BY created_at ASC
        """
        params = (session_id,)

    with get_conn() as con:
        with con.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [
        {"role": r[0], "content": r[1], "agent_type": r[2], "created_at": str(r[3])}
        for r in rows
    ]
    
    
# (print du DB_CONFIG retire : il exposait le mot de passe dans les logs)