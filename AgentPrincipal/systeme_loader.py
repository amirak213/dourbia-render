"""
systeme_loader.py — Charge le moteur de recommandation de circuits pour le CLI.
Essaie PostgreSQL (sig_dourbia), sinon fallback sur Profile_circuit.json.
"""

import logging
import os
import sys

from constants import PATH_CIRCUIT_AGENT

log = logging.getLogger("chatbot.systeme_loader")


class SystemeMinimal:
    """Adaptateur minimal compatible avec AgentCircuitsWrapper."""

    def __init__(self, calculateur):
        self.calculateur = calculateur
        self.nb_circuits = len(calculateur.circuits)


def _ensure_circuit_path():
    if PATH_CIRCUIT_AGENT not in sys.path:
        sys.path.insert(0, PATH_CIRCUIT_AGENT)


def _charger_depuis_postgresql():
    """Tente de charger circuits depuis PostgreSQL."""
    _ensure_circuit_path()
    try:
        from db import test_connexion, charger_tous_circuits
        from PertinenceCalculator import PertinenceCalculator

        if not test_connexion():
            return None

        circuits_brut = charger_tous_circuits()
        if not circuits_brut:
            return None

        calculateur = PertinenceCalculator()
        calculateur.circuits = circuits_brut
        log.info(f"[SYSTEME] {len(circuits_brut)} circuits chargés depuis PostgreSQL")
        return SystemeMinimal(calculateur)
    except Exception as e:
        log.debug(f"[SYSTEME] PostgreSQL indisponible : {e}")
        return None


def _charger_depuis_json():
    """Fallback : circuits depuis Profile_circuit.json."""
    _ensure_circuit_path()
    json_path = os.path.join(PATH_CIRCUIT_AGENT, "Profile_circuit.json")
    if not os.path.exists(json_path):
        return None

    try:
        from PertinenceCalculator import PertinenceCalculator

        calculateur = PertinenceCalculator(fichier_circuits_json=json_path)
        if not calculateur.circuits:
            return None
        log.info(f"[SYSTEME] {len(calculateur.circuits)} circuits chargés depuis JSON")
        return SystemeMinimal(calculateur)
    except Exception as e:
        log.warning(f"[SYSTEME] Erreur chargement JSON : {e}")
        return None


def charger_systeme():
    """
    Charge le système de recommandation.
    Returns:
        SystemeMinimal ou None si indisponible.
    """
    systeme = _charger_depuis_postgresql()
    if systeme:
        return systeme
    return _charger_depuis_json()
