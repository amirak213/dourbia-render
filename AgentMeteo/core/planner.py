"""
AgentPlanner — Module de planification autonome.
Le planner décompose la question en steps AVANT d'exécuter quoi que ce soit.
Séparé du prompt de synthèse (Single Responsibility).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.utils import safe_json_parse as _safe_json_parse


@dataclass
class PlanStep:
    """Un step atomique du plan d'exécution."""
    step_id:    int
    tool_name:  str
    tool_args:  dict
    rationale:  str           # pourquoi ce step est nécessaire
    depends_on: list[int] = field(default_factory=list)  # DAG de dépendances


@dataclass
class ExecutionPlan:
    """Plan complet généré par le planner."""
    intent:       str           # intention détectée (météo_actuelle, prévision, comparaison…)
    steps:        list[PlanStep]
    city:         str | None    # ville principale extraite
    time_horizon: str           # "now", "tomorrow", "week"…
    language:     str           # langue détectée de l'utilisateur
    confidence:   float         # 0.0–1.0


# Prompt de planification — SÉPARÉ du prompt de synthèse
PLANNER_SYSTEM = """Tu es le module de PLANIFICATION d'un agent météo.
Ta SEULE responsabilité : analyser la question et produire un plan JSON.
Tu ne génères JAMAIS de réponse en langage naturel.

OUTILS DISPONIBLES :
{tools_description}

HISTORIQUE RÉCENT :
{history}

RÈGLES DE PLANIFICATION :
1. Un seul outil si la question est simple (météo actuelle d'une ville).
2. Deux outils si la question compare deux villes.
3. Zéro outil si la réponse est déjà dans l'historique ou si c'est une question hors-météo.
4. Identifie toujours la ville (utilise l'historique si non mentionnée).
5. Détecte la langue de l'utilisateur.
6. city_name doit être UNIQUEMENT le nom de la ville, sans pays. Ex: "Tunis", "Sfax", "Djerba".

RETOURNE UNIQUEMENT ce JSON valide, rien d'autre :
{
  "intent": "météo_actuelle | prévision | comparaison | hors_météo",
  "city": "nom de la ville ou null",
  "time_horizon": "now | today | tomorrow | day_after | week | weekend | specific_day",
  "specific_day": "lundi|mardi|... ou null",
  "language": "fr | en | ar",
  "confidence": 0.95,
  "steps": [
    {
      "step_id": 1,
      "tool_name": "get_weather | get_forecast | compare_cities",
      "tool_args": {"city_name": "Tunis", "days": 3, "target_day": null},
      "rationale": "pourquoi ce step",
      "depends_on": []
    }
  ]
}"""


