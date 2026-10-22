from __future__ import annotations

import re

from app.rag.suggested_action_intent import get_suggested_action_intent
from app.rag.text_utils import normalize_text

HORAIRES_TARIFS_EXPLICIT_HINTS = (
    "horaire",
    "horaires",
    "ouverture",
    "fermeture",
    "tarif",
    "tarifs",
    "prix",
    "cout",
    "coute",
    "billet",
    "ticket",
    "entree",
    "opening hour",
    "closing time",
    "admission fee",
    "entry fee",
    "opening hours",
    "awqat",  # arabic fragment after normalize
    "si3r",  # سعر normalized loosely
)

CIRCUIT_EXPLICIT_HINTS = (
    "circuit",
    "circuits",
    "itineraire",
    "parcours",
    "que visiter",
    "que voir",
    "visite en",
    "walking tour",
    "tour route",
    "masar",  # مسار
)

VISIT_PLANNING_HINTS = ("visiter", "visite", "faire", "voir")


def user_explicitly_requests_horaires_or_tarifs(user_message: str) -> bool:
    """True when the visitor explicitly asks about hours or prices."""
    if get_suggested_action_intent(user_message) == "show_hours":
        return True

    normalized = normalize_text(user_message)
    if not normalized:
        return False

    if any(hint in normalized for hint in HORAIRES_TARIFS_EXPLICIT_HINTS):
        return True

    if "combien" in normalized and any(
        hint in normalized for hint in ("tarif", "tarifs", "prix", "cout", "coute")
    ):
        return True

    return False


def user_explicitly_requests_circuits(user_message: str) -> bool:
    """True when the visitor explicitly asks about tourist circuits or visit routes."""
    intent = get_suggested_action_intent(user_message)
    if intent in {"circuit_detail", "roman_circuit", "time_adapted_visit"}:
        return True

    normalized = normalize_text(user_message)
    if not normalized:
        return False

    if any(hint in normalized for hint in CIRCUIT_EXPLICIT_HINTS):
        return True

    if "circuit" in normalized and "romain" in normalized:
        return True

    if "romain" in normalized and any(
        hint in normalized for hint in ("circuit", "parcours", "itineraire")
    ):
        return True

    has_duration = bool(
        re.search(r"\d+\s*(h|heure|heures|min|minute|minutes)", normalized)
    )
    if has_duration and any(hint in normalized for hint in VISIT_PLANNING_HINTS):
        return True

    return False
