from __future__ import annotations
import asyncio, json, logging
from typing import Optional
from core.config import settings
from core.infra import get_pool, get_redis, record_to_dict
import os

log = logging.getLogger("dourbia.memory")
_embedding_model = None
_embed_lock = asyncio.Lock()


async def _get_embedding_model():
    global _embedding_model
    if os.environ.get("MEMORY_EMBEDDINGS", "on") == "off":
        return None
    if _embedding_model is None:
        async with _embed_lock:
            if _embedding_model is None:
                try:
                    from sentence_transformers import SentenceTransformer

                    _embedding_model = await asyncio.to_thread(
                        SentenceTransformer, settings.embedding_model
                    )
                    log.info(f"[MEMORY] Modèle chargé : {settings.embedding_model}")
                except ImportError:
                    log.warning(
                        "[MEMORY] sentence-transformers absent — mémoire vectorielle désactivée"
                    )
                except Exception as e:
                    log.warning(
                        f"[MEMORY] Impossible de charger le modèle ({e}) — mémoire vectorielle désactivée"
                    )
    return _embedding_model


async def embed(text: str) -> Optional[list]:
    model = await _get_embedding_model()
    if model is None:
        return None
    try:
        vec = await asyncio.to_thread(model.encode, text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as e:
        log.warning(f"[MEMORY] embed erreur : {e}")
        return None


async def store_episodic(session_id, content, importance=0.5, metadata=None):
    vec = await embed(content)
    if vec is None:
        return None
    pool = await get_pool()
    try:
        eid = await pool.fetchval(
            """
            INSERT INTO episodic_memory (session_id,content,embedding,importance,metadata)
            VALUES ($1,$2,$3,$4,$5) RETURNING id
        """,
            session_id,
            content,
            vec,
            importance,
            json.dumps(metadata or {}),
        )
        return str(eid)
    except Exception as e:
        log.warning(f"[MEMORY] store_episodic erreur : {e}")
        return None


async def recall_episodic(session_id, query, top_k=None, min_importance=0.3):
    top_k = top_k or settings.vector_top_k
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT id,content,importance,metadata,created_at
            FROM episodic_memory
            WHERE session_id=$1 AND importance>=$2
              AND (expires_at IS NULL OR expires_at>NOW())
            ORDER BY created_at DESC LIMIT $3
        """,
            session_id,
            min_importance,
            top_k,
        )
        return [record_to_dict(r) for r in rows]
    except Exception as e:
        log.warning(f"[MEMORY] recall_episodic erreur : {e}")
        return []


def format_episodic_context(episodes):
    if not episodes:
        return ""
    lines = ["[CONTEXTE MÉMORISÉ — ce que je sais déjà sur ce client]"]
    for ep in episodes:
        lines.append(f"  • {ep['content']}")
    return "\n".join(lines) if len(lines) > 1 else ""


async def store_lesson(trigger_pattern, lesson, error_type):
    vec = await embed(trigger_pattern)
    pool = await get_pool()
    try:
        lid = await pool.fetchval(
            """
            INSERT INTO procedural_memory (trigger_embedding,trigger_pattern,lesson,error_type)
            VALUES ($1,$2,$3,$4) RETURNING id
        """,
            vec,
            trigger_pattern,
            lesson,
            error_type,
        )
        log.info(f"[MEMORY] Leçon [{error_type}] stockée")
        return str(lid)
    except Exception as e:
        log.warning(f"[MEMORY] store_lesson erreur : {e}")
        return None


async def recall_lessons(query, top_k=3):
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT id,trigger_pattern,lesson,error_type,applied_count,success_rate
            FROM procedural_memory
            ORDER BY applied_count DESC LIMIT $1
        """,
            top_k,
        )
        return [record_to_dict(r) for r in rows]
    except Exception as e:
        log.warning(f"[MEMORY] recall_lessons erreur : {e}")
        return []


def format_lessons_context(lessons):
    if not lessons:
        return ""
    lines = ["[LEÇONS APPRISES — éviter ces erreurs]"]
    for l in lessons:
        lines.append(f"  ⚠ [{l['error_type']}] {l['lesson']}")
    return "\n".join(lines)


_memory_fallback = {}


async def get_history(session_id):
    try:
        r = await get_redis()
        raw = await r.get(f"history:{session_id}")
        return json.loads(raw) if raw else []
    except Exception as e:
        log.warning(f"[MEMORY] get_history erreur : {e}")
        return _memory_fallback.get(session_id, [])


async def set_history(session_id, history):
    trimmed = history[-20:]
    try:
        r = await get_redis()
        await r.setex(
            f"history:{session_id}",
            settings.history_ttl_seconds,
            json.dumps(trimmed, ensure_ascii=False, default=str),
        )
    except Exception as e:
        log.warning(f"[MEMORY] set_history erreur : {e}")
        _memory_fallback[session_id] = trimmed


def trim_history(history, max_tokens=6000):
    if not history:
        return history

    result = list(history[-4:])
    tokens = sum(len(str(m.get("content", ""))) // 4 for m in result)

    for msg in reversed(history[:-4]):
        t = len(str(msg.get("content", ""))) // 4
        if tokens + t > max_tokens:
            break
        result.insert(0, msg)
        tokens += t

    while result and result[0]["role"] == "tool":
        result = result[1:]

    cleaned = []
    i = 0
    while i < len(result):
        msg = result[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            expected_ids = {tc["id"] for tc in msg["tool_calls"]}
            j = i + 1
            found_ids = set()
            while j < len(result) and result[j].get("role") == "tool":
                found_ids.add(result[j].get("tool_call_id", ""))
                j += 1
            if expected_ids.issubset(found_ids):
                cleaned.append(msg)
                while i + 1 < len(result) and result[i + 1].get("role") == "tool":
                    i += 1
                    cleaned.append(result[i])
            else:
                while i + 1 < len(result) and result[i + 1].get("role") == "tool":
                    i += 1
            i += 1
            continue
        cleaned.append(msg)
        i += 1

    return cleaned


async def summarize_episode(user_message, assistant_reply, tools_called, groq_client):
    tools_summary = (
        f" (outils: {', '.join(t.get('name','') for t in tools_called)})"
        if tools_called
        else ""
    )
    if len(user_message) < 100 and not tools_called:
        return f"Client: {user_message[:80]} | Agent: {assistant_reply[:80]}"
    try:
        resp = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model=settings.groq_model_fast,
            max_tokens=150,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": f"Résume en 1-2 phrases ce tour (infos clés: entités, actions).\nUser: {user_message[:200]}\nAgent: {assistant_reply[:200]}\nOutils: {tools_summary}\nRésumé:",
                }
            ],
        )
        return resp.choices[0].message.content.strip()
    except:
        return f"Client: {user_message[:60]} | Agent: {assistant_reply[:60]}{tools_summary}"


async def compute_episode_importance(tools_called, has_reservation, has_error):
    if has_reservation:
        return 0.9
    if has_error:
        return 0.7
    if tools_called:
        return 0.6
    return 0.4
