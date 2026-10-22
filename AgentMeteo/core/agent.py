"""
WeatherAgent v4 — Vrai agent IA autonome 2026
Cycle : Observe → Plan → Act → Evaluate → Respond
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.planner import AgentPlanner, ExecutionPlan
from core.evaluator import ResponseEvaluator, EvalResult
from memory.context import ContextManager
from observability.tracer import AgentTracer, Span
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor

log = logging.getLogger("weather_agent")


class AgentStatus(Enum):
    IDLE       = "idle"
    PLANNING   = "planning"
    EXECUTING  = "executing"
    EVALUATING = "evaluating"
    DONE       = "done"
    FAILED     = "failed"


@dataclass
class AgentState:
    """État complet et immuable de l'agent à chaque step."""
    run_id:        str
    session_id:    str
    user_query:    str
    status:        AgentStatus          = AgentStatus.IDLE
    plan:          ExecutionPlan | None = None
    tool_results:  list[dict]           = field(default_factory=list)
    eval_result:   EvalResult | None    = None
    final_answer:  str                  = ""
    iterations:    int                  = 0
    token_budget:  int                  = 2000
    tokens_used:   int                  = 0
    error:         str | None           = None

    def to_dict(self) -> dict:
        return {
            "run_id":       self.run_id,
            "session_id":   self.session_id,
            "status":       self.status.value,
            "iterations":   self.iterations,
            "tokens_used":  self.tokens_used,
            "has_plan":     self.plan is not None,
            "tools_called": len(self.tool_results),
            "final_answer": self.final_answer[:100] if self.final_answer else "",
        }


