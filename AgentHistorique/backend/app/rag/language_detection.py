from __future__ import annotations

import re
from typing import Any

from app.memory.preference_extractor import _extract_language
from app.rag.text_utils import normalize_text

SUPPORTED_LANGUAGES = frozenset({"fr", "en", "ar"})

ARABIC_SCRIPT_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)

ENGLISH_MARKERS = frozenset(
    {
        "the",
        "what",
        "where",
        "when",
        "how",
        "why",
        "who",
        "whom",
        "whose",
        "about",
        "tell",
        "explain",
        "can",
        "you",
        "me",
        "is",
        "are",
        "was",
        "were",
        "history",
        "visit",
        "monument",
        "museum",
        "hours",
        "opening",
        "carthage",
        "tunisia",
        "roman",
        "punic",
        "search",
        "please",
        "show",
    }
)

FRENCH_MARKERS = frozenset(
    {
        "le",
        "la",
        "les",
        "des",
        "une",
        "un",
        "est",
        "sur",
        "pour",
        "comment",
        "quoi",
        "quel",
        "quelle",
        "ou",
        "où",
        "moi",
        "vous",
        "parler",
        "parlez",
        "explique",
        "expliquez",
        "visite",
        "visiter",
        "monument",
        "monuments",
        "musee",
        "horaires",
        "carthage",
        "tunisie",
        "romain",
        "romaine",
        "punique",
        "recherche",
        "merci",
        "bonjour",
    }
)

LANGUAGE_LABELS = {
    "fr": "français",
    "en": "English",
    "ar": "العربية",
}


def normalize_supported_language(language: str | None) -> str:
    cleaned = (language or "").strip().lower()
    if not cleaned or cleaned == "auto":
        return "fr"
    if cleaned.startswith("ar"):
        return "ar"
    if cleaned.startswith("en"):
        return "en"
    if cleaned.startswith("fr"):
        return "fr"
    return "fr"


def _language_tokens(message: str) -> set[str]:
    normalized = normalize_text(message)
    normalized = re.sub(r"(?<=\w)'s\b", "", normalized)
    normalized = re.sub(r"(?<=\w)'re\b", "", normalized)
    normalized = re.sub(r"(?<=\w)'ve\b", "", normalized)
    normalized = re.sub(r"(?<=\w)'ll\b", "", normalized)
    normalized = re.sub(r"(?<=\w)'d\b", "", normalized)
    normalized = re.sub(r"(?<=\w)'m\b", "", normalized)
    return {token for token in normalized.split() if token}


def detect_message_language(message: str) -> str | None:
    """Infer fr/en/ar from the current user message."""
    if not message.strip():
        return None

    if ARABIC_SCRIPT_RE.search(message):
        return "ar"

    tokens = _language_tokens(message)
    if not tokens:
        return None

    english_score = len(tokens & ENGLISH_MARKERS)
    french_score = len(tokens & FRENCH_MARKERS)

    if english_score > french_score and english_score >= 2:
        return "en"
    if french_score > english_score and french_score >= 2:
        return "fr"
    if english_score >= 1 and french_score == 0:
        return "en"
    if french_score >= 1 and english_score == 0:
        return "fr"

    # Short Latin questions like "who's baal hammon?"
    if english_score >= 1 and "who" in tokens:
        return "en"
    return None


def resolve_answer_language(
    message: str,
    *,
    request_language: str = "fr",
    memory_context: dict[str, Any] | None = None,
) -> str:
    """Pick the response language from explicit hints, message content, then session."""
    explicit = _extract_language(normalize_text(message))
    if explicit:
        return normalize_supported_language(explicit)

    detected = detect_message_language(message)
    if detected:
        return detected

    cleaned_request = normalize_supported_language(request_language)
    if request_language.strip().lower() not in {"", "auto"}:
        return cleaned_request

    context = memory_context or {}
    memory_language = context.get("preferred_language")
    if memory_language:
        return normalize_supported_language(str(memory_language))

    return "fr"


def get_language_instruction(answer_language: str) -> str:
    normalized = normalize_supported_language(answer_language)
    label = LANGUAGE_LABELS[normalized]
    if normalized == "ar":
        return (
            f"- يجب أن تكون إجابتك بالكامل باللغة {label}، حتى لو كانت المصادر بالفرنسية."
            f"\n- Answer entirely in {label} ({normalized}), even if sources are in French."
        )
    if normalized == "en":
        return (
            f"- You MUST answer entirely in {label}, even if the retrieved sources are in French."
            "\n- Translate or summarize faithfully; do not switch to French in the answer."
        )
    return (
        f"- Tu DOIS répondre entièrement en {label}, même si les sources récupérées sont en français."
    )
