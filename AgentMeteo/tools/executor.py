"""
ToolExecutor — Exécution des plans avec gestion d'erreurs propre.
Les erreurs sont propagées au LLM, jamais silencieuses.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from core.planner import ExecutionPlan, PlanStep
from tools.registry import ToolRegistry
from observability.tracer import AgentTracer


class ToolExecutionError(Exception):
    """Erreur d'exécution d'un tool — propagée au LLM pour replanifier."""
    def __init__(self, tool_name: str, reason: str):
        self.tool_name = tool_name
        self.reason    = reason
        super().__init__(f"[{tool_name}] {reason}")


class ToolExecutor:
    """
    Exécute les steps d'un plan.
    - Respecte les dépendances (DAG)
    - Propage les erreurs explicitement
    - Trace chaque exécution
    """

    def __init__(self, registry: ToolRegistry, tracer: AgentTracer):
        self.registry = registry
        self.tracer   = tracer

    def execute_plan(
        self,
        plan:      ExecutionPlan,
        run_id:    str,
        max_steps: int = 8,
    ) -> list[dict]:
        """
        Exécute les steps dans l'ordre, en respectant les dépendances.
        Retourne une liste de résultats structurés.
        """
        results:     dict[int, dict] = {}  # step_id → result
        output_list: list[dict]      = []

        steps_to_run = plan.steps[:max_steps]

        for step in steps_to_run:
            # Vérifie les dépendances
            for dep_id in step.depends_on:
                if dep_id not in results:
                    # Dépendance non résolue — skip avec erreur
                    results[step.step_id] = {
                        "tool_name": step.tool_name,
                        "result":    {"error": f"Dépendance {dep_id} non résolue"},
                        "duration_ms": 0,
                    }
                    continue

            result = self._execute_step(step, run_id)
            results[step.step_id] = result
            output_list.append(result)

        return output_list

    async def execute_plan_with_deadline(
        self,
        plan: ExecutionPlan,
        run_id: str,
        max_steps: int = 8,
        deadline: float | None = None,
    ) -> list[dict]:
        """Execute steps asynchronously and enforce the run deadline per tool."""
        results: dict[int, dict] = {}
        output_list: list[dict] = []

        for step in plan.steps[:max_steps]:
            for dep_id in step.depends_on:
                if dep_id not in results:
                    results[step.step_id] = {
                        "tool_name": step.tool_name,
                        "result": {"error": f"Dépendance {dep_id} non résolue"},
                        "duration_ms": 0,
                    }
                    continue

            timeout = None
            if deadline is not None:
                timeout = max(0.0, deadline - time.time())

            try:
                if timeout is not None:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(self._execute_step, step, run_id),
                        timeout=timeout,
                    )
                else:
                    result = await asyncio.to_thread(
                        self._execute_step, step, run_id
                    )
            except asyncio.TimeoutError:
                result = {
                    "tool_name": step.tool_name,
                    "tool_args": step.tool_args,
                    "result": {
                        "error": "Deadline globale météo dépassée",
                        "error_type": "TimeoutError",
                    },
                    "duration_ms": 0,
                    "step_id": step.step_id,
                }

            results[step.step_id] = result
            output_list.append(result)

        return output_list

    def _execute_step(self, step: PlanStep, run_id: str) -> dict:
        """Exécute un step unique avec timing et tracing."""
        spec = self.registry.get(step.tool_name)

        if spec is None:
            return {
                "tool_name":   step.tool_name,
                "result":      {"error": f"Tool inconnu : {step.tool_name}"},
                "duration_ms": 0,
                "step_id":     step.step_id,
            }

        t0 = time.perf_counter()
        try:
            # Validation des args requis
            validated_args = _validate_args(step.tool_args, spec.parameters)

            # Exécution du handler
            raw_result = spec.handler(**validated_args)

            duration_ms = int((time.perf_counter() - t0) * 1000)

            return {
                "tool_name":   step.tool_name,
                "tool_args":   step.tool_args,
                "result":      raw_result,
                "duration_ms": duration_ms,
                "step_id":     step.step_id,
                "rationale":   step.rationale,
            }

        except Exception as e:
            duration_ms = int((time.perf_counter() - t0) * 1000)

            # L'erreur est structurée — le LLM peut raisonner dessus
            error_detail = {
                "error":       str(e),
                "error_type":  type(e).__name__,
                "tool_name":   step.tool_name,
                "tool_args":   step.tool_args,
                "recoverable": _is_recoverable(e),
            }

            return {
                "tool_name":   step.tool_name,
                "tool_args":   step.tool_args,
                "result":      error_detail,
                "duration_ms": duration_ms,
                "step_id":     step.step_id,
            }


# ──────────────────────────────────────────────────────────────
# UTILITAIRES
# ──────────────────────────────────────────────────────────────

def _validate_args(args: dict, schema: dict) -> dict:
    """
    Valide et complète les args avec les valeurs par défaut.
    Ne lève une erreur que si un required est manquant.
    """
    required = schema.get("required", [])
    props    = schema.get("properties", {})
    result   = {}

    for key, prop in props.items():
        if key in args and args[key] is not None:
            # Cast défensif selon le type
            val = args[key]
            if prop.get("type") == "integer":
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    val = prop.get("default", 3)
            elif prop.get("type") == "string" and str(val).lower() in ("null", "none", ""):
                val = None
            result[key] = val
        elif key in required:
            raise ValueError(f"Paramètre requis manquant : '{key}'")
        elif "default" in prop:
            result[key] = prop["default"]

    return result


def _is_recoverable(e: Exception) -> bool:
    """Détermine si l'erreur est récupérable par replanification."""
    recoverable_types = (TimeoutError, ConnectionError, ValueError)
    return isinstance(e, recoverable_types)