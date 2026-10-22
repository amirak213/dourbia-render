from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.rag.text_utils import normalize_text


class QueryIntentType(str, Enum):
    MONUMENT = "monument"
    CIRCUIT = "circuit"
    MIXED = "mixed"


@dataclass(frozen=True)
class QueryIntent:
    intent_type: QueryIntentType
    monument_score: int
    circuit_score: int

    @property
    def is_monument_like(self) -> bool:
        return self.intent_type == QueryIntentType.MONUMENT

    @property
    def is_circuit_like(self) -> bool:
        return self.intent_type == QueryIntentType.CIRCUIT


CIRCUIT_KEYWORDS = (
    "circuit",
    "parcours",
    "itineraire",
    "demi journee",
    "demi-journee",
    "velo",
    "vélo",
    "cyclable",
    "pedestre",
    "pédestre",
    "etapes",
    "étapes",
)

MONUMENT_KEYWORDS = (
    "monument",
    "monuments",
    "site",
    "sites",
    "basilique",
    "basiliques",
    "theatre",
    "théâtre",
    "amphitheatre",
    "amphithéâtre",
    "thermes",
    "tophet",
    "colline",
    "byrsa",
    "port",
    "ports",
    "odeon",
    "odéon",
    "necropole",
    "nécropole",
    "musee",
    "musée",
    "explique",
    "histoire",
    "historique",
    "qu est-ce que",
    "qu'est-ce que",
    "ou se trouve",
    "où se trouve",
    "decrit",
    "décris",
    "raconte",
    "accessibilite",
    "accessibilité",
    "accessible",
    "duree",
    "durée",
    "minutes",
    "tarif",
    "horaires",
)


def detect_query_intent(query: str) -> QueryIntent:
    normalized = normalize_text(query)

    circuit_score = sum(1 for keyword in CIRCUIT_KEYWORDS if normalize_text(keyword) in normalized)
    monument_score = sum(1 for keyword in MONUMENT_KEYWORDS if normalize_text(keyword) in normalized)

    if circuit_score > monument_score and circuit_score > 0:
        intent_type = QueryIntentType.CIRCUIT
    elif monument_score > circuit_score and monument_score > 0:
        intent_type = QueryIntentType.MONUMENT
    elif circuit_score > 0 and monument_score > 0 and circuit_score == monument_score:
        intent_type = QueryIntentType.MIXED
    else:
        intent_type = QueryIntentType.MIXED

    return QueryIntent(
        intent_type=intent_type,
        monument_score=monument_score,
        circuit_score=circuit_score,
    )


def source_type_score(source_type: str, intent: QueryIntent) -> float:
    if intent.intent_type == QueryIntentType.MIXED:
        return 0.5

    if intent.intent_type == QueryIntentType.MONUMENT:
        return 1.0 if source_type == "monument" else 0.0

    if intent.intent_type == QueryIntentType.CIRCUIT:
        return 1.0 if source_type == "circuit" else 0.0

    return 0.5
