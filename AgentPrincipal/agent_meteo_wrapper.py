"""
agent_meteo_wrapper.py — Pont entre l'orchestrateur et WeatherAgent existant.

Intègre weather_agent_v4 directement en Python (sans passer par HTTP/Flask).
Retourne un dict standardisé utilisable par l'orchestrateur et le PertinenceCalculator.
"""

import asyncio
import logging
import sys, os
from unittest import result

from constants import PATH_WEATHER_AGENT
if PATH_WEATHER_AGENT not in sys.path:
    sys.path.insert(0, PATH_WEATHER_AGENT)

from typing import Optional

log = logging.getLogger("AgentMeteoWrapper")
from dotenv import load_dotenv

load_dotenv()  # ← avant tout import qui lit os.getenv()
# ─────────────────────────────────────────────────────────────────────────────
# IMPORT DYNAMIQUE DU WEATHER AGENT
# ─────────────────────────────────────────────────────────────────────────────
def _import_weather_agent():
    
    try:
        from core.agent import WeatherAgent, AgentState, AgentStatus

        return WeatherAgent, AgentState, AgentStatus
    except ImportError as e:
        log.error(f"[METEO] Impossible d'importer WeatherAgent : {e}")
        return None, None, None


WeatherAgent, AgentState, AgentStatus = _import_weather_agent()
print(f">>> WeatherAgent = {WeatherAgent}")

