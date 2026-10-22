"""
wizard_state_machine.py

State machine Redis pour piloter le wizard conversationnel de génération
de circuit dans Dourbia (Phase 1 du plan circuit-builder intégré).

Principe : chaque état a un handler déterministe qui traite un payload
structuré (clic sur card/bouton) SANS appel LLM. Le LLM n'intervient
que pour :
  - détecter l'intention initiale (entrée dans le wizard depuis IDLE)
  - interpréter une déviation en texte libre pendant le wizard

Ce fichier ne fait AUCUN appel LLM ni HTTP lui-même : il expose des
fonctions pures + une interface Redis, à brancher depuis orchestrateur.py.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from dataclasses import dataclass, field, asdict
from datetime import timezone
from enum import Enum
from typing import Any, Optional

import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------


class WizardState(str, Enum):
    IDLE = "IDLE"
    PLACE_SELECTION = "PLACE_SELECTION"
    CUSTOMIZATION_BUDGET = "CUSTOMIZATION_BUDGET"
    CUSTOMIZATION_MOBILITY = "CUSTOMIZATION_MOBILITY"
    CUSTOMIZATION_TIME = "CUSTOMIZATION_TIME"
    CUSTOMIZATION_PREFERENCES = "CUSTOMIZATION_PREFERENCES"
    CIRCUIT_GENERATION = "CIRCUIT_GENERATION"  # état transitoire, pas d'input user
    CIRCUIT_REVIEW = "CIRCUIT_REVIEW"
    CIRCUIT_ADJUSTMENT = "CIRCUIT_ADJUSTMENT"
    GUIDE_MODE_READY = "GUIDE_MODE_READY"


# Ordre "nominal" du wizard, utilisé pour savoir quel est l'état suivant
# par défaut quand un handler ne redirige pas ailleurs explicitement.
NOMINAL_ORDER: list[WizardState] = [
    WizardState.CUSTOMIZATION_BUDGET,
    WizardState.CUSTOMIZATION_MOBILITY,
    WizardState.CUSTOMIZATION_TIME,
    WizardState.CUSTOMIZATION_PREFERENCES,
    WizardState.PLACE_SELECTION,
    WizardState.CIRCUIT_GENERATION,
    WizardState.CIRCUIT_REVIEW,
]


# ---------------------------------------------------------------------------
# Modèle de données de session wizard
# ---------------------------------------------------------------------------


@dataclass
class WizardSession:
    session_id: str
    state: WizardState = WizardState.IDLE
    must_visit: list[str] = field(default_factory=list)  # ids monuments
    budget: Optional[dict[str, Any]] = (
        None  # {"type": "resident"|"etranger", "amount": float}
    )
    mobility: Optional[str] = None  # transport: "walking" | "bike" | "car" | ...
    mobilite: Optional[str] = None  # niveau: "normale" | "reduite" | "limitee"
    epoques: list[str] = field(default_factory=list)
    fonctions: list[str] = field(default_factory=list)
    time_constraints: Optional[dict[str, Any]] = (
        None  # {"duration_minutes": 120, "start_time": "09:00", "end_time": "11:00"}
    )
    places_offset: int = 0
    circuit_result: Optional[dict[str, Any]] = (
        None  # réponse brute de /api/circuits/recommend
    )
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        d = asdict(self)
        d["state"] = self.state.value
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def from_json(raw: str) -> "WizardSession":
        d = json.loads(raw)
        legacy_state = d.pop("state")
        d.pop("city", None)
        legacy_dates = d.pop("dates", None)
        if "time_constraints" not in d:
            time_constraints = (
                {
                    key: value
                    for key, value in legacy_dates.items()
                    if key in {"duration_minutes", "start_time", "end_time"}
                }
                if isinstance(legacy_dates, dict)
                else {}
            )
            if "duration_minutes" not in time_constraints and isinstance(legacy_dates, dict):
                legacy_hours = legacy_dates.get("duration_hours")
                if legacy_hours is not None:
                    try:
                        time_constraints["duration_minutes"] = int(float(legacy_hours) * 60)
                    except (TypeError, ValueError):
                        pass
            d["time_constraints"] = time_constraints or None

        if legacy_state == "CITY_SELECTION":
            legacy_state = WizardState.CUSTOMIZATION_BUDGET.value
        elif legacy_state == "CUSTOMIZATION_DATES":
            legacy_state = WizardState.CUSTOMIZATION_TIME.value
        elif legacy_state == "PLACE_SELECTION" and not d.get("budget"):
            legacy_state = WizardState.CUSTOMIZATION_BUDGET.value
        elif legacy_state == "CUSTOMIZATION_PREFERENCES" and not d.get("time_constraints"):
            legacy_state = WizardState.CUSTOMIZATION_TIME.value
        d["state"] = WizardState(legacy_state)
        return WizardSession(**d)


# ---------------------------------------------------------------------------
# Accès Redis
# ---------------------------------------------------------------------------

REDIS_KEY_PREFIX = "wizard:"
DEFAULT_TTL_SECONDS = 3600  # à aligner avec le TTL de session_memory.py existant


class WizardStore:
    """Wrapper Redis dédié au wizard. Volontairement séparé de
    session_memory.py pour ne pas coupler le state du wizard à la mémoire
    conversationnelle générale — mais utilise la même instance Redis.
    """

    def __init__(
        self, redis_client: aioredis.Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{REDIS_KEY_PREFIX}{session_id}"

    async def get(self, session_id: str) -> Optional[WizardSession]:
        raw = await self._redis.get(self._key(session_id))
        if raw is None:
            return None
        return WizardSession.from_json(raw)

    async def save(self, wizard: WizardSession) -> None:
        wizard.last_updated = datetime.now(timezone.utc).isoformat()
        await self._redis.set(
            self._key(wizard.session_id), wizard.to_json(), ex=self._ttl
        )

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(self._key(session_id))

    async def get_or_create(self, session_id: str) -> WizardSession:
        wizard = await self.get(session_id)
        if wizard is None:
            wizard = WizardSession(session_id=session_id)
            await self.save(wizard)
        return wizard


# ---------------------------------------------------------------------------
# Événements (actions envoyées par le frontend depuis les rich cards)
# ---------------------------------------------------------------------------


@dataclass
class WizardEvent:
    type: str  # ex: "select_places", "set_budget", "set_mobility", "set_time", ...
    value: Any = None


# ---------------------------------------------------------------------------
# Handlers par état — PURS, testables sans Redis ni LLM
# ---------------------------------------------------------------------------
#
# Chaque handler reçoit la WizardSession courante + l'événement, et retourne
# la WizardSession mise à jour. La transition d'état est explicite dans
# chaque handler (pas de magie implicite), pour rester lisible et facile à
# tester unitairement.
class WizardValidationError(ValueError):
    """Valeur invalide reçue dans un événement du wizard.

    Hérite de ValueError : l'orchestrateur la traite déjà (log + rappel de la
    question courante), sans changer l'état du wizard.
    """

def handle_place_selection(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "select_places":
        raise ValueError(f"Événement inattendu en PLACE_SELECTION: {event.type}")
    value = event.value or []
    if not isinstance(value, (list, tuple)) or len(value) > 50:
        raise WizardValidationError("Liste de lieux invalide")
    wizard.must_visit = list(value)
    wizard.state = WizardState.CIRCUIT_GENERATION
    return wizard


def handle_load_more_places(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "load_more_places":
        raise ValueError(f"Événement inattendu en PLACE_SELECTION: {event.type}")
    wizard.places_offset += 1
    wizard.state = WizardState.PLACE_SELECTION
    return wizard


def handle_budget(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "set_budget":
        raise ValueError(f"Événement inattendu en CUSTOMIZATION_BUDGET: {event.type}")
    value = event.value
    if not isinstance(value, dict):
        raise WizardValidationError("Budget invalide")
    tariff_type = value.get("type")
    if not isinstance(tariff_type, str) or tariff_type not in {
        "resident", "etudiant", "etranger", "enseignant", "retraite", "enfant"
    }:
        raise WizardValidationError("Profil tarifaire manquant ou invalide")
    raw_amount = value.get("amount")
    if raw_amount is None or isinstance(raw_amount, bool):
        raise WizardValidationError("Montant du budget manquant")
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        raise WizardValidationError("Montant du budget invalide") from None
    if not math.isfinite(amount) or amount < 0:
        raise WizardValidationError("Montant du budget invalide")
    wizard.budget = {**value, "amount": amount}  # {"type": ..., "amount": ...}
    wizard.state = WizardState.CUSTOMIZATION_MOBILITY
    return wizard


def handle_mobility(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "set_mobility":
        raise ValueError(f"Événement inattendu en CUSTOMIZATION_MOBILITY: {event.type}")
    if not isinstance(event.value, dict):
        raise WizardValidationError("Transport et mobilité requis")

    transport = event.value.get("transport")
    mobilite = event.value.get("mobilite")
    transports_valides = {
        "walking", "bike", "car", "public_transport", "pied", "velo", "voiture"
    }
    mobilites_valides = {
        "normale", "reduite", "limitee", "full", "reduced", "limited"
    }
    if not isinstance(transport, str) or transport.strip() not in transports_valides:
        raise WizardValidationError(f"Transport invalide: {transport!r}")
    if not isinstance(mobilite, str) or mobilite.strip() not in mobilites_valides:
        raise WizardValidationError(f"Mobilité invalide: {mobilite!r}")

    wizard.mobility = transport.strip()
    wizard.mobilite = mobilite.strip()
    wizard.state = WizardState.CUSTOMIZATION_TIME
    return wizard


def handle_preferences(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "set_preferences":
        raise ValueError(f"Événement inattendu en CUSTOMIZATION_PREFERENCES: {event.type}")
    wizard.epoques = event.value.get("epoques", []) if isinstance(event.value, dict) else []
    wizard.fonctions = event.value.get("fonctions", []) if isinstance(event.value, dict) else []
    wizard.state = WizardState.PLACE_SELECTION
    return wizard


def handle_time(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "set_time":
        raise ValueError(f"Événement inattendu en CUSTOMIZATION_TIME: {event.type}")
    value = event.value
    if not isinstance(value, dict):
        raise WizardValidationError("Durée et horaires invalides")
    raw_duration = value.get("duration_minutes")
    if raw_duration is None or isinstance(raw_duration, bool):
        raise WizardValidationError("Durée manquante")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        raise WizardValidationError("Durée invalide") from None
    if not math.isfinite(duration) or not 15 <= duration <= 720 or not duration.is_integer():
        raise WizardValidationError("Durée invalide")

    start_time = value.get("start_time")
    end_time = value.get("end_time")
    if not isinstance(start_time, str) or not isinstance(end_time, str):
        raise WizardValidationError("Horaires manquants")
    try:
        start = datetime.strptime(start_time, "%H:%M")
        end = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        raise WizardValidationError("Horaires invalides") from None
    if start >= end:
        raise WizardValidationError("L'heure de fin doit suivre l'heure de début")

    wizard.time_constraints = {
        "duration_minutes": int(duration),
        "start_time": start_time,
        "end_time": end_time,
    }
    wizard.state = WizardState.CUSTOMIZATION_PREFERENCES
    return wizard


def handle_circuit_review(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type == "confirm_circuit":
        wizard.state = WizardState.GUIDE_MODE_READY
    elif event.type == "adjust_circuit":
        # event.value indique quel champ ajuster: "budget" | "mobility" | "time" | "preferences" | "places"
        wizard.state = WizardState.CIRCUIT_ADJUSTMENT
    elif event.type == "regenerate_circuit":
        wizard.state = WizardState.CIRCUIT_GENERATION
    else:
        raise ValueError(f"Événement inattendu en CIRCUIT_REVIEW: {event.type}")
    return wizard


def handle_circuit_adjustment(
    wizard: WizardSession, event: WizardEvent
) -> WizardSession:
    # Redirige vers l'état de customization concerné, event.value = champ ciblé
    field_to_state = {
        "places": WizardState.PLACE_SELECTION,
        "budget": WizardState.CUSTOMIZATION_BUDGET,
        "mobility": WizardState.CUSTOMIZATION_MOBILITY,
        "preferences": WizardState.CUSTOMIZATION_PREFERENCES,
        "time": WizardState.CUSTOMIZATION_TIME,
    }
    target = field_to_state.get(event.value)
    if target is None:
        raise ValueError(f"Champ d'ajustement inconnu: {event.value}")
    wizard.state = target
    return wizard


def handle_guide_mode_ready(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    if event.type != "confirm_guide_mode":
        raise ValueError(f"Événement inattendu en GUIDE_MODE_READY: {event.type}")
    # Oui ou non, le wizard se termine ici — l'activation réelle du flag
    # mode_guide_actif est gérée par orchestrateur.py selon event.value.
    wizard.state = WizardState.IDLE
    return wizard


HANDLERS = {
    WizardState.PLACE_SELECTION: handle_place_selection,
    
    WizardState.CUSTOMIZATION_BUDGET: handle_budget,
    WizardState.CUSTOMIZATION_MOBILITY: handle_mobility,
    WizardState.CUSTOMIZATION_PREFERENCES: handle_preferences,
    WizardState.CUSTOMIZATION_TIME: handle_time,
    WizardState.CIRCUIT_REVIEW: handle_circuit_review,
    WizardState.CIRCUIT_ADJUSTMENT: handle_circuit_adjustment,
    WizardState.GUIDE_MODE_READY: handle_guide_mode_ready,
}

# Le handler de pagination est branché directement dans apply_event() pour
# conserver un seul point d'entrée de transition sur PLACE_SELECTION.


def apply_event(wizard: WizardSession, event: WizardEvent) -> WizardSession:
    """Point d'entrée unique pour appliquer un événement structuré à une
    WizardSession. Ne fait PAS d'appel Redis ni LLM — orchestrateur.py est
    responsable de charger/sauvegarder via WizardStore et de brancher
    CIRCUIT_GENERATION sur l'appel réel à /api/circuits/recommend.
    """
    if wizard.state == WizardState.IDLE:
        raise ValueError(
            "apply_event appelé en IDLE : l'entrée dans le wizard doit passer "
            "par la détection d'intention LLM, pas par apply_event."
        )
    if wizard.state == WizardState.PLACE_SELECTION and event.type == "load_more_places":
        return handle_load_more_places(wizard, event)
    handler = HANDLERS.get(wizard.state)
    if handler is None:
        raise ValueError(f"Aucun handler pour l'état {wizard.state}")
    return handler(wizard, event)


def start_wizard(session_id: str) -> WizardSession:
    """Appelé depuis orchestrateur.py une fois que le LLM a détecté
    l'intention "je veux un circuit" depuis IDLE. Le wizard commence par
    l'étape profil; la zone reste fixée à Carthage à la génération.
    """
    return WizardSession(session_id=session_id, state=WizardState.CUSTOMIZATION_BUDGET)


def reset_wizard(session_id: str) -> WizardSession:
    return WizardSession(session_id=session_id, state=WizardState.IDLE)


# ---------------------------------------------------------------------------
# Textes déterministes par état (SANS LLM)
# ---------------------------------------------------------------------------
#
# MVP : français uniquement. Structure prête pour EN/AR plus tard, sur le
# modèle de FALLBACK_MESSAGES dans constants.py.

_QUESTIONS_FR: dict[WizardState, str] = {
    WizardState.PLACE_SELECTION: "Quels lieux voulez-vous absolument visiter ?",
    WizardState.CUSTOMIZATION_BUDGET: "Quel est votre budget ?",
    WizardState.CUSTOMIZATION_MOBILITY: "Comment souhaitez-vous vous déplacer ?",
    WizardState.CUSTOMIZATION_TIME: "Quelle durée et quel créneau horaire souhaitez-vous ?",
    WizardState.CUSTOMIZATION_PREFERENCES: "Quelles époques et types de sites vous intéressent ?",
    WizardState.CIRCUIT_GENERATION: "Je génère votre circuit, un instant...",
    WizardState.CIRCUIT_REVIEW: "Voici votre circuit proposé.",
    WizardState.CIRCUIT_ADJUSTMENT: "Que souhaitez-vous ajuster ?",
    WizardState.GUIDE_MODE_READY: "Votre circuit est prêt ! Souhaitez-vous activer le mode Guide GPS ?",
}


def question_for_state(state: WizardState, lang: str = "FR") -> str:
    """Retourne le texte déterministe associé à un état du wizard.
    Pas d'appel LLM ici — TODO EN/AR quand le besoin se présente."""
    return _QUESTIONS_FR.get(state, "...")


def question_for_budget_category(lang: str = "FR") -> str:
    """Demande la catégorie tarifaire manquante pour le budget."""
    return (
        "Quel type de tarif s'applique à vous : résident, étudiant, étranger, "
        "enseignant, retraité ou enfant ?"
    )
