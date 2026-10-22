from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CircuitPreferences(BaseModel):
    epoques: list[str]
    fonctions: list[str]
    must_visit: list[str]
    avoid: list[str]


class CircuitRecommendationRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    age: int | None = Field(None, ge=0, le=120)
    type_tarif: Literal[
        "resident",
        "etudiant",
        "etranger",
        "enseignant",
        "retraite",
        "enfant",
    ]
    budget_max: float = Field(..., gt=0)
    transport: Literal["walking", "bike", "car", "public_transport", "pied", "velo", "voiture"]
    mobilite: Literal["normale", "reduite", "limitee", "full", "reduced", "limited"]
    duration_minutes: int | None = Field(None, ge=15, le=720)
    start_time: str | None = None
    end_time: str | None = None
    zone: str
    preferences: CircuitPreferences
    start_location: str | None = None
    end_location: str | None = None
    max_stops: int = Field(12, ge=2, le=20)

    @field_validator("session_id")
    @classmethod
    def strip_session_id(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_duration_window(self) -> CircuitRecommendationRequest:
        if self.duration_minutes is None and not (self.start_time and self.end_time):
            raise ValueError(
                "Fournissez duration_minutes ou bien start_time et end_time."
            )
        return self


class RecommendedMonument(BaseModel):
    order: int
    monument_id: float | None = None
    name: str
    latitude: float
    longitude: float
    visit_duration_min: float
    price: float | None
    arrival_time: str | None = None
    departure_time: str | None = None
    reason: str


class CircuitSummary(BaseModel):
    title: str
    summary: str
    monuments: list[RecommendedMonument]
    total_visit_duration_min: float
    total_travel_duration_min: float
    total_duration_min: float
    total_distance_km: float
    total_price: float
    unknown_price_count: int = 0
    budget_max: float | None = None
    score: float


class RouteSegment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, ser_json_by_alias=True)

    from_name: str = Field(alias="from")
    to: str
    distance_km: float
    duration_min: float
    path: list[list[float]]


class MapRoutePayload(BaseModel):
    transport: str
    polyline: list[list[float]]
    segments: list[RouteSegment]


class CircuitConstraintsStatus(BaseModel):
    budget_ok: bool
    duration_ok: bool
    mobility_ok: bool


class CircuitRecommendationResponse(BaseModel):
    session_id: str
    circuit: CircuitSummary
    route: MapRoutePayload
    constraints: CircuitConstraintsStatus
    explanation: list[str]
    alternatives: list[CircuitSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    feasible: bool = True
