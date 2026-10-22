"""
circuit_engine.py — Moteur de génération de circuit (PertinenceCalculator).

Extrait de app.py pour être importable à la fois par :
  - app.py (endpoint /api/circuits/recommend, résultat mappé vers les
    modèles Pydantic CircuitRecommendResponse)
  - AgentPrincipal/orchestrateur.py (wizard, état CIRCUIT_GENERATION,
    consomme directement le dict brut)

Placé À LA RACINE (E:\\claude, même niveau que app.py) pour éviter tout
import circulaire : app.py importe AgentPrincipal.orchestrateur, et
orchestrateur.py importe ce module — si ce module vivait dans app.py,
orchestrateur.py devrait importer app.py en retour, ce qui casse au
démarrage.

Ce module NE FAIT PAS d'appel LLM ni HTTP — logique mathématique pure
(DEAP / PertinenceCalculator), synchrone et CPU-bound. À appeler depuis
du code async via asyncio.to_thread(...).
"""

from __future__ import annotations



import os

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Caches module-level (chargés une seule fois, paresseusement)
# ---------------------------------------------------------------------------




_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_AGENT_CIRCUIT_DIR = os.path.join(_ROOT_DIR, "AgentCircuit")


