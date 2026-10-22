from __future__ import annotations

import re
from typing import Any

from app.rag.text_utils import normalize_text

MAX_MONUMENTS = 5

INTEREST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "romain": ("romain", "romaine", "romains", "romaines"),
    "punique": ("punique", "puniques", "carthaginois"),
    "byzantin": ("byzantin", "byzantine", "byzantins", "byzantines"),
    "architecture": ("architecture", "architectural", "architecturale"),
    "musee": ("musee", "musée", "musees", "musées"),
    "circuit": ("circuit", "circuits", "parcours", "itineraire", "itinéraire"),
}

MOBILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "walking": ("a pied", "à pied", "pedestre", "pédestre", "walking", "marche"),
    "cycling": ("velo", "vélo", "cyclable", "cyclables", "cycling", "bicyclette"),
}

LANGUAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "en": ("english", "anglais", "in english"),
    "ar": ("arabic", "arabe", "بالعربية"),
    "fr": ("francais", "français", "in french"),
}

TIME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d+)\s*h\s*(\d+)\s*(?:min(?:ute)?s?)?", re.IGNORECASE), "hours_minutes"),
    (re.compile(r"(\d+)\s*h(?:eure)?s?\b", re.IGNORECASE), "hours"),
    (re.compile(r"(\d+)\s*(?:min(?:ute)?s?)\b", re.IGNORECASE), "minutes"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*h(?:eure)?s?\b", re.IGNORECASE), "decimal_hours"),
)


def extract_preferences_from_message(message: str) -> dict[str, Any]:
    """Extract session preferences from a single user message."""
    normalized = normalize_text(message)
    updates: dict[str, Any] = {}

    language = _extract_language(normalized)
    if language:
        updates["preferred_language"] = language

    interests = _extract_interests(normalized)
    if interests:
        updates["interests"] = interests

    available_time = _extract_available_time_minutes(message)
    if available_time is not None:
        updates["available_time_minutes"] = available_time

    mobility_mode = _extract_mobility_mode(normalized)
    if mobility_mode:
        updates["mobility_mode"] = mobility_mode

    return updates


def merge_memory_updates(
    current: dict[str, Any],
    extracted: dict[str, Any],
    memory_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge newly extracted preferences and agent memory updates."""
    merged = dict(current)

    if "preferred_language" in extracted:
        merged["preferred_language"] = extracted["preferred_language"]

    if "available_time_minutes" in extracted:
        merged["available_time_minutes"] = extracted["available_time_minutes"]

    if "mobility_mode" in extracted:
        merged["mobility_mode"] = extracted["mobility_mode"]

    if "primary_site_id" in extracted:
        merged["primary_site_id"] = extracted["primary_site_id"]

    if "primary_site_name" in extracted:
        merged["primary_site_name"] = extracted["primary_site_name"]

    if "interests" in extracted:
        merged["interests"] = _merge_interests(
            merged.get("interests") or [],
            extracted["interests"],
        )

    cited_monuments = (memory_updates or {}).get("last_mentioned_monuments") or []
    if cited_monuments:
        merged["last_mentioned_monuments"] = _merge_monuments(
            merged.get("last_mentioned_monuments") or [],
            cited_monuments,
        )

    for key in ("primary_site_id", "primary_site_name"):
        if key in (memory_updates or {}):
            merged[key] = memory_updates[key]

    if "last_substantive_user_message" in extracted:
        merged["last_substantive_user_message"] = extracted["last_substantive_user_message"]

    return merged


def build_memory_context(
    *,
    preferred_language: str,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Return the compact memory context consumed by HistoricalAgent."""
    return {
        "preferred_language": preferred_language,
        "interests": list(preferences.get("interests") or []),
        "available_time_minutes": preferences.get("available_time_minutes"),
        "mobility_mode": preferences.get("mobility_mode"),
        "last_mentioned_monuments": list(preferences.get("last_mentioned_monuments") or []),
        "primary_site_id": preferences.get("primary_site_id"),
        "primary_site_name": preferences.get("primary_site_name"),
        "last_substantive_user_message": preferences.get("last_substantive_user_message"),
    }


def _extract_language(normalized_message: str) -> str | None:
    for language, keywords in LANGUAGE_KEYWORDS.items():
        if any(keyword in normalized_message for keyword in keywords):
            return language
    return None


def _extract_interests(normalized_message: str) -> list[str]:
    found: list[str] = []
    for interest, keywords in INTEREST_KEYWORDS.items():
        if any(keyword in normalized_message for keyword in keywords):
            found.append(interest)
    return found


def _extract_mobility_mode(normalized_message: str) -> str | None:
    for mode, keywords in MOBILITY_KEYWORDS.items():
        if any(keyword in normalized_message for keyword in keywords):
            return mode
    return None


def _extract_available_time_minutes(message: str) -> int | None:
    text = message.strip().lower()

    for pattern, kind in TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if kind == "hours_minutes":
            hours = int(match.group(1))
            minutes = int(match.group(2))
            return hours * 60 + minutes
        if kind == "hours":
            return int(match.group(1)) * 60
        if kind == "minutes":
            return int(match.group(1))
        if kind == "decimal_hours":
            hours = float(match.group(1).replace(",", "."))
            return int(hours * 60)

    return None


def _merge_interests(existing: list[str], new_items: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *new_items]:
        cleaned = str(item).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged


def _merge_monuments(existing: list[str], new_items: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *new_items]:
        cleaned = str(item).strip()
        if not cleaned:
            continue
        key = normalize_text(cleaned)
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged[-MAX_MONUMENTS:]
