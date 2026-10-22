from __future__ import annotations

import math
import random
from dataclasses import dataclass

from app.circuits.constraints import ConstraintContext
from app.circuits.data_loader import MonumentNode
from app.circuits.dijkstra import DijkstraRouter


@dataclass
class GAConfig:
    population_size: int = 40
    generations: int = 50
    mutation_rate: float = 0.15
    crossover_rate: float = 0.8
    elitism: bool = True
    tournament_size: int = 3
    min_stops: int = 2
    max_stops: int = 12


@dataclass
class GAResult:
    chromosome: list[str]
    fitness: float
    feasible: bool


class GeneticOptimizer:
    def __init__(
        self,
        *,
        candidates: dict[str, MonumentNode],
        scores: dict[str, float],
        router: DijkstraRouter,
        context: ConstraintContext,
        config: GAConfig | None = None,
        seed: int | None = None,
        reference_chromosomes: list[list[str]] | None = None,
    ) -> None:
        self._candidates = candidates
        self._scores = scores
        self._router = router
        self._context = context
        self._config = config or GAConfig(max_stops=context.max_stops)
        self._rng = random.Random(seed)
        self._reference_chromosomes = reference_chromosomes or []
        self._candidate_ids = list(candidates.keys())

    def optimize(self) -> GAResult:
        if not self._candidate_ids:
            return GAResult(chromosome=[], fitness=-1e9, feasible=False)

        population = self._init_population()
        best = max(population, key=lambda item: item.fitness)

        elite_count = 2 if self._config.elitism else 0
        for _ in range(self._config.generations):
            population.sort(key=lambda item: item.fitness, reverse=True)
            if population[0].fitness > best.fitness:
                best = population[0]

            next_population = population[:elite_count]
            while len(next_population) < self._config.population_size:
                parent_a = self._tournament_select(population)
                parent_b = self._tournament_select(population)
                if self._rng.random() < self._config.crossover_rate:
                    child = self._crossover(parent_a.chromosome, parent_b.chromosome)
                else:
                    child = parent_a.chromosome[:]
                child = self._mutate(child)
                fitness, feasible = self._evaluate(child)
                next_population.append(GAResult(chromosome=child, fitness=fitness, feasible=feasible))
            population = next_population

        population.sort(key=lambda item: item.fitness, reverse=True)
        if population[0].fitness > best.fitness:
            best = population[0]
        return best

    def _init_population(self) -> list[GAResult]:
        population: list[GAResult] = []
        for ref in self._reference_chromosomes[: max(1, self._config.population_size // 4)]:
            chromosome = self._repair(ref)
            fitness, feasible = self._evaluate(chromosome)
            population.append(GAResult(chromosome=chromosome, fitness=fitness, feasible=feasible))

        while len(population) < self._config.population_size:
            if len(population) % 2 == 0:
                chromosome = self._greedy_chromosome()
            else:
                chromosome = self._random_chromosome()
            fitness, feasible = self._evaluate(chromosome)
            population.append(GAResult(chromosome=chromosome, fitness=fitness, feasible=feasible))
        return population

    def _greedy_chromosome(self) -> list[str]:
        required = list(self._context.required_ids)
        ranked = sorted(
            self._candidate_ids,
            key=lambda monument_id: self._scores.get(monument_id, 0),
            reverse=True,
        )
        size = self._rng.randint(
            max(self._config.min_stops, len(required)),
            min(self._config.max_stops, len(ranked)),
        )
        chromosome = required[:]
        for monument_id in ranked:
            if monument_id in chromosome:
                continue
            chromosome.append(monument_id)
            if len(chromosome) >= size:
                break
        return self._repair(chromosome)

    def _random_chromosome(self) -> list[str]:
        required = list(self._context.required_ids)
        pool = [mid for mid in self._candidate_ids if mid not in required]
        self._rng.shuffle(pool)
        size = self._rng.randint(
            max(self._config.min_stops, len(required)),
            min(self._config.max_stops, len(required) + len(pool)),
        )
        chromosome = required + pool[: max(0, size - len(required))]
        return self._repair(chromosome)

    def _tournament_select(self, population: list[GAResult]) -> GAResult:
        contenders = self._rng.sample(population, k=min(self._config.tournament_size, len(population)))
        return max(contenders, key=lambda item: item.fitness)

    def _crossover(self, parent_a: list[str], parent_b: list[str]) -> list[str]:
        if not parent_a or not parent_b:
            return self._repair(parent_a or parent_b)
        start = self._rng.randint(0, len(parent_a) - 1)
        end = self._rng.randint(start, len(parent_a) - 1)
        slice_ids = parent_a[start : end + 1]
        child: list[str] = []
        for monument_id in slice_ids:
            if monument_id not in child:
                child.append(monument_id)
        for monument_id in parent_b:
            if monument_id not in child:
                child.append(monument_id)
            if len(child) >= self._config.max_stops:
                break
        return self._repair(child)

    def _mutate(self, chromosome: list[str]) -> list[str]:
        mutated = chromosome[:]
        if self._rng.random() > self._config.mutation_rate:
            return self._repair(mutated)
        if len(mutated) >= 2 and self._rng.random() < 0.5:
            i, j = self._rng.sample(range(len(mutated)), 2)
            mutated[i], mutated[j] = mutated[j], mutated[i]
        else:
            pool = [mid for mid in self._candidate_ids if mid not in mutated]
            if pool and len(mutated) < self._config.max_stops and self._rng.random() < 0.5:
                mutated.insert(self._rng.randint(0, len(mutated)), self._rng.choice(pool))
            elif len(mutated) > max(self._config.min_stops, len(self._context.required_ids)):
                removable = [mid for mid in mutated if mid not in self._context.required_ids]
                if removable:
                    mutated.remove(self._rng.choice(removable))
        return self._repair(mutated)

    def _repair(self, chromosome: list[str]) -> list[str]:
        required = list(self._context.required_ids)
        repaired: list[str] = []
        for monument_id in required + chromosome:
            if monument_id in self._candidates and monument_id not in repaired:
                repaired.append(monument_id)
        if len(repaired) < self._config.min_stops:
            for monument_id in sorted(
                self._candidate_ids,
                key=lambda mid: self._scores.get(mid, 0),
                reverse=True,
            ):
                if monument_id not in repaired:
                    repaired.append(monument_id)
                if len(repaired) >= self._config.min_stops:
                    break
        return repaired[: self._config.max_stops]

    def _evaluate(self, chromosome: list[str]) -> tuple[float, bool]:
        if not chromosome:
            return -1e9, False

        penalty = 0.0
        if any(monument_id in self._context.excluded_ids for monument_id in chromosome):
            penalty += 1000.0
        if not self._context.required_ids.issubset(set(chromosome)):
            penalty += 1000.0

        visit_minutes = sum(self._candidates[mid].visit_duration_min for mid in chromosome)
        visit_cost = sum(
            price
            for mid in chromosome
            if (price := self._candidates[mid].price) is not None
        )
        travel_distance, travel_minutes, used_fallback = self._router.route_metrics(chromosome)
        if travel_minutes == math.inf:
            return -1e9, False

        total_minutes = visit_minutes + travel_minutes
        total_cost = visit_cost

        if total_cost > self._context.budget_max:
            penalty += (total_cost - self._context.budget_max) * 5.0
        if total_minutes > self._context.duration_minutes:
            penalty += (total_minutes - self._context.duration_minutes) * 3.0
        if used_fallback:
            penalty += 5.0

        preference_score = sum(self._scores.get(mid, 0) for mid in chromosome) / len(chromosome)
        priority_score = sum(self._candidates[mid].priority for mid in chromosome) / (
            5.0 * len(chromosome)
        )
        duration_score = 1.0 - min(1.0, total_minutes / max(self._context.duration_minutes, 1))
        budget_score = 1.0 - min(1.0, total_cost / max(self._context.budget_max, 1))
        travel_efficiency = 1.0 - min(1.0, travel_minutes / max(total_minutes, 1))
        constraint_score = 1.0 if penalty == 0 else 0.0

        fitness = (
            0.30 * preference_score
            + 0.20 * priority_score
            + 0.20 * duration_score
            + 0.15 * budget_score
            + 0.10 * travel_efficiency
            + 0.05 * constraint_score
            - penalty / 100.0
        )
        feasible = penalty == 0
        return fitness, feasible
