from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.circuits.data_loader import GraphEdge, MonumentNode, haversine_km

TRANSPORT_DURATION_ATTR = {
    "walking": "duration_walk_min",
    "pied": "duration_walk_min",
    "bike": "duration_bike_min",
    "velo": "duration_bike_min",
    "car": "duration_car_min",
    "voiture": "duration_car_min",
    "public_transport": "duration_car_min",
    "transport": "duration_car_min",
}


@dataclass(frozen=True)
class PathResult:
    path: list[str]
    distance_km: float
    duration_min: float
    used_fallback: bool = False


class DijkstraRouter:
    def __init__(
        self,
        graph: dict[str, dict[str, GraphEdge]],
        nodes: dict[str, MonumentNode],
        *,
        transport: str,
        walking_speed_kmh: float = 4.5,
        fallback_enabled: bool = True,
    ) -> None:
        self._graph = graph
        self._nodes = nodes
        self._transport = transport
        self._walking_speed_kmh = walking_speed_kmh
        self._fallback_enabled = fallback_enabled
        self._duration_attr = TRANSPORT_DURATION_ATTR.get(
            transport,
            "duration_walk_min",
        )

    def _edge_duration(self, edge: GraphEdge) -> float:
        duration = getattr(edge, self._duration_attr, 0.0)
        return duration if duration > 0 else edge.duration_walk_min

    def shortest_path(self, start_id: str, end_id: str) -> PathResult | None:
        if start_id == end_id:
            return PathResult(path=[start_id], distance_km=0.0, duration_min=0.0)

        if start_id not in self._nodes or end_id not in self._nodes:
            return None

        distances: dict[str, float] = {start_id: 0.0}
        previous: dict[str, str | None] = {start_id: None}
        heap: list[tuple[float, str]] = [(0.0, start_id)]
        visited: set[str] = set()

        while heap:
            current_dist, current_id = heapq.heappop(heap)
            if current_id in visited:
                continue
            visited.add(current_id)

            if current_id == end_id:
                break

            for neighbor_id, edge in self._graph.get(current_id, {}).items():
                weight = self._edge_duration(edge)
                if weight <= 0:
                    continue
                alt = current_dist + weight
                if alt < distances.get(neighbor_id, math.inf):
                    distances[neighbor_id] = alt
                    previous[neighbor_id] = current_id
                    heapq.heappush(heap, (alt, neighbor_id))

        if end_id not in distances:
            if self._fallback_enabled:
                return self._haversine_fallback(start_id, end_id)
            return None

        path = self._reconstruct_path(previous, start_id, end_id)
        total_distance = 0.0
        for i in range(len(path) - 1):
            edge = self._graph.get(path[i], {}).get(path[i + 1])
            if edge is not None:
                total_distance += edge.distance_km
            else:
                a, b = self._nodes[path[i]], self._nodes[path[i + 1]]
                total_distance += haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)

        return PathResult(
            path=path,
            distance_km=total_distance,
            duration_min=distances[end_id],
        )

    def _haversine_fallback(self, start_id: str, end_id: str) -> PathResult:
        start = self._nodes[start_id]
        end = self._nodes[end_id]
        distance_km = haversine_km(
            start.latitude,
            start.longitude,
            end.latitude,
            end.longitude,
        )
        if self._duration_attr == "duration_car_min":
            speed = 25.0
        elif self._duration_attr == "duration_bike_min":
            speed = 12.0
        else:
            speed = self._walking_speed_kmh
        duration_min = (distance_km / max(speed, 1e-6)) * 60.0
        return PathResult(
            path=[start_id, end_id],
            distance_km=distance_km,
            duration_min=duration_min,
            used_fallback=True,
        )

    @staticmethod
    def _reconstruct_path(
        previous: dict[str, str | None],
        start_id: str,
        end_id: str,
    ) -> list[str]:
        path: list[str] = []
        current: str | None = end_id
        while current is not None:
            path.append(current)
            current = previous.get(current)
        path.reverse()
        if path and path[0] == start_id:
            return path
        return [start_id, end_id]

    def route_metrics(self, monument_ids: list[str]) -> tuple[float, float, bool]:
        if len(monument_ids) < 2:
            return 0.0, 0.0, False

        total_distance = 0.0
        total_duration = 0.0
        used_fallback = False
        for i in range(len(monument_ids) - 1):
            result = self.shortest_path(monument_ids[i], monument_ids[i + 1])
            if result is None:
                return math.inf, math.inf, True
            total_distance += result.distance_km
            total_duration += result.duration_min
            used_fallback = used_fallback or result.used_fallback
        return total_distance, total_duration, used_fallback