class WeatherAgent:
    """
    Agent météo autonome avec cycle complet :
    1. PLAN    — décompose la question en steps
    2. ACT     — exécute les tools nécessaires
    3. EVALUATE — vérifie si la réponse est suffisante
    4. REPLAN  — si insuffisant, replanifie (max 3 cycles)
    """

    MAX_CYCLES        = 3      # cycles plan→act→eval max
    MAX_STEPS         = 8      # steps totaux par run
    TOKEN_BUDGET      = 3000   # tokens max par run
    RUN_TIMEOUT_SECS  = 25     # timeout global — évite de bloquer un thread Flask

    def __init__(
        self,
        llm_client_factory,      # callable(task_type?) → (client, model)
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        tracer: AgentTracer,
    ):
        self._get_llm      = llm_client_factory
        self.tools         = tool_registry
        self.context       = context_manager
        self.tracer        = tracer

        # Chaque module reçoit une factory spécialisée par TaskType
        # Avant ce fix, planner et evaluator utilisaient le modèle de synthèse lourd
        from core.model_router import TaskType
        self.planner   = AgentPlanner(lambda: llm_client_factory(TaskType.PLAN))
        self.evaluator = ResponseEvaluator(lambda: llm_client_factory(TaskType.EVALUATE))
        self.executor  = ToolExecutor(tool_registry, tracer)

    # ──────────────────────────────────────────────
    # ENTRY POINT
    # ──────────────────────────────────────────────

    def run(self, session_id: str, user_query: str) -> AgentState:
        """Point d'entrée principal — retourne un AgentState complet."""
        state = AgentState(
            run_id     = str(uuid.uuid4())[:8],
            session_id = session_id,
            user_query = user_query,
        )

        with self.tracer.run_span(state.run_id, session_id, user_query) as run_span:
            try:
                deadline = time.time() + self.RUN_TIMEOUT_SECS
                state = self._main_loop(state, run_span, deadline=deadline)
            except TimeoutError:
                state.status       = AgentStatus.FAILED
                state.error        = "timeout"
                state.final_answer = "⏱️ La requête a pris trop de temps. Réessaie dans quelques instants."
                run_span.error("timeout")
            except Exception as e:
                state.status = AgentStatus.FAILED
                state.error  = str(e)
                state.final_answer = f"⚠️ Erreur interne : {str(e)[:100]}"
                run_span.error(str(e))

        # Persiste dans la mémoire de session
        self.context.add_turn(
            session_id = session_id,
            role       = "assistant",
            content    = state.final_answer,
            metadata   = state.to_dict(),
        )

        return state

    # ──────────────────────────────────────────────
    # MAIN LOOP — Observe → Plan → Act → Evaluate
    # ──────────────────────────────────────────────

    def _main_loop(self, state: AgentState, run_span: Span, deadline: float = 0) -> AgentState:
        loop_started = time.perf_counter()
        log.info("main_loop.start run_id=%s", state.run_id)

        # ── OBSERVE : charge le contexte mémoire ──
        ctx = self.context.build_context(state.session_id, state.user_query)

        accumulated_tool_results: list[dict] = []
        cycles_done = 0

        while cycles_done < self.MAX_CYCLES:
            # ── TIMEOUT CHECK ──
            if deadline and time.time() > deadline:
                raise TimeoutError

            state.iterations += 1

            # ── PLAN ──
            state.status = AgentStatus.PLANNING
            with self.tracer.span("plan", state.run_id) as s:
                plan = self.planner.plan(
                    query          = state.user_query,
                    context        = ctx,
                    previous_tools = accumulated_tool_results,
                    available_tools= self.tools.describe_all(),
                )
                state.plan = plan
                s.set_meta({"steps": len(plan.steps), "intent": plan.intent})

            # Si le planner dit qu'aucun tool n'est nécessaire
            if not plan.steps:
                state = self._generate_final_answer(state, ctx, accumulated_tool_results)
                break

            # ── ACT : exécute les steps du plan ──
            state.status = AgentStatus.EXECUTING
            with self.tracer.span("act", state.run_id) as s:
                new_results = asyncio.run(self.executor.execute_plan_with_deadline(
                    plan      = plan,
                    run_id    = state.run_id,
                    max_steps = self.MAX_STEPS - len(accumulated_tool_results),
                    deadline  = deadline,
                ))
                accumulated_tool_results.extend(new_results)
                state.tool_results = accumulated_tool_results
                state.tokens_used += sum(r.get("tokens", 0) for r in new_results)
                s.set_meta({"tools_called": len(new_results)})

            # ── EVALUATE : est-ce que j'ai assez d'infos ? ──
            state.status = AgentStatus.EVALUATING
            with self.tracer.span("evaluate", state.run_id) as s:
                eval_result = self.evaluator.evaluate(
                    query        = state.user_query,
                    tool_results = accumulated_tool_results,
                    plan         = plan,
                )
                state.eval_result = eval_result
                s.set_meta({
                    "score":      eval_result.score,
                    "sufficient": eval_result.is_sufficient,
                    "reason":     eval_result.reason,
                })

            # Si la réponse est suffisante → génère la réponse finale
            if eval_result.is_sufficient:
                state = self._generate_final_answer(state, ctx, accumulated_tool_results)
                break

            # Sinon → replanifie avec les infos manquantes
            cycles_done += 1
            if cycles_done >= self.MAX_CYCLES:
                # Force la génération avec ce qu'on a
                state = self._generate_final_answer(state, ctx, accumulated_tool_results)
                break

            # Injecte le feedback de l'évaluateur dans le contexte pour replanifier
            ctx["evaluator_feedback"] = eval_result.reason

        else:
            state = self._generate_final_answer(state, ctx, accumulated_tool_results)

        state.status = AgentStatus.DONE
        log.info(
            "main_loop.end run_id=%s duration_ms=%.0f iterations=%s tools=%s status=%s",
            state.run_id,
            (time.perf_counter() - loop_started) * 1000,
            state.iterations,
            len(state.tool_results),
            state.status.value,
        )
        return state

    # ──────────────────────────────────────────────
    # GÉNÉRATION DE LA RÉPONSE FINALE
    # ──────────────────────────────────────────────

    def _generate_final_answer(
        self,
        state: AgentState,
        ctx: dict,
        tool_results: list[dict],
    ) -> AgentState:
        """Synthèse finale — le LLM génère la réponse en prose."""
        # Des outils ont été appelés mais aucun n'a renvoyé de données valides :
        # on n'appelle pas le LLM (il pourrait inventer une météo plausible).
        if tool_results and not any(
            r.get("result") and not r.get("result", {}).get("error")
            for r in tool_results
        ):
            state.final_answer = (
                "Je n'ai pas pu récupérer les prévisions météo pour le moment. "
                "Veuillez réessayer dans quelques instants."
            )
            return state
        with self.tracer.span("synthesize", state.run_id) as s:
            client, model = self._get_llm()
            reasoning_kwargs = (
                {"extra_body": {"reasoning_effort": "low", "include_reasoning": False}}
                if "gpt-oss" in model
                else {}
            )

            synthesis_prompt = _build_synthesis_prompt(
                query        = state.user_query,
                tool_results = tool_results,
                context      = ctx,
                plan         = state.plan,
                eval_result  = state.eval_result,
            )

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=synthesis_prompt,
                    max_tokens=800,
                    **reasoning_kwargs,
                    temperature=0.3,
                )

                state.final_answer = resp.choices[0].message.content or ""
                state.tokens_used += resp.usage.total_tokens if resp.usage else 0
            except Exception as e:
                s.error(str(e))
                state.final_answer = (
                    "⚠️ Désolé, je n'ai pas pu récupérer les informations météo "
                    "pour le moment. Veuillez réessayer dans quelques instants."
                )

        return state


# ──────────────────────────────────────────────────────────────
# SYNTHESIS PROMPT BUILDER
# ──────────────────────────────────────────────────────────────

def _build_synthesis_prompt(
    query:        str,
    tool_results: list[dict],
    context:      dict,
    plan:         ExecutionPlan | None,
    eval_result:  EvalResult | None,
) -> list[dict]:
    """Construit le prompt de synthèse finale séparé du prompt de planning."""

    from core.prompts import get_synthesis_system_prompt
    synthesis_system_prompt = get_synthesis_system_prompt()  # date recalculée à chaque appel

    tool_summary = json.dumps(tool_results, ensure_ascii=False, indent=2)[:3000]

    history_text = ""
    if context.get("recent_turns"):
        turns = context["recent_turns"][-4:]
        history_text = "\n".join(
            f"{t['role'].upper()}: {t['content'][:200]}" for t in turns
        )

    user_content = f"""Question de l'utilisateur : {query}

Données météo collectées :
{tool_summary}

Historique récent de la conversation :
{history_text if history_text else "Aucun"}

{"Note de l'évaluateur : " + eval_result.reason if eval_result and not eval_result.is_sufficient else ""}

Génère maintenant une réponse finale claire, en prose, adaptée à la question."""

    return [
        {"role": "system",  "content": synthesis_system_prompt},
        {"role": "user",    "content": user_content},
    ]
