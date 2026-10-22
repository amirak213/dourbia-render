"""
Worker persistant pour dourbia — tourne indéfiniment, lit des JSONs ligne par ligne sur stdin.
"""

import json
from logging import log
import sys
import os
import asyncio
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr

DOURBIA = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "AgentLocation")
)
sys.path.insert(0, DOURBIA)
os.chdir(DOURBIA)

from agents.agent import run_agent


async def handle(data):
    reply, tokens = await run_agent(data["message"], data["session_id"])
    return {"reply": reply, "tokens": tokens}


async def main():
    import logging
    log = logging.getLogger("chatbot.agent_reservation_worker")
    from memory.memory_manager import _get_embedding_model

    await _get_embedding_model()
    log.info("[WORKER] BERT prêt.")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            result = await handle(data)
        except Exception as e:
            import traceback

            result = {
                "reply": "Erreur technique — réessayez.",
                "tokens": 0,
                "error": str(e),
            }
        _REAL_STDOUT.write(json.dumps(result, ensure_ascii=False) + "\n")
        _REAL_STDOUT.flush()


asyncio.run(main())
