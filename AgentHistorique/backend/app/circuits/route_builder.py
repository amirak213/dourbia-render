from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.circuits.constraints import ConstraintContext, check_constraints_status
from app.circuits.data_loader import MonumentNode
from app.circuits.dijkstra import DijkstraRouter, PathResult
from app.circuits.map_payload import build_map_route_payload
from app.circuits.scoring import preference_reason


@dataclass
class BuiltRoute:
    monuments: list[dict]
    segments: list[dict]
    polyline: list[list[float]]
    total_visit_duration_min: float
    total_travel_duration_min: float
    total_duration_min: float
    total_distance_km: float
    total_price: float
    unknown_price_count: int
    score: float
    constraints: dict[str, bool]
    explanation: list[str]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _format_time(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%H:%M")


def build_route(
    chromosome: list[str],
    *,
    candidates: dict[str, MonumentNode],
    router: DijkstraRouter,
    context: ConstraintContext,
    fitness_score: float,
    preferred_periods: list[str],
    preferred_functions: list[str],
    transport: str,
    start_time: str | None,
    zone: str,
) -> BuiltRoute:
    monuments: list[dict] = []
    segments: list[dict] = []
    current_time = _parse_time(start_time)

    total_visit = 0.0
    total_travel = 0.0
    total_distance = 0.0
    total_price = 0.0
    unknown_price_count = 0

    for order, monument_id in enumerate(chromosome, start=1):
        node = candidates[monument_id]
        arrival_time = _format_time(current_time)
        departure_dt = None
        if current_time is not None:
            departure_dt = current_time + timedelta(minutes=node.visit_duration_min)
        departure_time = _format_time(departure_dt)

        monuments.append(
            {
                "order": order,
                "monument_id": monument_id,
                "name": node.name,
                "latitude": node.latitude,
                "longitude": node.longitude,
                "visit_duration_min": node.visit_duration_min,
                "price": node.price,
                "arrival_time": arrival_time,
                "departure_time": departure_time,
                "reason": preference_reason(node, preferred_periods, preferred_functions),
            }
        )
        total_visit += node.visit_duration_min
        if node.price is None:
            unknown_price_count += 1
        else:
            total_price += node.price
        current_time = departure_dt

    for i in range(len(chromosome) - 1):
        from_id = chromosome[i]
        to_id = chromosome[i + 1]
        from_node = candidates[from_id]
        to_node = candidates[to_id]
        path_result: PathResult | None = router.shortest_path(from_id, to_id)
        if path_result is None:
            continue

        path_coords = [
            [candidates[mid].latitude, candidates[mid].longitude]
            for mid in path_result.path
            if mid in candidates
        ]
        if len(path_coords) < 2:
            path_coords = [
                [from_node.latitude, from_node.longitude],
                [to_node.latitude, to_node.longitude],
            ]

        segments.append(
            {
                "from": from_node.name,
                "to": to_node.name,
                "distance_km": round(path_result.distance_km, 2),
                "duration_min": round(path_result.duration_min, 1),
                "path": path_coords,
            }
        )
        total_travel += path_result.duration_min
        total_distance += path_result.distance_km
        if current_time is not None:
            current_time += timedelta(minutes=path_result.duration_min)

    total_duration = total_visit + total_travel
    constraints = check_constraints_status(
        total_cost=total_price,
        total_duration=total_duration,
        context=context,
        candidates=candidates,
        chromosome=chromosome,
    )
    explanation = _build_explanations(constraints, zone=zone)

    map_payload = build_map_route_payload(monuments, segments)
    return BuiltRoute(
        monuments=monuments,
        segments=segments,
        polyline=map_payload["polyline"],
        total_visit_duration_min=round(total_visit, 1),
        total_travel_duration_min=round(total_travel, 1),
        total_duration_min=round(total_duration, 1),
        total_distance_km=round(total_distance, 2),
        total_price=round(total_price, 2),
        unknown_price_count=unknown_price_count,
        score=round(max(0.0, min(1.0, fitness_score)), 2),
        constraints=constraints,
        explanation=explanation,
    )


def _build_explanations(constraints: dict[str, bool], *, zone: str) -> list[str]:
    messages: list[str] = []
    if constraints.get("budget_ok"):
        messages.append("Le circuit respecte le budget maximal.")
    else:
        messages.append("Le circuit dépasse légèrement le budget maximal.")
    if constraints.get("duration_ok"):
        messages.append("La durée totale est inférieure à la durée disponible.")
    else:
        messages.append("La durée totale dépasse la fenêtre disponible.")
    if constraints.get("mobility_ok"):
        messages.append("Les monuments sélectionnés sont compatibles avec votre niveau de mobilité.")
    else:
        messages.append("Certains monuments peuvent être difficiles d'accès avec votre mobilité.")
    messages.append(f"Circuit optimisé pour la zone {zone}.")
    return messages
