from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monument import Monument
from app.models.reference_circuit import ReferenceCircuit
from app.services.distance_service import build_distance_lookup

logger = logging.getLogger(__name__)

TARIFF_COLUMN_MAP: dict[str, str] = {
    "resident": "price_resident",
    "etudiant": "price_student",
    "etranger": "price_foreign",
    "enseignant": "price_teacher",
    "retraite": "price_senior",
    "enfant": "price_child",
}


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_monument_price(monument: Monument, tariff_type: str) -> float | None:
    column = TARIFF_COLUMN_MAP.get(tariff_type, "price_resident")
    value = getattr(monument, column, None)
    if value is None:
        return None
    return float(value)


@dataclass(frozen=True)
class MonumentNode:
    id: str
    name: str
    latitude: float
    longitude: float
    visit_duration_min: float
    priority: float
    price: float | None
    dominant_period: str | None
    secondary_period: str | None
    third_period: str | None
    function: str | None
    accessibility: str | None
    relief: str | None

    def __init__(
        self,
        *,
        id: str | int | float,
        name: str,
        latitude: float,
        longitude: float,
        visit_duration_min: float,
        priority: float | None = None,
        price: float | None,
        dominant_period: str | None = None,
        secondary_period: str | None = None,
        third_period: str | None = None,
        function: str | None = None,
        accessibility: str | None = None,
        relief: str | None = None,
        popularity: float | None = None,
    ) -> None:
        object.__setattr__(self, "id", str(id))
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "visit_duration_min", visit_duration_min)
        object.__setattr__(self, "priority", float(priority if priority is not None else popularity if popularity is not None else 3))
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "dominant_period", dominant_period)
        object.__setattr__(self, "secondary_period", secondary_period)
        object.__setattr__(self, "third_period", third_period)
        object.__setattr__(self, "function", function)
        object.__setattr__(self, "accessibility", accessibility)
        object.__setattr__(self, "relief", relief)

    @classmethod
    def from_orm(cls, monument: Monument, *, price: float | None) -> MonumentNode:
        return cls(
            id=monument.id_str,
            name=monument.name_fr,
            latitude=monument.latitude_float or 0.0,
            longitude=monument.longitude_float or 0.0,
            visit_duration_min=float(monument.visit_duration_minutes or 15),
            priority=float(monument.priority or 3),
            price=price,
            dominant_period=monument.dominant_period,
            secondary_period=monument.secondary_period,
            third_period=monument.third_period,
            function=monument.function,
            accessibility=monument.accessibility,
            relief=monument.relief,
        )


@dataclass
class GraphEdge:
    to_id: str
    distance_km: float
    duration_walk_min: float
    duration_bike_min: float
    duration_car_min: float


class CircuitDataLoader:
    def __init__(self, db: Session) -> None:
        self._db = db

    def load_monuments(self, tariff_type: str) -> dict[str, MonumentNode]:
        monuments = self._db.scalars(select(Monument)).all()
        nodes: dict[str, MonumentNode] = {}
        for monument in monuments:
            if monument.latitude_float is None or monument.longitude_float is None:
                continue
            price = get_monument_price(monument, tariff_type)
            if price is None:
                logger.warning(
                    "Monument has missing %s tariff: %s",
                    tariff_type,
                    monument.name_fr,
                )
            nodes[monument.id_str] = MonumentNode.from_orm(monument, price=price)
        return nodes

    def load_graph(self) -> dict[str, dict[str, GraphEdge]]:
        monuments = self._db.scalars(select(Monument)).all()
        monument_ids = [
            monument.id_str for monument in monuments if monument.id is not None
        ]
        lookup, unresolved = build_distance_lookup(self._db, monument_ids=monument_ids)

        graph: dict[str, dict[str, GraphEdge]] = {}
        for src_id, target_id in lookup:
            entry = lookup[(src_id, target_id)]
            graph.setdefault(src_id, {})[target_id] = GraphEdge(
                to_id=target_id,
                distance_km=float(entry.get("distance_km") or 0.0),
                duration_walk_min=float(entry.get("duration_walk_min") or 0.0),
                duration_bike_min=float(entry.get("duration_bike_min") or 0.0),
                duration_car_min=float(entry.get("duration_car_min") or 0.0),
            )

        if unresolved:
            print(f"[circuits] {len(unresolved)} distance pairs could not be resolved from the distance table")
        return graph

    def load_reference_circuits(self) -> list[dict[str, Any]]:
        refs = self._db.scalars(select(ReferenceCircuit)).all()
        return [
            {
                "external_id": ref.external_id,
                "monument_ids": ref.monument_ids or [],
                "monument_names": ref.monument_names,
                "score": float(ref.score or 0),
            }
            for ref in refs
        ]

    def resolve_monument_ids_by_names(
        self,
        names: list[str],
        nodes: dict[str, MonumentNode],
    ) -> tuple[list[str], list[str]]:
        name_index = {normalize_name(node.name): node.id for node in nodes.values()}
        resolved: list[str] = []
        unknown: list[str] = []
        for raw_name in names:
            normalized = normalize_name(raw_name)
            monument_id = name_index.get(normalized)
            if monument_id is None:
                for key, node_id in name_index.items():
                    if normalized in key or key in normalized:
                        monument_id = node_id
                        break
            if monument_id is None:
                unknown.append(raw_name)
            else:
                resolved.append(monument_id)
        return resolved, unknown


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))