class AgentPlanner:
    """
    Planificateur autonome — produit un ExecutionPlan structuré.
    Ne fait JAMAIS d'appel API météo. Pur raisonnement.
    """

    def __init__(self, llm_client_factory):
        self._get_llm = llm_client_factory

    def plan(
        self,
        query:           str,
        context:         dict,
        previous_tools:  list[dict],
        available_tools: str,
    ) -> ExecutionPlan:
        """
        Génère un plan d'exécution structuré.
        Si le LLM échoue → fallback déterministe.
        """
        history_text = self._format_history(context.get("recent_turns", []))

        system_prompt = (
            PLANNER_SYSTEM
            .replace("{tools_description}", available_tools)
            .replace("{history}", history_text or "Aucun historique.")
        )

        # Contexte des tools déjà exécutés (pour éviter duplicates)
        already_done = ""
        if previous_tools:
            already_done = f"\nTools déjà exécutés dans ce run : {[t.get('tool_name') for t in previous_tools]}"

        try:
            client, model = self._get_llm()
            reasoning_kwargs = (
                {"extra_body": {"reasoning_effort": "low", "include_reasoning": False}}
                if "gpt-oss" in model
                else {}
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Question : {query}{already_done}"},
                ],
                max_tokens=700,
                temperature=0.1,  # déterministe pour le planning
                response_format=(
                    {"type": "json_object"} if _supports_json_mode(model) else None
                ),
                **reasoning_kwargs,
            )

            raw = resp.choices[0].message.content or "{}"
            plan_dict = _safe_json_parse(raw)
            return self._dict_to_plan(plan_dict, query)

        except Exception as e:
            # Fallback déterministe — ne jamais crasher sur le planning
            return self._fallback_plan(query, context)

    # ──────────────────────────────────────────────
    # FALLBACK DÉTERMINISTE
    # ──────────────────────────────────────────────

    def _fallback_plan(self, query: str, context: dict) -> ExecutionPlan:
        """
        Plan basé sur des règles simples — zéro LLM.
        Utilisé si le LLM de planning est indisponible.
        """
        q = query.lower()

        # Détection ville depuis historique
        city = context.get("last_city", "Tunis")

        # Détection intention
        if any(w in q for w in ["compare", "vs", "ou", "lequel", "mieux"]):
            # Comparaison — extrait deux villes si possible
            cities = _extract_cities_fallback(q)
            if len(cities) >= 2:
                return ExecutionPlan(
                    intent="comparaison",
                    city=cities[0],
                    time_horizon="now",
                    language=_detect_lang(q),
                    confidence=0.6,
                    steps=[PlanStep(
                        step_id=1,
                        tool_name="compare_cities",
                        tool_args={"city1": cities[0], "city2": cities[1]},
                        rationale="Comparaison de deux villes détectée",
                    )],
                )

        future_keywords = ["demain","après-demain","week-end","semaine",
                           "lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
        if any(w in q for w in future_keywords):
            target_day = next((w for w in future_keywords if w in q), None)
            days = _days_for_target(target_day)
            return ExecutionPlan(
                intent="prévision",
                city=city,
                time_horizon="future",
                language=_detect_lang(q),
                confidence=0.7,
                steps=[PlanStep(
                    step_id=1,
                    tool_name="get_forecast",
                    tool_args={"city_name": city, "days": days, "target_day": target_day},
                    rationale=f"Prévision pour {target_day or 'les prochains jours'}",
                )],
            )

        # Défaut : météo actuelle
        return ExecutionPlan(
            intent="météo_actuelle",
            city=city,
            time_horizon="now",
            language=_detect_lang(q),
            confidence=0.5,
            steps=[PlanStep(
                step_id=1,
                tool_name="get_weather",
                tool_args={"city_name": city},
                rationale="Météo actuelle par défaut",
            )],
        )

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _dict_to_plan(self, d: dict, original_query: str) -> ExecutionPlan:
        steps = []
        for s in d.get("steps", []):
            tool_args = s.get("tool_args", {})
            if "city_name" in tool_args:
                tool_args["city_name"] = (
                tool_args["city_name"]
                .replace(" Tunisia", "")
                .replace(" Tunisie", "")
                .strip()
            )
            steps.append(PlanStep(
            step_id    = s.get("step_id", 1),
            tool_name  = s.get("tool_name", "get_weather"),
            tool_args  = tool_args,
            rationale  = s.get("rationale", ""),
            depends_on = s.get("depends_on", []),
        ))

        specific_day = d.get("specific_day")
        if specific_day:
            for step in steps:
                if step.tool_name == "get_forecast":
                    step.tool_args["target_day"] = specific_day
                    step.tool_args["days"] = _days_for_target(specific_day)

        return ExecutionPlan(
            intent=d.get("intent", "météo_actuelle"),
            steps=steps,
            city=d.get("city"),
            time_horizon=d.get("time_horizon", "now"),
            language=d.get("language", "fr"),
            confidence=float(d.get("confidence", 0.8)),
        )

    @staticmethod
    def _format_history(turns: list[dict]) -> str:
        if not turns:
            return ""
        return "\n".join(
            f"{t['role'].upper()}: {t['content'][:150]}"
            for t in turns[-6:]
        )


# ──────────────────────────────────────────────────────────────
# UTILITAIRES
# ──────────────────────────────────────────────────────────────

# _safe_json_parse est importé depuis core.utils


def _supports_json_mode(model: str) -> bool:
    """Certains modèles ne supportent pas response_format."""
    supported_prefixes = ("gpt-", "claude-", "llama-3", "openai/gpt-")
    return any(model.startswith(p) for p in supported_prefixes)


def _detect_lang(text: str) -> str:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    if arabic_chars > 2:
        return "ar"
    english_words = {"weather","what","how","tomorrow","today","forecast"}
    if any(w in text.lower() for w in english_words):
        return "en"
    return "fr"


def _days_for_target(target: str | None) -> int:
    mapping = {
        "demain": 1, "après-demain": 2,
        "lundi": 7, "mardi": 7, "mercredi": 7, "jeudi": 7,
        "vendredi": 7, "samedi": 7, "dimanche": 7,
        "week-end": 7, "semaine": 7,
    }
    return mapping.get((target or "").lower(), 3)


_TUNISIAN_CITIES = [
    "tunis","sfax","sousse","kairouan","bizerte","gabès","ariana","gafsa",
    "monastir","djerba","nabeul","hammamet","tozeur","douz","tabarka",
    "sidi bou said","carthage","el kef","mahdia","zarzis","tataouine",
    "béja","jendouba","siliana","kasserine","sidi bouzid","medenine",
]

def _extract_cities_fallback(query: str) -> list[str]:
    found = [c for c in _TUNISIAN_CITIES if c in query.lower()]
    return found[:2]
