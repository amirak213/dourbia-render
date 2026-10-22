from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.circuits.constraints import ConstraintContext, filter_monuments
from app.circuits.data_loader import CircuitDataLoader
from app.circuits.dijkstra import DijkstraRouter
from app.circuits.genetic_optimizer import GAConfig, GeneticOptimizer
from app.circuits.route_builder import build_route
from app.circuits.scoring import score_monuments
from app.config import Settings, get_settings
from app.schemas.circuit_agent import (
    CircuitConstraintsStatus,
    CircuitRecommendationRequest,
    CircuitRecommendationResponse,
    CircuitSummary,
    MapRoutePayload,
    RecommendedMonument,
    RouteSegment,
)

logger = logging.getLogger(__name__)

TRANSPORT_NORMALIZE = {
    "pied": "walking",
    "walking": "walking",
    "velo": "bike",
    "bike": "bike",
    "voiture": "car",
    "car": "car",
    "public_transport": "public_transport",
    "transport": "public_transport",
}


@dataclass(frozen=True)
class CircuitAgentResult:
    response: CircuitRecommendationResponse


class CircuitAgentError(ValueError):
    """Raised when circuit recommendation cannot be produced."""


class CircuitAgent:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        data_loader: CircuitDataLoader | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._data_loader = data_loader or CircuitDataLoader(db)

    def recommend(self, request: CircuitRecommendationRequest) -> CircuitAgentResult:
        transport = TRANSPORT_NORMALIZE.get(request.transport, request.transport)
        duration_minutes = self._resolve_duration_minutes(request)

        nodes = self._data_loader.load_monuments(request.type_tarif)
        if not nodes:
            raise CircuitAgentError(
                "Aucun monument disponible. Importez les données CSV avec "
                "`python scripts/import_circuit_datasets.py`."
            )

        graph = self._data_loader.load_graph()
        router = DijkstraRouter(graph, nodes, transport=transport)

        required_ids, unknown_required = self._data_loader.resolve_monument_ids_by_names(
            request.preferences.must_visit,
            nodes,
        )
        excluded_ids, _ = self._data_loader.resolve_monument_ids_by_names(
            request.preferences.avoid,
            nodes,
        )
        if unknown_required:
            raise CircuitAgentError(
                f"Monuments requis introuvables: {', '.join(unknown_required)}"
            )

        context = ConstraintContext(
          budget_max=request.budget_max,
          duration_minutes=duration_minutes,
          mobilite=request.mobilite,
          required_ids=frozenset(required_ids),
          excluded_ids=frozenset(excluded_ids),
          max_stops=request.max_stops,
        )

        candidates, filter_warnings = filter_monuments(nodes, context)
        if not candidates:

            raise CircuitAgentError(
            "Aucun circuit réalisable avec ces contraintes."
          )

        if required_ids:

            candidates = {k: v for k, v in candidates.items() if k in required_ids}
        if not candidates:

            raise CircuitAgentError("Les monuments sélectionnés ne respectent pas les contraintes.")
        from dataclasses import replace
        context = replace(context, max_stops=len(candidates))

        scores = score_monuments(
            candidates,
            preferred_periods=request.preferences.epoques,
            preferred_functions=request.preferences.fonctions,
            budget_max=request.budget_max,
            mobilite=request.mobilite,
        )

        reference_chromosomes = self._build_reference_seeds(
            candidates,
            request.preferences.epoques,
            request.preferences.fonctions,
        )

        ga_config = GAConfig(
            population_size=self._settings.circuit_ga_population_size,
            generations=self._settings.circuit_ga_generations,
            mutation_rate=self._settings.circuit_ga_mutation_rate,
            crossover_rate=self._settings.circuit_ga_crossover_rate,
            elitism=self._settings.circuit_ga_elitism,
            max_stops=context.max_stops,
        )
        optimizer = GeneticOptimizer(
            candidates=candidates,
            scores=scores,
            router=router,
            context=context,
            config=ga_config,
            reference_chromosomes=reference_chromosomes,
        )
        ga_result = optimizer.optimize()

        if not ga_result.chromosome:
            raise CircuitAgentError(
                "Impossible de construire un circuit avec ces contraintes."
            )

        built = build_route(
            ga_result.chromosome,
            candidates=candidates,
            router=router,
            context=context,
            fitness_score=ga_result.fitness,
            preferred_periods=request.preferences.epoques,
            preferred_functions=request.preferences.fonctions,
            transport=transport,
            start_time=request.start_time,
            zone=request.zone,
        )

        summary = CircuitSummary(
            title=f"Circuit personnalisé à {request.zone}",
            summary=self._build_summary(built, request),
            monuments=[RecommendedMonument(**monument) for monument in built.monuments],
            total_visit_duration_min=built.total_visit_duration_min,
            total_travel_duration_min=built.total_travel_duration_min,
            total_duration_min=built.total_duration_min,
            total_distance_km=built.total_distance_km,
            total_price=built.total_price,
            unknown_price_count=built.unknown_price_count,
            budget_max=request.budget_max,
            score=built.score,
        )

        response = CircuitRecommendationResponse(
            session_id=request.session_id,
            circuit=summary,
            route=MapRoutePayload(
                transport=transport,
                polyline=built.polyline,
                segments=[RouteSegment.model_validate(segment) for segment in built.segments],
            ),
            constraints=CircuitConstraintsStatus(**built.constraints),
            explanation=built.explanation,
            alternatives=[],
            warnings=filter_warnings,
            feasible=ga_result.feasible and all(built.constraints.values()),
        )
        logger.info(
            "Circuit recommended session=%s stops=%s feasible=%s score=%s",
            request.session_id,
            len(ga_result.chromosome),
            response.feasible,
            built.score,
        )
        return CircuitAgentResult(response=response)

    def _resolve_duration_minutes(self, request: CircuitRecommendationRequest) -> int:
        if request.duration_minutes is not None:
            return request.duration_minutes
        start = self._parse_time(request.start_time)
        end = self._parse_time(request.end_time)
        if start is None or end is None:
            raise CircuitAgentError("Fenêtre horaire invalide.")
        delta = end - start
        if delta.total_seconds() <= 0:
            delta += timedelta(days=1)
        return max(15, int(delta.total_seconds() // 60))

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _build_reference_seeds(
        self,
        candidates: dict[str, Any],
        epoques: list[str],
        fonctions: list[str],
    ) -> list[list[str]]:
        refs = self._data_loader.load_reference_circuits()
        candidate_ids = set(candidates.keys())
        seeds: list[list[str]] = []
        for ref in refs:
            ids = [str(mid) for mid in ref.get("monument_ids", [])]
            filtered = [mid for mid in ids if mid in candidate_ids]
            if len(filtered) >= 2:
                seeds.append(filtered)
        seeds.sort(key=lambda _: 0)
        return seeds[:5]

    @staticmethod
    def _build_summary(built: Any, request: CircuitRecommendationRequest) -> str:
        return (
            f"{len(built.monuments)} monuments, "
            f"{built.total_duration_min:.0f} min au total "
            f"({built.total_travel_duration_min:.0f} min de trajet), "
            f"coût estimé {built.total_price:.0f} TND pour un budget maximal "
            f"de {request.budget_max:.0f} TND."
        )