# ─────────────────────────────────────────────────────────────────────────────
# WRAPPER PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class AgentMeteoWrapper:
    """
    Wrapper autour de WeatherAgent pour l'intégrer dans le pipeline de l'orchestrateur.

    Retourne un dict standardisé :
    {
        "disponible": True,
        "final_answer": "Il fait 24°C à Tunis...",   # prose prête à afficher
        "donnees_brutes": {                           # pour PertinenceCalculator
            "temperature": 24,
            "vent_kmh": 15,
            "alerte": {
                "level": "VERT",         # VERT / ORANGE / ROUGE
                "outdoor_ok": True,
                "message": "..."
            }
        },
        "ville": "Tunis",
        "erreur": None
    }
    """

    def __init__(self):
        self._agent = None
        self._available = WeatherAgent is not None

    def _get_agent(self):
        if self._agent is None and self._available:
            try:
                import sys, os
                from pathlib import Path

                # Purger tous les packages qui peuvent entrer en conflit
                PREFIXES_A_PURGER = ("core", "memory", "tools", "observability")
                to_delete = [k for k in sys.modules if any(k == p or k.startswith(p + ".") for p in PREFIXES_A_PURGER)]
                for k in to_delete:
                    del sys.modules[k]

                # Forcer weather_agent_v4 en tête de path
                if PATH_WEATHER_AGENT not in sys.path:
                    sys.path.insert(0, PATH_WEATHER_AGENT)

                from core.model_router import ModelRouter, TaskType
                from core.agent import WeatherAgent as _WA
                from memory.context import ContextManager
                from observability.tracer import AgentTracer
                from tools.weather_tools import registry as tool_registry

                _router = ModelRouter()
                _context = ContextManager(Path("weather_memory.json"))
                _tracer = AgentTracer(None)

                def _llm_factory(task_type: TaskType = TaskType.SYNTHESIZE):
                    return _router.get(task_type)

                self._agent = _WA(
                    llm_client_factory=_llm_factory,
                    tool_registry=tool_registry,
                    context_manager=_context,
                    tracer=_tracer,
                )
                log.info("[METEO] WeatherAgent initialisé avec succès")

            except Exception as e:
                log.error(f"[METEO] Erreur init WeatherAgent : {e}", exc_info=True)
                self._available = False
        return self._agent

    async def get_weather(self, message: str, session_id: str = "default") -> dict:
        """
        Appelle WeatherAgent et retourne un dict standardisé.

        Args:
            message: La question météo de l'utilisateur (ex: "Quel temps fait-il à Tunis ?")
            session_id: ID de session pour le contexte

        Returns:
            Dict standardisé avec final_answer, donnees_brutes, etc.
        """
        if not self._available:
            log.warning("[METEO] WeatherAgent non disponible — fallback")
            return self._fallback_response()

        agent = self._get_agent()
        if agent is None:
            log.error("[METEO] _get_agent() a retourné None — voir logs init")
            return self._fallback_response(erreur="agent_init_failed")

        try:
            # WeatherAgent.run() est synchrone — on wrap dans asyncio.to_thread
            _t0 = asyncio.get_running_loop().time()
            state = await asyncio.to_thread(agent.run, session_id, message)
            log.warning(
                "[METEO] WeatherAgent.run : %.1fs",
                asyncio.get_running_loop().time() - _t0,
            )
            return self._parse_state(state)

        except asyncio.TimeoutError:
            log.warning("[METEO] Timeout WeatherAgent")
            return self._fallback_response(erreur="timeout")
        except Exception as e:
            log.error(f"[METEO] Erreur WeatherAgent : {e}")
            return self._fallback_response(erreur=str(e))

    def _parse_state(self, state) -> dict:
        """
        Transforme un AgentState en dict standardisé.
        Extrait final_answer, tool_results (données brutes), et l'alerte.
        """
        # Vérifier le statut
        if AgentStatus and hasattr(state, "status"):
            if state.status == AgentStatus.FAILED:
                return self._fallback_response(erreur=getattr(state, "error", "FAILED"))

        final_answer = getattr(state, "final_answer", "") or ""
        tool_results = getattr(state, "tool_results", []) or []
        erreur = getattr(state, "error", None)

        # Extraire les données brutes depuis tool_results
        donnees_brutes = self._extract_raw_data(tool_results)

        # Extraire la ville depuis les données brutes ou la réponse
        ville = donnees_brutes.get("ville", "")

        return {
            "disponible": True,
            "response": final_answer,
            "error": erreur,
            "payload": {
                "_raw": {
                    "final_answer": final_answer,
                    "donnees_brutes": donnees_brutes,
                    "ville": ville,
                }
            },
        }

    def _extract_raw_data(self, tool_results: list) -> dict:
        """
        Extrait les données météo structurées depuis les tool_results.
        Cherche température, vent, alerte.level, alerte.outdoor_ok.
        """
        donnees = {
            "temperature": None,
            "temperature_ressentie": None,
            "vent_kmh": None,
            "precipitations_mm": None,
            "humidite_pct": None,
            "description": "",
            "alerte": {
                "level": "VERT",
                "outdoor_ok": True,
                "message": "",
            },
            "ville": "",
        }

        for result in tool_results:
            if not isinstance(result, dict):
                continue

            # Données météo directes
            if "temperature" in result:
                donnees["temperature"] = result.get("temperature")
            if "temperature_ressentie" in result:
                donnees["temperature_ressentie"] = result.get("temperature_ressentie")
            if "vent_kmh" in result or "wind_speed" in result:
                donnees["vent_kmh"] = result.get("vent_kmh") or result.get("wind_speed")
            if "precipitations_mm" in result or "precipitation" in result:
                donnees["precipitations_mm"] = result.get("precipitations_mm") or result.get("precipitation")
            if "humidite" in result or "humidity" in result:
                donnees["humidite_pct"] = result.get("humidite") or result.get("humidity")
            if "description" in result:
                donnees["description"] = result.get("description", "")
            if "ville" in result or "city" in result:
                donnees["ville"] = result.get("ville") or result.get("city", "")

            # Alerte (structure de WeatherAgent)
            alerte = result.get("alerte", result.get("alert", {}))
            if isinstance(alerte, dict):
                level = alerte.get("level", alerte.get("niveau", "VERT"))
                outdoor_ok = alerte.get("outdoor_ok", alerte.get("ok_dehors", True))
                message = alerte.get("message", alerte.get("msg", ""))
                donnees["alerte"] = {
                    "level": str(level).upper(),
                    "outdoor_ok": bool(outdoor_ok),
                    "message": str(message),
                }

        return donnees

    def _fallback_response(self, erreur: Optional[str] = None) -> dict:
        """Réponse de fallback quand WeatherAgent est indisponible."""
        return {
            "disponible": False,
            "response": "",
            "error": erreur or "service_indisponible",
            "payload": {
                "_raw": {
                    "final_answer": "",
                    "donnees_brutes": {
                        "temperature": None,
                        "alerte": {"level": "VERT", "outdoor_ok": True, "message": ""},
                        "ville": "",
                    },
                    "ville": "",
                }
            },
        }

    def get_outdoor_recommendation(self, donnees_brutes: dict, lieu: str = "") -> str:
        """
        Génère une recommandation météo courte pour intégration dans les circuits.
        Utilisé par l'orchestrateur pour enrichir les recommandations de circuit.

        Returns:
            str courte à intégrer naturellement dans la réponse narrative.
            Ex: "Le soleil est avec vous aujourd'hui ☀️"
                "Prévoyez un imperméable, quelques averses dans l'après-midi 🌦️"
                "La pluie est annoncée — mieux vaut privilégier le Bardo aujourd'hui 🏛️"
        """
        alerte = donnees_brutes.get("alerte", {})
        level = alerte.get("level", "VERT")
        outdoor_ok = alerte.get("outdoor_ok", True)
        temp = donnees_brutes.get("temperature")
        ville_info = f" sur {lieu}" if lieu else ""

        if level == "VERT":
            if temp and temp > 28:
                return f"Le soleil est généreux{ville_info} ({temp}°C) — prévoyez de l'eau et de la crème solaire ☀️"
            elif temp and temp < 12:
                return f"Il fait frais{ville_info} ({temp}°C), habillez-vous chaud 🧥"
            else:
                return f"Le temps est agréable{ville_info} pour une sortie ✨"

        elif level == "ORANGE":
            return f"Quelques averses possibles{ville_info} — prévoyez un imperméable 🌦️"

        else:  # ROUGE
            if not outdoor_ok:
                return f"Mauvais temps annoncé{ville_info} — je vous recommande plutôt le Bardo ou la Médina couverte 🏛️"
            return f"Conditions difficiles{ville_info} — restez prudents 🌧️"


# ─────────────────────────────────────────────────────────────────────────────
# INSTANCE GLOBALE (singleton)
# ─────────────────────────────────────────────────────────────────────────────

_meteo_wrapper_instance: Optional[AgentMeteoWrapper] = None


def get_meteo_wrapper() -> AgentMeteoWrapper:
    """Retourne l'instance singleton du wrapper météo."""
    global _meteo_wrapper_instance
    if _meteo_wrapper_instance is None:
        _meteo_wrapper_instance = AgentMeteoWrapper()
    return _meteo_wrapper_instance
