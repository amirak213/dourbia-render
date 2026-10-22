"""
chat.py — Point d'entrée unifié du chatbot touristique tunisien.

Remplace l'ancien chat.py de stage_AI_agentique--master.
Expose une interface simple pour Streamlit et tout autre frontend.

Usage depuis Streamlit :
    from chat import chat

    reponse = asyncio.run(chat(session_id="user-123", message="Bonjour"))

Usage CLI :
    python chat.py
"""

import asyncio
import logging
import os
import sys
from typing import Optional

# ── Assure que le dossier chatbot_tunisie est dans le path ────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chatbot.chat")

from AgentPrincipal.orchestrateur import OrchestratorAgent

# ─────────────────────────────────────────────────────────────────────────────
# INSTANCE GLOBALE (singleton — évite de réinstancier à chaque message)
# ─────────────────────────────────────────────────────────────────────────────

_orchestrateur: OrchestratorAgent | None = None


def _get_orchestrateur(systeme_recommandation=None) -> OrchestratorAgent:
    global _orchestrateur
    if _orchestrateur is None:
        log.info("[CHAT] Initialisation de l'orchestrateur...")
        # PertinenceCalculator/DEAP est un moteur legacy remplacé par CircuitAgent.
        # On ne le charge plus au démarrage (coût de 1-2 min pour un composant mort).
        _orchestrateur = OrchestratorAgent(systeme_recommandation)
        log.info("[CHAT] Orchestrateur prêt.")
    return _orchestrateur

def get_orchestrateur() -> OrchestratorAgent:
    """
    Accès public à l'instance singleton de l'orchestrateur.
    Utilisé par app.py pour appeler des méthodes directes (ex: mode terrain GPS).
    """
    return _get_orchestrateur()


def inject_systeme(systeme) -> None:
    """
    Injecte le système de recommandation (couche math) dans l'orchestrateur.
    À appeler depuis l'application principale après chargement de la DB.

    Exemple depuis Application_streamlit.py :
        from chat import inject_systeme
        from db import get_systeme_recommandation

        systeme = get_systeme_recommandation()
        inject_systeme(systeme)
    """
    orch = _get_orchestrateur()
    orch.inject_systeme(systeme)
    log.info("[CHAT] Système de recommandation injecté dans l'orchestrateur")


# ─────────────────────────────────────────────────────────────────────────────
# INTERFACE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────


async def chat(session_id: str, message: str, action: Optional[dict] = None) -> str:
    """
    Interface principale du chatbot — appelée par Streamlit ou tout autre frontend.

    Args:
        session_id: Identifiant unique de la session utilisateur
                    (ex: "streamlit-abc123", "user-42")
        message: Message brut de l'utilisateur (toute langue supportée)

    Returns:
        Réponse finale en prose, dans la langue de l'utilisateur

    Exemple :
        reponse = await chat("user-123", "Je veux visiter Carthage avec ma famille")
    """
    orchestrateur = _get_orchestrateur()
    return await orchestrateur.handle_message(
        user_id=session_id, message=message, action=action
    )


def chat_sync(session_id: str, message: str) -> str:
    """
    Version synchrone de chat() pour les contextes sans event loop.
    Pratique pour les tests et les intégrations simples.

    Attention : ne pas appeler depuis une coroutine existante (utiliser await chat() à la place).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Dans un event loop existant (ex: Jupyter, Streamlit avec async)
            # → créer une tâche
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, chat(session_id, message))
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(chat(session_id, message))
    except RuntimeError:
        return asyncio.run(chat(session_id, message))


# ─────────────────────────────────────────────────────────────────────────────
# CLI INTERACTIF (pour tester sans Streamlit)
# ─────────────────────────────────────────────────────────────────────────────

async def _cli_loop():
    """Boucle interactive en ligne de commande."""
    print("\n" + "=" * 60)
    print("  Chatbot Touristique Tunisien — Mode CLI")
    print("  Tapez 'quit' ou 'exit' pour quitter")
    print("  Tapez 'reset' pour effacer la session")
    print("=" * 60 + "\n")

    session_id = "cli-session-001"
    print(f"Session : {session_id}\n")

    while True:
        try:
            user_input = input("Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir !")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Au revoir !")
            break

        if user_input.lower() == "reset":
            from AgentPrincipal.session_memory import clear_history, purge_session

            purge_session(session_id)
            global _orchestrateur
            _orchestrateur = None
            print("[Session réinitialisée]\n")
            continue

        if user_input.lower() == "help":
            print("Commandes : quit, exit, reset, help")
            print("Essayez : 'Je voudrais visiter Carthage' ou 'Météo à Tunis ?'\n")
            continue

        print("Aziz : ...", end="\r")
        reponse = await chat(session_id, user_input)
        print(f"Aziz : {reponse}\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(_cli_loop())
