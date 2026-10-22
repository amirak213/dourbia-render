from __future__ import annotations

COMPLEX_QUESTION_HINTS = (
    "en detail",
    "en détail",
    "detaille",
    "détaillé",
    "détaillée",
    "developpe",
    "développe",
    "histoire complete",
    "histoire complète",
    "compare",
    "comparer",
    "comparaison",
    "evolution",
    "évolution",
    "contexte historique",
    "en profondeur",
    "tout sur",
    "explique tout",
    "raconte l histoire",
    "raconte l'histoire",
    "chronologie",
    "pourquoi",
    "comment s est",
    "comment s'est",
)

DETAIL_REQUEST_HINTS = (
    "en detail",
    "en détail",
    "detaille",
    "détaillé",
    "détaillée",
    "developpe",
    "développe",
    "en profondeur",
    "histoire complete",
    "histoire complète",
    "explique tout",
    "tout savoir",
    "plus de details",
    "plus de détails",
)

MIN_COMPLEX_MESSAGE_LENGTH = 150


def is_complex_question(user_message: str) -> bool:
    """Return True when retrieval should use a wider top_k."""
    normalized = user_message.strip().lower()
    if not normalized:
        return False
    if len(normalized) >= MIN_COMPLEX_MESSAGE_LENGTH:
        return True
    return any(hint in normalized for hint in COMPLEX_QUESTION_HINTS)


def user_requests_detailed_answer(user_message: str) -> bool:
    """Return True when the user explicitly asks for a longer answer."""
    normalized = user_message.strip().lower()
    return any(hint in normalized for hint in DETAIL_REQUEST_HINTS)
