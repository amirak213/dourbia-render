"""
Utilitaires partagés — évite les imports circulaires.
"""

from __future__ import annotations
import json

def safe_json_parse(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
