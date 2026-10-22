from __future__ import annotations

from typing import Any

from app.rag.language_messages import SUGGESTED_ACTIONS
from app.rag.text_utils import normalize_text


def get_suggested_action_intent(message: str) -> str | None:
    """Map a UI suggested-action click to a stable intent key."""
    normalized = normalize_text(message)
    if not normalized:
        return None

    for intent, translations in SUGGESTED_ACTIONS.items():
        if intent == "ask_another":
            continue
        for text in translations.values():
            action_norm = normalize_text(text)
            if normalized == action_norm or normalized in action_norm:
                return intent
    return None


def all_suggested_action_phrases() -> tuple[str, ...]:
    phrases: list[str] = []
    for intent, translations in SUGGESTED_ACTIONS.items():
        if intent == "ask_another":
            continue
        phrases.extend(translations.values())
    return tuple(phrases)


def build_retrieval_query_for_action(
    intent: str,
    memory_context: dict[str, Any],
) -> str | None:
    last_monuments = memory_context.get("last_mentioned_monuments") or []
    primary_monument = str(last_monuments[0]) if last_monuments else ""
    site_name = str(memory_context.get("primary_site_name") or "").strip()

    if intent == "show_hours":
        if primary_monument:
            return f"horaires {primary_monument} Carthage"
        return "horaires monuments Carthage"

    if intent == "circuit_detail":
        parts = ["circuit Carthage"]
        if site_name:
            parts.append(site_name)
        elif primary_monument:
            parts.append(primary_monument)
        return " ".join(parts)

    if intent == "nearby_monuments":
        parts = ["monuments proches Carthage"]
        if primary_monument:
            parts.append(primary_monument)
        return " ".join(parts)

    if intent == "roman_circuit":
        return "circuit romain Carthage"

    if intent == "time_adapted_visit":
        minutes = memory_context.get("available_time_minutes")
        if minutes:
            return f"circuit Carthage {minutes} minutes"
        return "circuit Carthage visite"

    return None
