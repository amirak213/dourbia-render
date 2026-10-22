"""
orchestrateur.py — Cerveau central du chatbot touristique tunisien.

Pipeline complet :
1. Détection langue
2. Extraction signaux (regex, sans LLM)
3. Classification intention (LLM rapide)
4. Routing vers agents compétents
5. Collecte réponses agents
6. Synthèse narrative finale (LLM puissant)
7. Mise à jour mémoire

Usage :
    import asyncio
    from orchestrateur import OrchestratorAgent

    orchestrateur = OrchestratorAgent()
    reponse = asyncio.run(orchestrateur.handle_message("user-123", "Bonjour, je veux visiter Carthage"))
    print(reponse)
"""

import asyncio
import json
import logging
import re
import difflib
import time
import uuid
from functools import lru_cache
from typing import Optional

from groq import Groq

from constants import (
    GROQ_API_KEY,
    MODEL_FAST,
    MODEL_SMART,
    AGENT_TIMEOUT_SECONDS,
    ROUTING_TABLE,
    INTENTIONS_VALIDES,
    INTENT_CONFIDENCE_THRESHOLD,
    LIEUX_OUTDOOR,
    LIEUX_INDOOR,
    SYSTEM_PROMPT_ORCHESTRATEUR,
    SYSTEM_PROMPT_INTENTION,
    SYSTEM_PROMPT_SYNTHESE,
    FALLBACK_MESSAGES,
    CLARIFICATION_MESSAGES,
    PROPOSITION_CIRCUIT,
    texte_lieu,
    is_affirmation_circuit,
    INTENTIONS_BLOQUANT_CIRCUIT,
    contient_demande_reservation,
    get_langue_nom,
    TERRAIN_SYSTEM_PROMPT,
    is_affirmation,
    HISTORIQUE_KEYWORDS_FR,
    HISTORIQUE_KEYWORDS_EN,
    HISTORIQUE_KEYWORDS_AR,
)
from AgentPrincipal.session_memory import (
    get_history,
    set_history,
    get_profile,
    update_profile,
    append_to_history,
    _ensure_session,
    set_active_circuit,
    clear_profile_fields,
)
from agent_meteo_wrapper import get_meteo_wrapper
from agent_circuits_wrapper import get_circuits_wrapper
from agent_reservation_wrapper import get_reservation_wrapper

log = logging.getLogger("chatbot.orchestrateur")
from profil_synthetique import ProfilSynthetique

import onboarding
from circuit_presentation import presenter_recommandations
import os
from sentence_transformers import SentenceTransformer
import sys
from wizard_state_machine import (
    start_wizard,
    question_for_state,
    reset_wizard,
    WizardStore,
)

_chatbot_path = os.path.dirname(os.path.abspath(__file__))
_tools_path = os.path.join(_chatbot_path, "tools")
_agenthistorique_backend_path = os.path.join(
    _chatbot_path, "..", "AgentHistorique", "backend"
)
_agenthistorique_backend_path = os.path.abspath(_agenthistorique_backend_path)
if _agenthistorique_backend_path not in sys.path:
    sys.path.insert(0, _agenthistorique_backend_path)

if _tools_path not in sys.path:
    sys.path.insert(0, _tools_path)

_project_root = os.path.abspath(os.path.join(_chatbot_path, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from packs_tool import (  # type: ignore[import]
    is_packs_request,
    get_packs_from_db,
    format_packs_response,
    detect_filter_category,
    get_filter_question,
    detect_filter_location,
    filter_packs,
    pack_to_card_dict,
)
from geo_service import get_geo_service
from agents.historical.historical_agent_proxy import HistoricalAgentProxy
from wizard_state_machine import (
    WizardState,
    WizardEvent,
    WizardStore,
    apply_event,
    start_wizard,
    question_for_state,
    question_for_budget_category,
)
from redis_client import get_redis
from redis_client import get_redis
from securite.output_guard import check_output_generic, check_output_rag  # NOUVEAU

# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATEUR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
_circuit_v2_modules = {}

_WIZARD_RESET_RE = re.compile(
    r"\b(?:annul(?:e|er|ez)?|abandon(?:ne|ner|nez)?|"
    r"stop(?:per|pez)?|recommenc(?:e|er|ez)?|reset)\b",
    re.IGNORECASE,
)


def _load_circuit_v2_modules():
    """Charge une seule fois SessionLocal/CircuitAgent/etc. depuis AgentHistorique/backend/app,
    en contournant le conflit de nom avec le module racine 'app' (app.py, chargé par uvicorn)."""
    if _circuit_v2_modules:
        return _circuit_v2_modules

    backend_path = os.path.abspath(
        os.path.join(_chatbot_path, "..", "AgentHistorique", "backend")
    )
    if backend_path in sys.path:
        sys.path.remove(backend_path)
    sys.path.insert(0, backend_path)
    # _project_root (E:\claude, racine d'app.py) doit être retiré le
    # temps de l'import, sinon il passe devant backend_path dans
    # sys.path et 'app' se résout vers app.py au lieu du package
    project_root_was_in_path = _project_root in sys.path
    if project_root_was_in_path:

        sys.path.remove(_project_root)

    saved = {
        name: mod for name, mod in list(sys.modules.items())
        if name == "app" or name.startswith("app.")
    }
    for name in saved:
        del sys.modules[name]

    try:
        from app.database import SessionLocal
        from app.agents.circuit_agent import CircuitAgent, CircuitAgentError
        from app.models.monument import Monument
        from app.schemas.circuit_agent import (
            CircuitRecommendationRequest,
            CircuitPreferences,
            CircuitRecommendationResponse,
        )
        _circuit_v2_modules.update(
            SessionLocal=SessionLocal,
            CircuitAgent=CircuitAgent,
            CircuitRecommendationRequest=CircuitRecommendationRequest,
            CircuitPreferences=CircuitPreferences,
            CircuitRecommendationResponse=CircuitRecommendationResponse,
            CircuitAgentError=CircuitAgentError,
            Monument=Monument,
        )
        # Renommer dans le cache pour ne plus jamais entrer en collision avec le 'app' racine
        for name in list(sys.modules.keys()):
            if name == "app" or name.startswith("app."):
                sys.modules["_agenthistorique_" + name] = sys.modules[name]
                del sys.modules[name]
    finally:
        # Restaurer le 'app' racine (app.py d'uvicorn) exactement comme avant
        for name, mod in saved.items():
            sys.modules[name] = mod

        if project_root_was_in_path and _project_root not in sys.path:
            sys.path.insert(0, _project_root)

    return _circuit_v2_modules

class CircuitRecommendationBusinessError(Exception):
    """Erreur métier lors de la génération de circuit (contraintes
    irréalisables, monuments introuvables, etc.) — à distinguer d'une
    panne technique. Doit être traduite en 422 par la couche API."""

def _run_circuit_recommendation_sync(request):
    mods = _load_circuit_v2_modules()
    CircuitAgentError = mods["CircuitAgentError"]
    db = mods["SessionLocal"]()
    try:
        agent = mods["CircuitAgent"](db)
        result = agent.recommend(request)
        db.commit()
        return result
    except CircuitAgentError as e:
        db.rollback()
        log.warning(f"[WIZARD] Circuit non réalisable : {e}")
        raise CircuitRecommendationBusinessError(str(e)) from e
    except Exception as e:
        db.rollback()
        log.error(f"[WIZARD] Erreur DB/Agent : {e}")
        raise e
    finally:
        db.close()

class OrchestratorAgent:
    """
    Agent orchestrateur central du chatbot touristique tunisien.

    Orchestre le pipeline complet : détection → routing → agents → synthèse.
    Utilise Groq/llama pour les appels LLM (modèle rapide pour classification,
    modèle puissant pour la synthèse narrative).
    """

    def __init__(self, systeme_recommandation=None):
        """
        Args:
            systeme_recommandation: Instance du système de recommandation (couche math).
                Optionnel — peut être injecté après via inject_systeme().
        """
        # Client Groq
        self._groq = Groq(api_key=GROQ_API_KEY)

        # Wrappers agents
        self._meteo = get_meteo_wrapper()
        self._circuits = get_circuits_wrapper(systeme_recommandation)
        self._reservation = get_reservation_wrapper()
        self._historical = HistoricalAgentProxy()

        log.info("[ORCHESTRATEUR] Initialisé")
        log.info(f"  Météo disponible    : {self._meteo._available}")
        log.info(f"  Circuits disponible : {self._circuits._available}")
        log.info(f"  Réservation disponible : {self._reservation._available}")
        ok = self._historical.start()
        if not ok:
            log.warning("[ORCHESTRATEUR] Agent historique non démarré — fallback actif")

        self._embedding_model = SentenceTransformer(
            os.environ.get(
                "EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            )
        )

    def inject_systeme(self, systeme) -> None:
        """
        Injecte le système de recommandation après init.
        À appeler depuis l'application une fois la DB chargée.
        """
        self._circuits.set_systeme(systeme)
        log.info("[ORCHESTRATEUR] Système de recommandation injecté")

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTHODE PRINCIPALE
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_message(
        self, user_id: str, message: str, action: Optional[dict] = None
    ) -> str:
        """
        Méthode principale appelée à chaque message utilisateur.

        Args:
            user_id: Identifiant unique de la session utilisateur
            message: Message brut de l'utilisateur (toute langue)

        Returns:
            Réponse finale en prose, dans la langue de l'utilisateur, style guide Aziz
        """
        start_ms = int(time.time() * 1000)
        log.info(f"[ORCHESTRATEUR] {user_id} → {message[:80]}")

        try:
            reponse_finale = FALLBACK_MESSAGES.get("FR", "Une erreur est survenue.")

            # ── ÉTAPE 1 : Détection langue ────────────────────────────────
            langue = self._detect_language(message)
            log.info(f"  Langue détectée : {langue}")

            # ── ÉTAPE 2 : Récupération historique et profil ───────────────
            historique = get_history(user_id)
            profil = get_profile(user_id)

            # ── ÉTAPE 2bis : Mode onboarding actif → on continue le probing ──
            if profil.get("mode_onboarding"):
                return await self._handle_onboarding_step(
                    user_id, message, profil, historique, langue
                )
            # ── ÉTAPE 2quater : Mode terrain — user répond à une notification monument ──
            monument_en_attente = profil.get("monument_en_attente")
            if monument_en_attente and (
                is_affirmation(message)
                or self._mentions_monument(message, monument_en_attente.get("nom", ""))
            ):
                return await self._handle_terrain_question(
                    user_id=user_id,
                    monument_id=monument_en_attente["id"],
                    monument_nom=monument_en_attente["nom"],
                    message=message,
                    langue=langue,
                    historique=historique,
                )
            # ── ÉTAPE 2ter : Validation post-onboarding (ex: « ok » après recommandations) ──
            if profil.get("attente_validation_circuit"):
                circuits_list = profil.get("derniers_circuits", {}).get("circuits", [])
                circuit_choisi = self._detect_circuit_selection(message, circuits_list)
                if circuit_choisi:
                    return await self._confirmer_choix_circuit(
                        user_id, message, circuit_choisi, profil, historique, langue
                    )
                if is_affirmation_circuit(message):
                    return await self._confirmer_circuits_en_attente(
                        user_id, message, profil, historique, langue
                    )

            # ── ÉTAPE 2quinquies : Activation du mode guide GPS après choix de circuit ──
            if profil.get("attente_activation_guide") and is_affirmation(message):
                return await self._activer_mode_guide(
                    user_id, message, profil, historique, langue
                )
            # ── ÉTAPE 2sexies : Wizard circuit structuré (Phase 1) ─────────
            wizard_store = WizardStore(await get_redis())

            if action and action.get("type") == "start_wizard":
                wizard = start_wizard(user_id)
                await wizard_store.save(wizard)
                reponse_finale = question_for_state(wizard.state, langue)
                await self._update_memory(
                    user_id=user_id,
                    message=message,
                    reponse=reponse_finale,
                    signaux={"wizard_state": wizard.state.value},
                    langue=langue,
                    intention="WIZARD",
                    historique=historique,
                    profil=profil,
                )
                return reponse_finale

            wizard = await wizard_store.get(user_id)

            if (
                wizard
                and wizard.state == WizardState.CUSTOMIZATION_BUDGET
                and not action
                and not contient_demande_reservation(message)
            ):
                budget_match = re.search(
                    r"(?<!\d)(?P<amount>\d+(?:[.,]\d{1,2})?)\s*"
                    r"(?P<currency>dt|tnd|dinars?)\b",
                    message,
                    re.IGNORECASE,
                )
                if budget_match:
                    tarif = onboarding.detect_tarif(message)
                    if tarif:
                        budget = {
                            "type": tarif,
                            "amount": float(
                                budget_match.group("amount").replace(",", ".")
                            ),
                        }
                        wizard = apply_event(
                            wizard,
                            WizardEvent(type="set_budget", value=budget),
                        )
                        await wizard_store.save(wizard)
                        reponse_finale = question_for_state(wizard.state, langue)
                    else:
                        reponse_finale = question_for_budget_category(langue)

                    await self._update_memory(
                        user_id=user_id,
                        message=message,
                        reponse=reponse_finale,
                        signaux={"wizard_state": wizard.state.value},
                        langue=langue,
                        intention="WIZARD",
                        historique=historique,
                        profil=profil,
                    )
                    return reponse_finale

                # Texte libre pendant un wizard actif : ne jamais redémarrer
                # le wizard ni laisser une classification ambiguë écraser son état.

                # Texte libre pendant un wizard actif : ne jamais redémarrer
            # le wizard ni laisser une classification ambiguë écraser son état.

            if wizard and wizard.state != WizardState.IDLE and not action:
                # Une demande de réservation explicite reste routée normalement.
                if contient_demande_reservation(message):
                    pass
                elif _WIZARD_RESET_RE.search(message):
                    wizard = reset_wizard(user_id)
                    await wizard_store.save(wizard)
                    return (
                        "D'accord, le circuit en cours est annulé. "
                        "Vous pourrez en démarrer un nouveau quand vous le souhaitez."
                    )
                else:
                    return question_for_state(wizard.state, langue)

            if wizard and wizard.state != WizardState.IDLE and action:
                event_type = None
                try:

                    event_type = action.get("type")
                    if not event_type:

                        raise ValueError("action.type manquant ou vide")
                    event = WizardEvent(type=event_type, value=action.get("value"))
                    wizard = apply_event(wizard, event)
                    await wizard_store.save(wizard)
                except ValueError as e:
                    log.warning(f"[WIZARD] Événement invalide : {e}")

                if wizard.state == WizardState.CIRCUIT_GENERATION:
                    reponse_finale = await self._generate_wizard_circuit(
                        user_id, wizard, wizard_store, langue
                    )
                else:
                    reponse_finale = question_for_state(wizard.state, langue)

                if event_type == "confirm_guide_mode":
                    activer = action.get("value") == "yes"
                    circuit_data = (wizard.circuit_result or {}).get("circuit") or {}
                    circuit_confirme_id = (str(uuid.uuid4()) if activer else None)
                    update_profile(
                        user_id,
                        {
                            "mode_guide_actif": activer,
                            "circuit_confirme_id":
    circuit_confirme_id,
                            
                            "circuit_confirme_nom": circuit_data.get("title"),
                            "circuit_etapes": (
                                circuit_data.get("monuments") or [] if activer else []
                            ),
                        },
                    )
                    if activer:
                        reponse_finale = (
                            "Mode Guide GPS activé ! 📍 Autorisez l'accès à votre "
                            "position — je vous guiderai à l'approche de chaque site."
                        )
                    else:
                        reponse_finale = (
                            "Pas de souci ! Votre circuit reste disponible si vous "
                            "changez d'avis."
                        )

                await self._update_memory(
                    user_id=user_id,
                    message=message,
                    reponse=reponse_finale,
                    signaux={"wizard_state": wizard.state.value},
                    langue=langue,
                    intention="WIZARD",
                    historique=historique,
                    profil=profil,
                )
                return reponse_finale
            # Si wizard actif mais pas d'action (texte libre) → déviation,
            # non géré ici (Phase 5 du plan). On laisse tomber dans le flow normal.
            # ── Court-circuit : Suite du filtrage des packs touristiques ──
            if profil.get("attente_filtre_pack", False):
                category = detect_filter_category(message)
                location = detect_filter_location(message)
                msg_lower = message.lower().strip()
                wants_all = any(
                    w in msg_lower
                    for w in [
                        "tous",
                        "tout",
                        "tous les packs",
                        "catalogue",
                        "all",
                        "كل",
                        "الباقات",
                    ]
                )

                if category or location or wants_all:
                    packs = await asyncio.to_thread(get_packs_from_db)
                    filtered = filter_packs(packs, category=category, location=location)
                    reponse_finale = (
                        "Voici les packs disponibles pour vous 👇"
                        if filtered else "Aucun pack disponible pour cette recherche."
                    )

                    profil_update = {
                        "attente_filtre_pack": False,
                        "last_packs": [pack_to_card_dict(p) for p in filtered],
                    }
                    update_profile(user_id, profil_update)

                    await self._update_memory(
                        user_id=user_id,
                        message=message,
                        reponse=reponse_finale,
                        signaux=profil_update,
                        langue=langue,
                        intention="CIRCUIT",
                        historique=historique,
                        profil=profil,
                    )
                    return reponse_finale
                else:
                    # Désactive le drapeau pour éviter de bloquer et on continue le flux normal
                    profil_update = {"attente_filtre_pack": False}
                    update_profile(user_id, profil_update)
                    profil["attente_filtre_pack"] = False

            # ── Court-circuit : Détection initiale packs touristiques ──
            if is_packs_request(message):
                category = detect_filter_category(message)
                location = detect_filter_location(message)
                if category or location:
                    packs = await asyncio.to_thread(get_packs_from_db)
                    filtered = filter_packs(packs, category=category, location=location)
                    reponse_finale = (
                        "Voici les packs disponibles pour vous 👇"
                        if filtered else "Aucun pack disponible pour cette recherche."
                    )
                    profil_update = {"last_packs": [pack_to_card_dict(p) for p in filtered]}
                    update_profile(user_id, profil_update)

                    await self._update_memory(
                        user_id=user_id,
                        message=message,
                        reponse=reponse_finale,
                        signaux={},
                        langue=langue,
                        intention="CIRCUIT",
                        historique=historique,
                        profil=profil,
                    )
                    return reponse_finale
                else:
                    reponse_finale = get_filter_question(lang=langue)
                    profil_update = {"attente_filtre_pack": True}
                    update_profile(user_id, profil_update)

                    await self._update_memory(
                        user_id=user_id,
                        message=message,
                        reponse=reponse_finale,
                        signaux=profil_update,
                        langue=langue,
                        intention="CIRCUIT",
                        historique=historique,
                        profil=profil,
                    )

                    return reponse_finale

            # ── ÉTAPE 3 : Extraction signaux (sans LLM) ───────────────────
            signaux = self._extract_profile_signals(message)
            log.info(f"  Signaux extraits : {signaux}")

            # ── ÉTAPE 4 : Classification intention (LLM rapide) ───────────
            intention_data = await self._detect_intent(
                message, langue, historique, session_id=user_id
            )
            intention = intention_data.get("intention", "SMALLTALK")
            confiance = intention_data.get("confiance", 0.5)
            derniere_intention = profil.get("derniere_intention", "")
            if derniere_intention == "RESERVATION" and intention != "RESERVATION":

                msg_low = message.lower().strip()
                mots_selection_voiture = (
                    "nissan",
                    "hyundai",
                    "volkswagen",
                    "polo",
                    "leaf",
                    "i10",
                    "celle",
                    "celui",
                    "la première",
                    "la deuxieme",
                    "la deuxième",
                    "la troisième",
                )

                intention_ambigue = intention == "SMALLTALK" or confiance < 0.6
                if intention_ambigue and any(
                    m in msg_low for m in mots_selection_voiture
                ):
                    intention = "RESERVATION"
                    confiance = max(confiance, 0.90)
                    log.info(
                        f"  Intention corrigée → RESERVATION (sticky réservation, dernière intention={derniere_intention})"
                    )

            if contient_demande_reservation(message):
                intention = "RESERVATION"
                confiance = max(confiance, 0.9)
                log.info("  Intention forcée → RESERVATION (mots-clés détectés)")
            entites = intention_data.get("entites", {})
            log.info(f"  Intention : {intention} (confiance={confiance:.2f})")

            # Fallback mots-clés : si le LLM hésite ou classe en SMALLTALK, mais que les mots-clés historiques matchent
            if (
                intention in ("SMALLTALK", "CLARIFICATION")
                or confiance < INTENT_CONFIDENCE_THRESHOLD
            ) and self._detect_historique_intent(message, langue):
                ancien_intent = intention
                ancienne_confiance = confiance
                intention = "HISTORIQUE"
                confiance = 0.85
                if ancien_intent != "SMALLTALK":
                    log.info(
                        f"  [MONITORING] Intention corrigée de {ancien_intent} → HISTORIQUE par fallback mots-clés (confiance initiale={ancienne_confiance:.2f})"
                    )
                else:
                    log.info(
                        "  Intention corrigée → HISTORIQUE (mots-clés détectés sur SMALLTALK)"
                    )

            # Si confiance trop faible → demander clarification
            if confiance < INTENT_CONFIDENCE_THRESHOLD and intention not in (
                "SMALLTALK",
                "FEEDBACK",
            ):
                return CLARIFICATION_MESSAGES.get(langue, CLARIFICATION_MESSAGES["FR"])

            # Enrichir signaux avec entités détectées
            signaux.update(
                {k: v for k, v in entites.items() if v and not signaux.get(k)}
            )

            # Réinitialiser la proposition circuit si nouvelle intention forte
            if (
                intention in INTENTIONS_BLOQUANT_CIRCUIT
                and confiance >= INTENT_CONFIDENCE_THRESHOLD
            ):
                signaux["attente_confirmation_circuit"] = False

            # ── Déclenchement onboarding circuit (après exclusion RESERVATION, etc.) ──
            veut_circuit = intention == "CIRCUIT" or (
                intention not in INTENTIONS_BLOQUANT_CIRCUIT
                and profil.get("attente_confirmation_circuit")
                and is_affirmation_circuit(message)
            )
            if veut_circuit:
                wizard_store = WizardStore(await get_redis())
                wizard = start_wizard(user_id)
                await wizard_store.save(wizard)
                reponse_finale = question_for_state(wizard.state, langue)
                await self._update_memory(
                    user_id=user_id,
                    message=message,
                    reponse=reponse_finale,
                    signaux={"wizard_state": wizard.state.value},
                    langue=langue,
                    intention="WIZARD",
                    historique=historique,
                    profil=profil,
                )
                return reponse_finale

            # ── ÉTAPE 5 : Routing et appels agents ────────────────────────
            agents_responses = await self._route_to_agents(
                intention=intention,
                message=message,
                profil=profil,
                signaux=signaux,
                langue=langue,
                user_id=user_id,
                historique=historique,
            )
            log.info(f"  Agents appelés : {list(agents_responses.keys())}")

            # ── ÉTAPE 6 : Synthèse narrative finale ───────────────────────
            attente_circuit = profil.get("attente_confirmation_circuit", False)
            generation_tronquee = False

            if intention == "RESERVATION" and "agent_reservation" in agents_responses:
                res_data = agents_responses["agent_reservation"]
                if res_data and isinstance(res_data, dict) and res_data.get("response"):
                    reponse_finale = res_data["response"]
                else:
                    reponse_finale = FALLBACK_MESSAGES.get(
                        langue, FALLBACK_MESSAGES["FR"]
                    )
                attente_circuit = False

            # ── Court-circuit agent historique ────────────────────────────
            elif intention == "HISTORIQUE" and "agent_guide" in agents_responses:
                hist = agents_responses["agent_guide"]
                if hist.get("error"):
                    error_reason = str(hist["error"])
                    log.error(
                        "[HISTORIQUE] Worker indisponible: %s (query=%r)",
                        error_reason,
                        message[:120],
                    )
                    historique_fallbacks = {
                        "FR": "Le guide historique est momentanément indisponible. Réessayez dans quelques instants.",
                        "EN": "The historical guide is temporarily unavailable. Please try again shortly.",
                        "AR": "المرشد التاريخي غير متاح مؤقتاً. يرجى المحاولة بعد قليل.",
                        "IT": "La guida storica è temporaneamente non disponibile. Riprova tra poco.",
                        "DE": "Der historische Guide ist momentan nicht verfügbar. Bitte versuchen Sie es später erneut.",
                    }
                    reponse_finale = historique_fallbacks.get(
                        langue, historique_fallbacks["FR"]
                    )
                    await self._update_memory(
                        user_id=user_id,
                        message=message,
                        reponse=reponse_finale,
                        signaux=signaux,
                        langue=langue,
                        intention="HISTORIQUE",
                        historique=historique,
                        profil=profil,
                    )
                    return reponse_finale

                if hist.get("answer"):
                    answer = hist["answer"]
                    reponse_llm_brute = (
                        answer  # NOUVEAU : copie AVANT ajout du suffixe Sources
                    )
                    sources = hist.get("sources", [])
                    source_titles = [s["title"] for s in sources[:2] if s.get("title")]
                    if source_titles:
                        answer += f"\n\n*Sources : {', '.join(source_titles)}*"
                    reponse_finale = answer
                    await self._update_memory(
                        user_id=user_id,
                        message=message,
                        reponse=reponse_finale,
                        signaux=signaux,
                        langue=langue,
                        intention="HISTORIQUE",
                        historique=historique,
                        profil=profil,
                        chunks_rag=hist.get("sources", []),
                        texte_a_verifier=reponse_llm_brute,
                    )
                    return reponse_finale

            elif intention == "SMALLTALK":
                reponse_finale, generation_tronquee = await self._respond_smalltalk(
                    message, langue, historique
                )
            else:
                reponse_finale = await self._synthesize_response(
                    agents_responses=agents_responses,
                    langue=langue,
                    historique=historique,
                    message_utilisateur=message,
                    intention=intention,
                    profil=profil,
                )

            # ── Proposition de circuit (une seule fois par session) ───────
            if (
                intention != "RESERVATION"
                and not attente_circuit
                and not (
                    intention == "SMALLTALK" and generation_tronquee
                )
                and not profil.get("proposition_circuit_faite")
                and not profil.get("mode_onboarding")
            ):
                lieu_propose = signaux.get("lieu", "") or profil.get("lieu", "")
                proposition = PROPOSITION_CIRCUIT.get(
                    langue, PROPOSITION_CIRCUIT["FR"]
                ).format(lieu=texte_lieu(langue, lieu_propose))
                reponse_finale = f"{reponse_finale.rstrip()}\n\n{proposition}"
                attente_circuit = True
                signaux["proposition_circuit_faite"] = True

            signaux["attente_confirmation_circuit"] = attente_circuit

            # ── ÉTAPE 7 : Mise à jour mémoire ─────────────────────────────
            await self._update_memory(
                user_id=user_id,
                message=message,
                reponse=reponse_finale,
                signaux=signaux,
                langue=langue,
                intention=intention,
                historique=historique,
                profil=profil,
            )

            latency_ms = int(time.time() * 1000) - start_ms
            log.info(f"[ORCHESTRATEUR] Réponse générée en {latency_ms}ms")

            return reponse_finale

        except Exception as e:
            log.error(f"[ORCHESTRATEUR] Erreur inattendue : {e}", exc_info=True)
            return FALLBACK_MESSAGES.get(
                "FR", "Une erreur est survenue, réessayez dans quelques instants."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # DÉTECTION LANGUE (sans LLM — regex)
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_language(self, message: str) -> str:
        """
        Détecte la langue du message par règles simples.
        Délègue à Agent Multilingue (TODO) pour les cas ambigus.

        Returns:
            Code langue : "FR", "EN", "AR", "IT", "DE"
        """
        msg = message.lower().strip()

        # Arabe : présence de caractères arabes
        if re.search(r"[\u0600-\u06FF]", message):
            return "AR"

        # Mots-clés forts par langue
        fr_keywords = r"\b(bonjour|je|tu|nous|vous|est|sont|avec|pour|dans|sur|qui|que|quoi|comment|combien|merci|salut|bonsoir)\b"
        en_keywords = r"\b(hello|hi|i|we|you|is|are|with|for|in|on|who|what|how|much|thanks|please|want|need|can)\b"
        it_keywords = r"\b(ciao|buongiorno|voglio|sono|con|per|nel|sulla|chi|cosa|come|grazie|salve)\b"
        de_keywords = r"\b(hallo|guten|ich|wir|sie|ist|sind|mit|für|in|auf|wer|was|wie|danke|bitte)\b"

        scores = {
            "FR": len(re.findall(fr_keywords, msg)),
            "EN": len(re.findall(en_keywords, msg)),
            "IT": len(re.findall(it_keywords, msg)),
            "DE": len(re.findall(de_keywords, msg)),
        }

        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
            return best

        # Par défaut : français
        return "FR"

    # ─────────────────────────────────────────────────────────────────────────
    # EXTRACTION SIGNAUX (sans LLM — regex + règles)
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_profile_signals(self, message: str) -> dict:
        """
        Extrait les signaux du message sans LLM (regex + règles).
        Rapide, déterministe, sans latence réseau.

        Returns:
            Dict avec les signaux trouvés :
            {"budget": 150, "taille_groupe": 4, "type_groupe": "famille",
             "duree": "journée", "lieu": "Carthage", "outdoor_detected": True}
        """
        msg = message.lower()
        signaux = {}

        # ── Budget ────────────────────────────────────────────────────────
        budget_match = re.search(
            r"(\d+)\s*(?:dt|dinar|dinars|tnd|€|eur|euro|euros|\$|dollar)", msg
        )
        if budget_match:
            signaux["budget"] = int(budget_match.group(1))

        # ── Taille groupe ─────────────────────────────────────────────────
        groupe_match = re.search(
            r"(\d+)\s*(?:personne|personnes|adulte|adultes|enfant|enfants|pers\.?)", msg
        )
        if groupe_match:
            signaux["taille_groupe"] = int(groupe_match.group(1))
        elif re.search(r"\b(seul|solo|alone)\b", msg):
            signaux["taille_groupe"] = 1
        elif re.search(r"\b(couple|deux|2)\b", msg):
            signaux["taille_groupe"] = 2

        # ── Type de groupe ────────────────────────────────────────────────
        if re.search(r"\b(famille|family|enfant|enfants|kids?|children)\b", msg):
            signaux["type_groupe"] = "famille"
        elif re.search(r"\b(couple|romantique|lune de miel|honeymoon)\b", msg):
            signaux["type_groupe"] = "couple"
        elif re.search(r"\b(groupe|groupe scolaire|amis|friends|school)\b", msg):
            signaux["type_groupe"] = "groupe"
        elif re.search(r"\b(solo|seul|backpacker)\b", msg):
            signaux["type_groupe"] = "solo"

        # ── Durée ─────────────────────────────────────────────────────────
        if re.search(r"\b(demi.?journ[eé]e|half.?day|matinée|après.?midi)\b", msg):
            signaux["duree"] = "demi-journée"
        elif re.search(
            r"\b(journ[eé]e|journée entière|full.?day|toute la journée)\b", msg
        ):
            signaux["duree"] = "journée"
        elif re.search(r"\b(week.?end|2 jours|deux jours)\b", msg):
            signaux["duree"] = "week-end"
        elif re.search(r"\b(\d+)\s*(?:jours?|days?)\b", msg):
            nb_match = re.search(r"(\d+)\s*(?:jours?|days?)", msg)
            if nb_match:
                signaux["duree"] = f"{nb_match.group(1)} jours"

        # ── Lieu ──────────────────────────────────────────────────────────
        lieux_connus = [
            "carthage",
            "médina",
            "medina",
            "bardo",
            "sidi bou saïd",
            "sidi bou said",
            "el jem",
            "dougga",
            "tozeur",
            "douz",
            "kairouan",
            "monastir",
            "mahdia",
            "hammamet",
            "nabeul",
            "bizerte",
            "tabarka",
            "ain draham",
            "tataouine",
            "matmata",
            "chenini",
            "sbeitla",
            "zaghouan",
            "kerkouane",
            "tunis",
        ]
        for lieu in lieux_connus:
            if lieu in msg:
                signaux["lieu"] = lieu.title()
                # Déterminer si outdoor
                signaux["outdoor_detected"] = lieu in LIEUX_OUTDOOR
                break

        # ── Type d'activité ───────────────────────────────────────────────
        if re.search(
            r"\b(historique|histoire|ruines?|archéologie|antiquité|romain|punique)\b",
            msg,
        ):
            signaux["type_activite"] = "historique"
        elif re.search(r"\b(musée|museum|expo|exposition)\b", msg):
            signaux["type_activite"] = "musee"
        elif re.search(
            r"\b(ar|vr|réalité augmentée|réalité virtuelle|immersif|numérique)\b", msg
        ):
            signaux["type_activite"] = "ar_vr"
        elif re.search(r"\b(nature|randonnée|plage|mer|montagne|désert|sahara)\b", msg):
            signaux["type_activite"] = "nature"

        return signaux

    # ─────────────────────────────────────────────────────────────────────────
    # DÉTECTION INTENTION (LLM rapide)
    # ─────────────────────────────────────────────────────────────────────────

    async def _detect_intent(
        self,
        message: str,
        langue: str,
        historique: list = [],
        session_id: str = "",
    ) -> dict:
        """
        Classifie l'intention du message via LLM rapide (llama-3.1-8b-instant).
        Utilise un prompt JSON strict pour avoir un résultat parsable.

        Returns:
            {"intention": "CIRCUIT", "confiance": 0.92, "entites": {...}}
        """
        try:
            # Contexte conversationnel pour aider la classification
            dernier_contexte = ""
            if historique:
                derniers = historique[-4:]
                dernier_contexte = f"\nDerniers échanges : {json.dumps(derniers, ensure_ascii=False)[:300]}"

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._groq.chat.completions.create,
                    model=MODEL_FAST,
                    max_tokens=700,
                    temperature=0.65,
                    reasoning_effort="none",
                    include_reasoning=False,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT_INTENTION},
                        {
                            "role": "user",
                            "content": f"Message : {message}{dernier_contexte}",
                        },
                    ],
                ),
                timeout=AGENT_TIMEOUT_SECONDS,
            )

            raw = (response.choices[0].message.content or "").strip()
            log.debug(
                f"[INTENT] finish_reason={response.choices[0].finish_reason} raw={raw!r}"
            )

            result = json.loads(raw)

            if result.get("intention") not in INTENTIONS_VALIDES:
                result["intention"] = "SMALLTALK"
                result["confiance"] = 0.5

            log.info(
                "[INTENT] classified session_id=%s intention=%s confiance=%s",
                session_id,
                result.get("intention"),
                result.get("confiance"),
            )

            tokens = getattr(response, "usage", None)
            tokens_used = (
                tokens.total_tokens
                if tokens and getattr(tokens, "total_tokens", None)
                else 0
            )
            log.debug(f"[INTENT] Tokens utilisés : {tokens_used}")

            return result

        except asyncio.TimeoutError:
            log.warning("[INTENT] Timeout détection intention")
            return {"intention": "SMALLTALK", "confiance": 0.5, "entites": {}}
        except json.JSONDecodeError as e:
            log.warning(f"[INTENT] JSON invalide : {e}")
            return self._fallback_intent_detection(message)
        except Exception as e:
            log.error(f"[INTENT] Erreur : {e}")
            return {"intention": "SMALLTALK", "confiance": 0.5, "entites": {}}

    def _detect_historique_intent(self, message: str, language: str) -> bool:
        """
        Détecte si le message concerne Carthage / patrimoine historique tunisien.
        Vérifie dans la liste de keywords correspondant à la langue de session.
        """
        msg_lower = (message or "").lower()

        if language == "ar":
            keywords = HISTORIQUE_KEYWORDS_AR
        elif language == "en":
            keywords = HISTORIQUE_KEYWORDS_EN
        else:
            keywords = HISTORIQUE_KEYWORDS_FR

        return any(kw in msg_lower for kw in keywords)

    def _fallback_intent_detection(self, message: str) -> dict:
        """Détection d'intention par mots-clés si le LLM échoue."""
        msg = message.lower()

        if any(
            w in msg
            for w in [
                "réserver",
                "réservation",
                "voiture",
                "hôtel",
                "louer",
                "location",
            ]
        ):
            return {"intention": "RESERVATION", "confiance": 0.8, "entites": {}}
        if any(
            w in msg
            for w in [
                "circuit",
                "itinéraire",
                "visite",
                "excursion",
                "pack",
                "famille",
                "journée",
            ]
        ):
            return {"intention": "CIRCUIT", "confiance": 0.75, "entites": {}}
        if any(
            w in msg
            for w in ["carthage", "bardo", "médina", "histoire", "monument", "ruines"]
        ):
            return {"intention": "HISTORIQUE", "confiance": 0.75, "entites": {}}
        if any(
            w in msg
            for w in ["météo", "temps", "pluie", "soleil", "température", "weather"]
        ):
            return {"intention": "METEO", "confiance": 0.85, "entites": {}}
        if any(
            w in msg
            for w in [
                "horaire",
                "prix",
                "tarif",
                "accès",
                "comment y aller",
                "transport",
            ]
        ):
            return {"intention": "PRATIQUE", "confiance": 0.75, "entites": {}}

        return {"intention": "SMALLTALK", "confiance": 0.6, "entites": {}}

    ORDINAL_PATTERNS = {
        1: [r"\b1\b", r"premier", r"première", r"first", r"أول"],
        2: [r"\b2\b", r"deuxième", r"deuxieme", r"second", r"ثاني"],
        3: [r"\b3\b", r"troisième", r"troisieme", r"third", r"ثالث"],
    }

    def _detect_circuit_selection(self, message: str, circuits: list) -> Optional[dict]:
        """
        Détecte si le message correspond à un choix explicite parmi les circuits proposés.
        Stratégie 1 : index ordinal ("le 2ème", "circuit 1"...)
        Stratégie 2 : matching flou sur le nom ("Carthage + Sidi Bou Saïd")
        """
        if not circuits:
            return None

        msg = message.lower().strip()

        # Index ordinal
        for index, patterns in self.ORDINAL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, msg) and index <= len(circuits):
                    return circuits[index - 1]

        # Matching flou sur le nom
        best_match, best_score = None, 0.0
        for c in circuits:
            nom = (c.get("nom") or "").lower()
            if not nom:
                continue
            score = difflib.SequenceMatcher(None, msg, nom).ratio()
            mots_nom = [m for m in nom.split() if len(m) > 3]
            if any(mot in msg for mot in mots_nom):
                score += 0.2
            if score > best_score:
                best_score, best_match = score, c

        return best_match if best_score >= 0.5 else None

    # ─────────────────────────────────────────────────────────────────────────
    # ROUTING ET APPELS AGENTS
    # ─────────────────────────────────────────────────────────────────────────

    async def _route_to_agents(
        self,
        intention: str,
        message: str,
        profil: dict,
        signaux: dict,
        langue: str,
        user_id: str,
        historique: list,
    ) -> dict:
        """
        Route vers les agents appropriés et collecte leurs réponses.
        Les agents sont appelés en parallèle quand possible.

        Returns:
            Dict {nom_agent: réponse_agent}
        """
        agents_to_call = ROUTING_TABLE.get(intention, ["orchestrateur"])
        responses = {}

        # ── Déterminer si on a besoin de la météo ────────────────────────
        # La météo est enrichie automatiquement pour tous les circuits outdoor
        lieu = signaux.get("lieu", "")
        need_meteo = intention in ("METEO", "CIRCUIT") and (
            any(l in message.lower() for l in LIEUX_OUTDOOR)
            or signaux.get("outdoor_detected", False)
            or True  # la météo reste utile pour toute demande CIRCUIT/METEO
        )

        # ── Appels en parallèle ───────────────────────────────────────────
        tasks = {}

        # Météo en premier (résultat utilisé par d'autres agents)
        if need_meteo or "agent_meteo" in agents_to_call:
            tasks["agent_meteo"] = self._call_agent_meteo(message, user_id)

        # Circuits (attend potentiellement la météo)
        if "agent_circuits" in agents_to_call or "moteur_math" in agents_to_call:
            tasks["agent_circuits"] = None  # Sera appelé après la météo

        # Réservation
        if "agent_reservation" in agents_to_call:
            try:

                # ⚠️ RISQUE DE SATURATION (Phase 2, point 5) :
                # Ce timeout de 180s est nécessaire au démarrage à froid du subprocess
                # Yasmine (Python + appel LLM Groq), mais agent_reservation_wrapper.py
                # sérialise tous les appels via un unique threading.Lock (un seul
                # worker subprocess partagé, cf. _run_worker_sync).
                # Concrètement : si 10 utilisateurs font une demande de réservation
                # en même temps, ils sont traités en file d'attente strictement
                # séquentielle, chacun pouvant attendre jusqu'à 180s son tour +
                # son propre traitement — le 10ème utilisateur peut donc attendre
                # jusqu'à ~1800s (30 min) dans le pire cas avant timeout.
                # Pas de correctif ici : à traiter via un pool de workers ou une
                # file d'attente avec feedback utilisateur ("votre demande est en cours").
                reservation_data = await asyncio.wait_for(
                    self._call_agent_reservation(message, user_id),
                    timeout=180.0,  # subprocess dourbia : démarrage Python + LLM Groq
                )
                responses["agent_reservation"] = reservation_data

            except asyncio.TimeoutError:
                log.warning("[ORCHESTRATEUR] Timeout agent réservation")
                responses["agent_reservation"] = {
                    "disponible": False,
                    "response": None,
                    "error": "timeout",
                    "payload": {"_raw": {}},
                }
            except Exception as e:
                log.warning(
                    f"[ORCHESTRATEUR] Erreur agent réservation : {e}", exc_info=True
                )
                responses["agent_reservation"] = {
                    "disponible": False,
                    "response": None,
                    "error": str(e),
                    "payload": {"_raw": {}},
                }

        # Guide historique / pratique (TODO: RAG pgvector)
        if "agent_guide" in agents_to_call:
            tasks["agent_guide"] = self._call_agent_guide(message, langue, historique)

        # Feedback math (TODO)
        if "agent_feedback_math" in agents_to_call:
            tasks["agent_feedback_math"] = self._call_agent_feedback(message, user_id)

        # ── Exécution avec timeout ────────────────────────────────────────

        # Météo d'abord (pour enrichir les circuits)
        meteo_data = None
        if "agent_meteo" in tasks:
            try:
                meteo_data = await asyncio.wait_for(
                    tasks.pop("agent_meteo"),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
                responses["agent_meteo"] = meteo_data
                log.info(
                    f"  Météo : {self._meteo_raw(meteo_data).get('donnees_brutes', {}).get('alerte', {}).get('level', 'N/A')}"
                )
            except asyncio.TimeoutError:
                log.warning("[ORCHESTRATEUR] Timeout agent météo")
                responses["agent_meteo"] = None

        # Circuits avec données météo
        if "agent_circuits" in tasks or (
            "moteur_math" in agents_to_call and tasks.get("agent_circuits") is None
        ):
            try:
                circuits_data = await asyncio.wait_for(
                    self._call_agent_circuits(message, user_id, signaux, meteo_data),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
                responses["agent_circuits"] = circuits_data
            except asyncio.TimeoutError:
                log.warning("[ORCHESTRATEUR] Timeout agent circuits")
                responses["agent_circuits"] = None

        # Autres agents en parallèle
        remaining = {
            k: v for k, v in tasks.items() if k not in ("agent_meteo", "agent_circuits")
        }
        if remaining:
            results = await asyncio.gather(
                *[
                    asyncio.wait_for(coro, timeout=AGENT_TIMEOUT_SECONDS)
                    for coro in remaining.values()
                ],
                return_exceptions=True,
            )
            for name, result in zip(remaining.keys(), results):
                if isinstance(result, Exception):
                    log.warning(
                        f"[ORCHESTRATEUR] Erreur agent {name} : {result}",
                        exc_info=result,
                    )
                    responses[name] = {
                        "disponible": False,
                        "reponse": None,
                        "erreur": str(result),
                    }
                else:
                    responses[name] = result

        return responses

    def _circuits_raw(self, circuits_data: Optional[dict]) -> dict:
        """Extrait payload['_raw'] d'une réponse AgentResponseBase de l'agent circuits."""
        if not circuits_data:
            return {}
        return circuits_data.get("payload", {}).get("_raw", {})

    def _meteo_raw(self, meteo_response: Optional[dict]) -> dict:
        """Extrait payload['_raw'] d'une réponse AgentResponseBase de l'agent météo."""
        if not meteo_response:
            return {}
        return meteo_response.get("payload", {}).get("_raw", {})

    def _meteo_to_flat(self, meteo_response: Optional[dict]) -> dict:
        """Reconstruit l'ancien format plat météo, pour agent_circuits_wrapper
        qui attend encore ce format (non migré dans ce lot)."""
        if not meteo_response:
            return {
                "disponible": False,
                "final_answer": "",
                "donnees_brutes": {},
                "ville": "",
                "erreur": None,
            }
        raw = self._meteo_raw(meteo_response)
        return {
            "disponible": meteo_response.get("disponible", False),
            "final_answer": raw.get("final_answer", ""),
            "donnees_brutes": raw.get("donnees_brutes", {}),
            "ville": raw.get("ville", ""),
            "erreur": meteo_response.get("error"),
        }

    async def _call_agent_meteo(self, message: str, user_id: str) -> dict:
        """Appel à l'agent météo."""
        return await self._meteo.get_weather(message, user_id)

    async def _call_agent_circuits(self, message, user_id, signaux, meteo_data):
        """
        Appel à l'agent circuits avec ProfilSynthetique.

        CHANGEMENT v2 :
        - Le wrapper construit ProfilSynthetique depuis signaux
        - Plus besoin de client en base
        - Retourne aussi profil_utilise et manquants pour le prompt de synthèse
        """
        meteo_flat = self._meteo_to_flat(meteo_data)
        result = await self._circuits.get_recommendations(
            user_id=user_id,
            signals=signaux,
            n=3,
            meteo_data=meteo_flat,
        )

        # Ajouter conseil météo à chaque circuit
        raw = self._circuits_raw(result)
        if meteo_flat.get("disponible"):
            donnees_brutes = meteo_flat.get("donnees_brutes", {})
            for circuit in raw.get("circuits", []):
                lieu_circuit = signaux.get("lieu", "")
                circuit["conseil_meteo"] = self._meteo.get_outdoor_recommendation(
                    donnees_brutes,
                    lieu=lieu_circuit if circuit.get("outdoor") else "",
                )

        return result

    async def _generate_wizard_circuit(
        self, user_id: str, wizard, wizard_store, langue: str
    ) -> str:

        mods = _load_circuit_v2_modules()
        CircuitRecommendationRequest = mods["CircuitRecommendationRequest"]
        CircuitPreferences = mods["CircuitPreferences"]
        SessionLocal = mods["SessionLocal"]
        Monument = mods["Monument"]

        budget = wizard.budget or {}
        time_constraints = wizard.time_constraints or {}
        start_time = time_constraints.get("start_time")
        end_time = time_constraints.get("end_time")
        duration_minutes = time_constraints.get("duration_minutes")

        # Résout les id_str sélectionnés en PLACE_SELECTION vers des noms,
        # requis par CircuitPreferences.must_visit (list[str] de noms).
        # Si must_visit est vide (étape skip par l'utilisateur), on ne
        # fait aucune requête et must_visit_names reste vide sans erreur.
        must_visit_ids = {str(i) for i in (wizard.must_visit or []) if i}
        must_visit_names: list[str] = []
        if must_visit_ids:
            db = SessionLocal()
            try:
                monuments = db.query(Monument).all()
            finally:
                db.close()
            id_to_name = {m.id_str: m.name_fr for m in monuments if m.id_str}
            must_visit_names = [
                id_to_name[i] for i in must_visit_ids if i in id_to_name
            ]

        epoques = wizard.epoques or []
        fonctions = wizard.fonctions or []

        request = CircuitRecommendationRequest(
            session_id=user_id,
            age=None,
            type_tarif=budget.get("type", "etranger"),
            budget_max=budget.get("amount", 9999),
            transport=wizard.mobility or "walking",
            mobilite=wizard.mobilite,
            zone="Carthage",
            preferences=CircuitPreferences(
                epoques=epoques,
                fonctions=fonctions,
                must_visit=must_visit_names,
                avoid=[],
            ),
            max_stops=12,
            duration_minutes=duration_minutes,
            start_time=start_time,
            end_time=end_time,
        )
        try:
            result = await asyncio.to_thread(_run_circuit_recommendation_sync, request)
            circuits = [result] if result else []
        except Exception as e:
            log.error(f"[WIZARD] Échec technique recommend_circuit : {e}")
            wizard.state = WizardState.CIRCUIT_ADJUSTMENT
            await wizard_store.save(wizard)
            return (
                "Une erreur technique m'empêche de générer votre circuit "
                "pour l'instant — voulez-vous ajuster votre budget ou vos dates "
                "pour réessayer ?"
            )

        if not circuits:
            wizard.state = WizardState.CIRCUIT_ADJUSTMENT
            await wizard_store.save(wizard)
            return (
                "Je n'ai trouvé aucun circuit correspondant à votre budget "
                "ou vos dates — voulez-vous les ajuster ?"
            )

        wizard.circuit_result = circuits[0].response.model_dump()
        wizard.state = WizardState.CIRCUIT_REVIEW
        await wizard_store.save(wizard)
        return question_for_state(wizard.state, langue)

    async def _call_agent_reservation(self, message: str, user_id: str) -> dict:
        """
        Appel à l'agent réservation (Yasmine).
        Le session_id est préfixé pour séparer les contextes.
        """
        # Utilise un session_id dédié pour Yasmine (namespace séparé)
        reservation_session_id = f"reservation_{user_id}"
        return await self._reservation.handle_message(message, reservation_session_id)

    @lru_cache(maxsize=512)
    def _encode_cached(self, message: str) -> tuple:
        """
        Cache LRU sur les embeddings (Phase 2, point 1).
        SentenceTransformer.encode() était recalculé à chaque requête, y compris
        pour des messages identiques (questions répétées, onboarding, etc.).
        Retourne un tuple (hashable, immuable) plutôt qu'un ndarray pour que
        lru_cache puisse comparer/stocker correctement les résultats.
        maxsize=512 : borne la mémoire, les entrées les moins récentes sont évincées.
        """
        return tuple(self._embedding_model.encode(message).tolist())

    async def _call_agent_guide(
        self, message: str, langue: str, historique: list
    ) -> dict:
        """
        Appel à l'agent guide historique (RAG pgvector + web search).
        """
        import os

        query_embedding = list(self._encode_cached(message))
        session_ctx = {}  # profil Redis L1

        try:
            hist_result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._historical.query,
                    query=message,
                    query_embedding=query_embedding,
                    language=langue.lower(),
                    session_context=session_ctx,
                    web_search_enabled=os.environ.get(
                        "WEB_SEARCH_ENABLED", "false"
                    ).lower()
                    == "true",
                ),
                timeout=30.0,
            )
            if isinstance(hist_result, dict):
                hist_result["disponible"] = not bool(hist_result.get("error"))
            else:
                hist_result = {
                    "answer": "",
                    "error": "invalid_format",
                    "disponible": False,
                }
            return hist_result
        except asyncio.TimeoutError:
            log.warning("[ORCHESTRATEUR] Timeout agent guide historique")
            return {"answer": "", "error": "timeout", "disponible": False}
        except Exception as e:
            log.warning(f"[ORCHESTRATEUR] Erreur agent guide historique : {e}")
            return {"answer": "", "error": str(e), "disponible": False}

    async def _call_agent_feedback(self, message: str, user_id: str) -> dict:
        """
        Appel à l'agent feedback (moteur math AgentFeedback).
        TODO: Connecter AgentFeedback depuis Agent_principal.py
        """
        # TODO: from Agent_principal import AgentFeedback
        # feedback_agent = AgentFeedback(systeme)
        # feedback_agent.enregistrer_feedback(user_id, circuit_id, note, commentaire)

        log.info("[FEEDBACK] TODO: AgentFeedback non encore connecté")
        return {
            "disponible": False,
            "response": None,
            "error": "feedback_non_connecte",
            "payload": {"_raw": {}},
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MODE GUIDE TERRAIN
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _mentions_monument(message: str, nom: str) -> bool:
        """True si le message cite le nom du monument en attente (insensible à la casse)."""
        return bool(nom) and nom.casefold() in (message or "").casefold()

    async def handle_proximity_trigger(
        self,
        user_id: str,
        monument_id: str,
        monument_nom: str,
        langue: str = "FR",
    ) -> None:
        """
        Appelé par app.py quand un monument est détecté à proximité.
        Stocke le monument en attente dans le profil session.
        Le user doit confirmer ("oui") pour déclencher la présentation complète.

        Args:
            user_id      : ID de session
            monument_id  : ID du monument détecté
            monument_nom : Nom du monument (pour le profil)
            langue       : Langue de session
        """
        update_profile(
            user_id,
            {
                "monument_en_attente": {
                    "id": monument_id,
                    "nom": monument_nom,
                },
                "mode_terrain": True,
                "langue": langue,
            },
        )
        log.info(
            f"[TERRAIN] Monument en attente enregistré : {monument_nom} ({monument_id})"
        )

    async def _handle_terrain_question(
        self,
        user_id: str,
        monument_id: str,
        monument_nom: str,
        message: str,
        langue: str,
        historique: list,
    ) -> str:
        """
        Génère la présentation narrative complète d'un monument
        quand le user confirme qu'il veut en savoir plus.

        Flow :
        1. Récupère les données complètes du monument depuis la DB
        2. Construit un prompt enrichi (description + horaires + durée)
        3. Appelle LLM puissant avec TERRAIN_SYSTEM_PROMPT
        4. Nettoie le monument_en_attente du profil
        """
        log.info(f"[TERRAIN] Présentation monument : {monument_nom} ({monument_id})")

        # ── Récupérer données complètes du monument ───────────────────────
        geo = get_geo_service()
        monument = await geo.get_monument_by_id(monument_id, langue=langue)

        if not monument:
            # Fallback : présentation générique avec le nom seulement
            monument = {"nom": monument_nom, "description": "", "duree_visite_min": 0}

        # ── Construire le contexte pour le LLM ───────────────────────────
        description = monument.get("description", "")
        description_verifiee = bool(description)
        duree = monument.get("duree_visite_min", 0)
        statut = monument.get("statut", "")
        horaires = monument.get("horaires", {})
        accessibilite = monument.get("accessibilite", "")

        # ── Pas de description en base → on va la chercher via l'agent
        # historique (RAG + fallback web) plutôt que de laisser le LLM
        # narratif inventer une description à partir de rien.
        if not description:
            try:
                requete_hist = f"Parle-moi de {monument.get('nom', monument_nom)} à Carthage"
                embedding = list(self._encode_cached(requete_hist))
                hist_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._historical.query,
                        query=requete_hist,
                        query_embedding=embedding,
                        language=langue.lower(),
                        session_context={},
                        web_search_enabled=True,
                    ),
                    timeout=25.0,
                )
                if isinstance(hist_result, dict) and hist_result.get("sources"):
                    description = hist_result["answer"]
                    description_verifiee = True
                else:
                    log.info(
                        f"[TERRAIN] Fallback historique sans résultat exploitable pour {monument_nom}"
                    )
            except Exception as e:
                log.warning(f"[TERRAIN] Fallback historique indisponible : {e}")
        
        # ── Ni description en base, ni fallback historique exploitable :
        # on arrête ici plutôt que de laisser le LLM narratif "combler le
        # vide" — c'est cette étape qui causait l'invention de détails
        # (souk, marbre sculpté, caravansérails...) sur la Rotonde.
        if not description_verifiee:
            reponse_finale = (
                f"Je n'ai pas encore d'information vérifiée sur {monument.get('nom', monument_nom)}. "
                "Ce que je peux vous confirmer, c'est que ce site fait bien partie du circuit de Carthage"
                + (f", prévu pour environ {duree} minutes de visite" if duree else "")
                + ". N'hésitez pas à me demander un autre monument du circuit !"
            )
            clear_profile_fields(user_id, "monument_en_attente")
            historique.append({"role": "user", "content": message})
            historique.append({"role": "assistant", "content": reponse_finale})
            set_history(user_id, historique)
            return reponse_finale
        # Déterminer horaires selon saison (simple : mois > 4 et < 10 = été)
        import datetime

        mois = datetime.datetime.now().month
        if 4 < mois < 10:
            ouverture = horaires.get("ouverture_ete", "")
            fermeture = horaires.get("fermeture_ete", "")
        else:
            ouverture = horaires.get("ouverture_hiver", "")
            fermeture = horaires.get("fermeture_hiver", "")

        ferme = "fermé" in statut.lower() or "ferme" in statut.lower()

        contexte = f"""Monument : {monument.get('nom', monument_nom)}
Statut : {"FERMÉ" if ferme else "Ouvert"}
Durée de visite conseillée : {duree} minutes
Horaires : {ouverture} — {fermeture}
Accessibilité : {accessibilite}
 
Description :
{description[:800] if description else "Monument historique tunisien."}
"""

        langue_nom = get_langue_nom(langue)
        prompt = f"""Le visiteur est physiquement devant ce monument et veut en savoir plus.
 
{contexte}
 
Génère une présentation narrative vivante en {langue_nom}.
{"⚠️ IMPORTANT : Le monument est actuellement FERMÉ — mentionne-le clairement." if ferme else ""}
"""

        # ── Appel LLM puissant ────────────────────────────────────────────
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._groq.chat.completions.create,
                    model=MODEL_SMART,
                    max_tokens=700,
                    temperature=0.65,
                    reasoning_effort="low",
                    include_reasoning=False,
                    messages=[
                        {
                            "role": "system",
                            "content": f"{TERRAIN_SYSTEM_PROMPT}\n\nIMPORTANT : réponds UNIQUEMENT en {langue_nom}.",
                        },
                        *historique[-4:],
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=AGENT_TIMEOUT_SECONDS + 5,
            )
            reponse_finale = (response.choices[0].message.content or "").strip()

        except Exception as e:
            log.error(f"[TERRAIN] Erreur LLM : {e}")
            reponse_finale = FALLBACK_MESSAGES.get(langue, FALLBACK_MESSAGES["FR"])

        # ── Nettoyer monument_en_attente + mettre à jour mémoire ─────────
        clear_profile_fields(user_id, "monument_en_attente")

        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_finale})
        set_history(user_id, historique)

        return reponse_finale

    # ─────────────────────────────────────────────────────────────────────────
    # ONBOARDING CIRCUIT (probing 8 questions)
    # ─────────────────────────────────────────────────────────────────────────

    async def _start_onboarding(
        self, user_id: str, message: str, profil: dict, historique: list, langue: str
    ) -> str:
        """Démarre le probing circuit : pose la première question."""
        question, historique_probing = await onboarding.premiere_question(langue)

        update_profile(
            user_id,
            {
                "mode_onboarding": True,
                "onboarding_collecte": {},
                "onboarding_historique": historique_probing,
                "attente_confirmation_circuit": False,
                "attente_validation_circuit": False,
                "attente_activation_guide": False,
                "mode_guide_actif": False,
                "langue": langue,
            },
        )

        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": question})
        set_history(user_id, historique)

        return question

    async def _handle_onboarding_step(
        self, user_id: str, message: str, profil: dict, historique: list, langue: str
    ) -> str:
        """Traite une réponse de l'utilisateur pendant le probing circuit."""
        profil_collecte = profil.get("onboarding_collecte", {})
        historique_probing = profil.get("onboarding_historique", [])
        langue = langue or profil.get("langue", "FR")

        # Question hors-sujet (météo, pratique…) pendant le probing : répondre sans avancer
        intention_data = await self._detect_intent(
            message, langue, historique, session_id=user_id
        )
        intention_hs = intention_data.get("intention", "SMALLTALK")
        confiance_hs = intention_data.get("confiance", 0.0)
        if intention_hs == "METEO" and confiance_hs >= 0.8:
            meteo_data = await self._call_agent_meteo(message, user_id)
            reponse_meteo = await self._synthesize_response(
                agents_responses={"agent_meteo": meteo_data},
                langue=langue,
                historique=historique,
                message_utilisateur=message,
                intention="METEO",
                profil=profil,
            )
            manquants = onboarding.champs_manquants(profil_collecte)
            if manquants:
                question_courante = onboarding._question_pour_champ(
                    manquants[0], profil_collecte, langue
                )
                if langue == "EN":
                    suite = (
                        "\n\nWhen you're ready, let's continue planning your tour:\n"
                        f"{question_courante}"
                    )
                else:
                    suite = (
                        "\n\nQuand vous voulez, reprenons la personnalisation de votre circuit :\n"
                        f"{question_courante}"
                    )
                reponse_finale = f"{reponse_meteo.rstrip()}{suite}"
            else:
                reponse_finale = reponse_meteo

            historique.append({"role": "user", "content": message})
            historique.append({"role": "assistant", "content": reponse_finale})
            set_history(user_id, historique)
            update_profile(user_id, {"langue": langue})
            return reponse_finale

        result = await onboarding.step(
            historique_probing, profil_collecte, message, langue
        )

        historique.append({"role": "user", "content": message})

        if result["complete"]:
            profil_synth = onboarding.construire_profil_final(result["profil_collecte"])
            try:
                circuits_data = await self._circuits.get_recommendations(
                    user_id=user_id,
                    signals={},
                    n=3,
                    profil_override=profil_synth,
                )
            except Exception as e:
                log.error(
                    f"[ONBOARDING] Erreur récupération circuits : {e}", exc_info=True
                )
                circuits_data = {"circuits": [], "disponible": False}

            presentation = await self._presenter_circuits_onboarding(
                circuits_data, result["profil_collecte"], langue
            )
            reponse_finale = f"{result['reponse']}\n{presentation}"

            update_profile(
                user_id,
                {
                    "mode_onboarding": False,
                    "onboarding_collecte": {},
                    "onboarding_historique": [],
                    "attente_confirmation_circuit": False,
                    "mode_guide_actif": False,
                    "profil_circuit": profil_synth.to_dict(),
                    "profil_collecte_circuit": result["profil_collecte"],
                    "derniers_circuits": circuits_data,
                    "presentation_circuits": presentation,
                    "attente_validation_circuit": True,
                },
            )
        else:
            reponse_finale = result["reponse"]
            update_profile(
                user_id,
                {
                    "onboarding_collecte": result["profil_collecte"],
                    "onboarding_historique": result["historique"],
                    "langue": langue,
                },
            )

        historique.append({"role": "assistant", "content": reponse_finale})
        set_history(user_id, historique)

        return reponse_finale

    async def _confirmer_circuits_en_attente(
        self, user_id: str, message: str, profil: dict, historique: list, langue: str
    ) -> str:
        """Réaffiche les circuits recommandés après validation utilisateur (ex: « ok »)."""
        presentation = profil.get("presentation_circuits")
        if not presentation:
            circuits_data = profil.get("derniers_circuits", {})
            profil_collecte = profil.get("profil_collecte_circuit", {})
            presentation = await self._presenter_circuits_onboarding(
                circuits_data, profil_collecte, langue
            )
        reponse_finale = presentation

        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_finale})
        set_history(user_id, historique)
        update_profile(user_id, {"attente_validation_circuit": False})

        return reponse_finale

    async def _confirmer_choix_circuit(
        self,
        user_id: str,
        message: str,
        circuit: dict,
        profil: dict,
        historique: list,
        langue: str,
    ) -> str:
        """
        L'utilisateur a choisi un circuit précis parmi les recommandations.
        Active ce circuit pour la session et propose le mode guide GPS.
        """
        circuit_id = circuit.get("circuit_id")
        nom = circuit.get("nom", "")
        if not circuit_id:
            log.error(
                f"[CIRCUIT] circuit_id manquant dans le circuit choisi : {circuit}"
            )
            return FALLBACK_MESSAGES.get(langue, FALLBACK_MESSAGES["FR"])

        set_active_circuit(user_id, circuit_id)

        update_profile(
            user_id,
            {
                "circuit_confirme_id": circuit_id,
                "circuit_confirme_nom": nom,
                "attente_validation_circuit": False,
                "attente_activation_guide": True,
                "mode_guide_actif": False,
            },
        )

        if langue == "EN":
            reponse_finale = (
                f"Great choice — **{nom}**! 🎉\n\n"
                "Would you like to activate GPS Guide mode for this tour? "
                "I'll let you know as you approach each stop."
            )
        elif langue == "AR":
            reponse_finale = (
                f"اختيار ممتاز — **{nom}**! 🎉\n\n"
                "هل ترغب في تفعيل وضع المرشد عبر GPS لهذه الجولة؟"
            )
        else:
            reponse_finale = (
                f"Excellent choix — **{nom}** ! 🎉\n\n"
                "Souhaitez-vous activer le mode Guide GPS pour ce circuit ? "
                "Je vous préviendrai à chaque étape."
            )

        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_finale})
        set_history(user_id, historique)

        return reponse_finale

    async def _activer_mode_guide(
        self,
        user_id: str,
        message: str,
        profil: dict,
        historique: list,
        langue: str,
    ) -> str:
        """
        Confirme l'activation du mode guide GPS.
        Le frontend doit détecter ce flag (via /api/chat ou un futur endpoint dédié)
        pour démarrer le polling de position.
        """
        update_profile(
            user_id,
            {
                "attente_activation_guide": False,
                "mode_guide_actif": True,
            },
        )

        # Cohérence d'état : à ce stade, aucun autre flag "attente_*" ne devrait rester actif.
        # Les transitions précédentes ont déjà désactivé les états incompatibles.

        if langue == "EN":
            reponse_finale = (
                "GPS Guide mode activated! 📍 Please allow location access — "
                "I'll tell you about each site as you approach it."
            )
        elif langue == "AR":
            reponse_finale = "تم تفعيل وضع المرشد! 📍 يرجى السماح بالوصول لموقعك."
        else:
            reponse_finale = (
                "Mode Guide GPS activé ! 📍 Autorisez l'accès à votre position — "
                "je vous parlerai de chaque lieu à mesure que vous vous en approchez."
            )

        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_finale})
        set_history(user_id, historique)

        return reponse_finale

    async def _presenter_circuits_onboarding(
        self, circuits_data: dict, profil_collecte: dict, langue: str
    ) -> str:
        """Affiche les circuits comme l'agent circuit : cartes + description LLM."""
        circuits = self._circuits_raw(circuits_data).get("circuits", [])
        if not circuits:
            return FALLBACK_MESSAGES.get(langue, FALLBACK_MESSAGES["FR"])

        tarif = profil_collecte.get("tarif", "etranger")
        transport = profil_collecte.get("transport", "voiture")
        recs = [
            (c.get("donnees_completes", c), float(c.get("score_global", 0.5)))
            for c in circuits[:3]
        ]
        return await presenter_recommandations(
            recs, profil_collecte, tarif=tarif, transport=transport
        )

    # ─────────────────────────────────────────────────────────────────────────
    # RÉPONSE SMALLTALK DIRECTE
    # ─────────────────────────────────────────────────────────────────────────

    async def _respond_smalltalk(
        self,
        message: str,
        langue: str,
        historique: list,
    ) -> tuple[str, bool]:
        """
        Génère une réponse smalltalk directement (sans passer par les agents).
        L'orchestrateur répond lui-même avec le style Aziz.
        """
        try:
            langue_nom = get_langue_nom(langue)
            messages_llm = [
                {
                    "role": "system",
                    "content": (
                        f"{SYSTEM_PROMPT_ORCHESTRATEUR}\n\n"
                        f"IMPORTANT : réponds UNIQUEMENT en {langue_nom}."
                    ),
                },
                *historique[-6:],
                {"role": "user", "content": message},
            ]

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._groq.chat.completions.create,
                    model=MODEL_SMART,
                    max_tokens=700,
                    reasoning_effort="low",
                    include_reasoning=False,
                    temperature=0.7,
                    messages=messages_llm,
                ),
                timeout=AGENT_TIMEOUT_SECONDS,
            )

            finish_reason = getattr(response.choices[0], "finish_reason", None)
            log.info(
                "[SMALLTALK] finish_reason=%s",
                finish_reason,
            )
            return (
                (response.choices[0].message.content or "").strip(),
                finish_reason == "length",
            )

        except Exception as e:
            log.warning(f"[SMALLTALK] Erreur : {e}")
            return FALLBACK_MESSAGES.get(langue, FALLBACK_MESSAGES["FR"]), False

    # ─────────────────────────────────────────────────────────────────────────
    # SYNTHÈSE NARRATIVE FINALE
    # ─────────────────────────────────────────────────────────────────────────

    async def _synthesize_response(
        self,
        agents_responses: dict,
        langue: str,
        historique: list,
        message_utilisateur: str,
        intention: str,
        profil: dict = {},
    ) -> str:
        """
        Synthétise les réponses des agents en une réponse narrative cohérente.
        Utilise le modèle puissant (llama-3.3-70b) pour la qualité narrative.

        Args:
            agents_responses: Dict des réponses brutes de chaque agent
            langue: Code langue de l'utilisateur
            historique: Historique de la conversation
            message_utilisateur: Message original
            intention: Intention classifiée

        Returns:
            Réponse narrative finale en prose, style guide Aziz
        """
        # ── Préparer le contexte pour le LLM ─────────────────────────────
        contexte_agents = self._format_agents_context(agents_responses, intention)
        langue_nom = get_langue_nom(langue)

        prompt_synthese = f"""Message de l'utilisateur : "{message_utilisateur}"
          Intention détectée : {intention}
          Langue requise : {langue_nom} (code {langue})

         Données des agents :
         {contexte_agents}

         Génère une réponse narrative ENTIÈREMENT en {langue_nom}, style guide Aziz (guide touristique tunisien).
         Maximum 150 mots. Termine par une question de relance."""

        try:
            messages_llm = [
                {
                    "role": "system",
                    "content": (
                        f"{SYSTEM_PROMPT_SYNTHESE}\n\n"
                        f"IMPORTANT : réponds UNIQUEMENT en {langue_nom}."
                    ),
                },
                *historique[-4:],
                {"role": "user", "content": prompt_synthese},
            ]

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._groq.chat.completions.create,
                    model=MODEL_SMART,
                    max_tokens=700,
                    temperature=0.65,
                    reasoning_effort="low",
                    include_reasoning=False,
                    messages=messages_llm,
                ),
                timeout=AGENT_TIMEOUT_SECONDS + 5,  # Synthèse a droit à +5s
            )

            log.info(
                "[SYNTHESE] finish_reason=%s",
                getattr(response.choices[0], "finish_reason", None),
            )
            tokens = response.usage.total_tokens if response.usage else 0
            log.info(f"[SYNTHESE] Tokens utilisés : {tokens}")

            if response.choices[0].finish_reason == "length":
                log.warning("[SYNTHESE] Réponse tronquée (finish_reason=length)")
            return (response.choices[0].message.content or "").strip()

        except asyncio.TimeoutError:
            log.warning("[SYNTHESE] Timeout synthèse")
            return FALLBACK_MESSAGES.get(langue, FALLBACK_MESSAGES["FR"])
        except Exception as e:
            log.error(f"[SYNTHESE] Erreur : {e}")
            return FALLBACK_MESSAGES.get(langue, FALLBACK_MESSAGES["FR"])

    def _format_agents_context(self, agents_responses: dict, intention: str) -> str:
        """
        Formate les réponses des agents en texte structuré pour le prompt de synthèse.

        AJOUTS v2 :
        - Affiche explication personnalisée de chaque circuit
        - Signale les signaux manquants au LLM de synthèse
        - Affiche les scores détaillés (budget, durée) pour que le LLM puisse les commenter
        """
        lines = []

        # ── Météo ─────────────────────────────────────────────────────────────

        meteo = agents_responses.get("agent_meteo")
        if meteo and meteo.get("disponible"):
            meteo_raw = self._meteo_raw(meteo)
            donnees = meteo_raw.get("donnees_brutes", {})
            alerte = donnees.get("alerte", {})
            temp = donnees.get("temperature")
            lines.append("[MÉTÉO]")
            if temp:
                lines.append(f"  Température : {temp}°C")
            lines.append(f"  Alerte : {alerte.get('level', 'VERT')}")
            lines.append(f"  Outdoor OK : {alerte.get('outdoor_ok', True)}")
            if meteo_raw.get("final_answer"):
                lines.append(f"  Résumé : {meteo_raw['final_answer'][:200]}")

        # ── Circuits ──────────────────────────────────────────────────────────
        circuits_data = agents_responses.get("agent_circuits")
        if circuits_data:
            circuits_raw = self._circuits_raw(circuits_data)
            circuits = circuits_raw.get("circuits", [])
            disponible = circuits_data.get("disponible", False)

            tag = "[CIRCUITS RECOMMANDÉS]" if disponible else "[CIRCUITS PAR DÉFAUT]"
            lines.append(f"\n{tag} ({len(circuits)} circuits)")

            for i, c in enumerate(circuits[:3], 1):
                duree_h = c.get("duree_minutes", 0) // 60
                duree_m = c.get("duree_minutes", 0) % 60
                duree_str = f"{duree_h}h{duree_m:02d}" if duree_h else f"{duree_m}min"

                lines.append(
                    f"  {i}. {c.get('nom', 'Circuit')} "
                    f"— {c.get('prix_dt', 0):.0f} DT/pers "
                    f"— {duree_str}"
                )

                # Scores détaillés (pour que le LLM sache quoi valoriser)
                details = c.get("score_details", {})
                score_budget = details.get("budget", None)
                score_duree = details.get("duree", None)

                if score_budget is not None:
                    budget_ok = (
                        "✓ dans le budget"
                        if score_budget >= 0.7
                        else "⚠ proche de la limite"
                    )
                    lines.append(
                        f"     Budget : {budget_ok} (score {score_budget:.2f})"
                    )

                if score_duree is not None:
                    duree_ok = (
                        "✓ durée adaptée" if score_duree >= 0.7 else "⚠ un peu long"
                    )
                    lines.append(f"     Durée : {duree_ok} (score {score_duree:.2f})")

                # Explication personnalisée
                if c.get("explication"):
                    lines.append(f"     Pourquoi : {c['explication']}")

                # Conseil météo
                if c.get("conseil_meteo"):
                    lines.append(f"     Météo : {c['conseil_meteo']}")

                # Monuments inclus
                monuments = c.get("monuments", [])
                if monuments and isinstance(monuments, list):
                    lines.append(
                        f"     Monuments : {', '.join(str(m) for m in monuments[:5])}"
                    )

            # Signaux manquants → le LLM doit poser la question naturellement
            manquants = circuits_raw.get("manquants", [])
            if manquants:
                questions_map = {
                    "budget": "Quel est votre budget approximatif ?",
                    "duree": "Combien de temps avez-vous pour cette visite ?",
                }
                questions = [questions_map[m] for m in manquants if m in questions_map]
                if questions:
                    lines.append(
                        f"\n[À DEMANDER NATURELLEMENT] "
                        f"Pour affiner : {' / '.join(questions)}"
                    )

        # ── Guide historique (RAG) ─────────────────────────────────────────────
        guide = agents_responses.get("agent_guide")
        if guide and guide.get("disponible") and not guide.get("error"):
            lines.append("\n[INFORMATIONS HISTORIQUES (RAG)]")
            if guide.get("contexte_rag"):
                for info in guide["contexte_rag"][:3]:
                    lines.append(f"  - {str(info)[:200]}")
            elif guide.get("answer"):
                lines.append(f"  Réponse de l'agent : {guide['answer']}")

        if not lines:
            lines.append(
                "[Aucune donnée agent disponible — "
                "réponds avec tes connaissances générales sur la Tunisie]"
            )

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # MISE À JOUR MÉMOIRE
    # ─────────────────────────────────────────────────────────────────────────

    async def _update_memory(
        self,
        user_id: str,
        message: str,
        reponse: str,
        signaux: dict,
        langue: str,
        intention: str,
        historique: list,
        profil: dict,
        chunks_rag: Optional[list] = None,
        texte_a_verifier: Optional[str] = None,
    ) -> None:
        """
        Met à jour la mémoire session après chaque échange.
        - Exécute les guardrails de sortie (sécurité) — Niveau 1 systématique,
          Niveau 2 si chunks_rag est fourni (agent historique uniquement)
        - Ajoute le message et la réponse à l'historique
        - Met à jour le profil avec les nouveaux signaux
        """
        # ── Guardrails de sortie — isolés dans leur propre try/except ──────
        # pour qu'une erreur du guard ne bloque jamais l'écriture mémoire.
        try:
            texte_guard = texte_a_verifier if texte_a_verifier is not None else reponse
            if chunks_rag is not None:
                guard_result = check_output_rag(
                    reponse=texte_guard,
                    sources=chunks_rag,
                    question_originale=message,
                    embedding_model=self._embedding_model,
                )

            else:
                guard_result = check_output_generic(
                    reponse=texte_guard,
                    question_originale=message,
                    embedding_model=self._embedding_model,
                )

            if guard_result.langage_inapproprie:
                log.warning(
                    f"[SECURITE] Langage inapproprié détecté (user={user_id}) : "
                    f"{guard_result.termes_detectes}"
                )
            if guard_result.hors_sujet:
                log.info(
                    f"[SECURITE] Réponse hors-sujet potentielle (user={user_id}), "
                    f"score={guard_result.score_similarite_domaine}"
                )
            if guard_result.hallucination_potentielle:
                log.warning(
                    f"[SECURITE] Hallucination potentielle (user={user_id}) : "
                    f"faits non vérifiés={guard_result.faits_non_verifies}"
                )
        except Exception as e:
            log.error(f"[SECURITE] Erreur guard de sortie : {e}")

        try:
            # Ajouter l'échange à l'historique
            historique.append({"role": "user", "content": message})
            historique.append({"role": "assistant", "content": reponse})
            set_history(user_id, historique)

            # Mettre à jour le profil
            profil_update = {k: v for k, v in signaux.items() if v is not None}
            profil_update["langue"] = langue
            profil_update["derniere_intention"] = intention
            profil_update["nb_echanges"] = profil.get("nb_echanges", 0) + 1
            update_profile(user_id, profil_update)

        except Exception as e:
            log.error(f"[MEMORY] Erreur mise à jour : {e}")


# ─────────────────────────────────────────────────────────────────────────────
# EXEMPLE D'UTILISATION
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    async def demo():
        """Démonstration du pipeline complet."""
        print("=" * 60)
        print("Chatbot Touristique Tunisien — Démo")
        print("=" * 60)

        orchestrateur = OrchestratorAgent()

        # Exemple 1 : Famille avec budget
        print("\n[TEST 1] Famille, budget 150 DT, journée")
        reponse = await orchestrateur.handle_message(
            user_id="demo-user-001",
            message="Bonjour, je suis avec ma famille, on a une journée à Tunis, budget 150 DT pour 4 personnes",
        )
        print(f"Dourbia : {reponse}\n")

        # Exemple 2 : Question historique
        print("[TEST 2] Question historique")
        reponse = await orchestrateur.handle_message(
            user_id="demo-user-001",
            message="C'est quoi l'histoire de Carthage ?",
        )
        print(f"Dourbia : {reponse}\n")

        # Exemple 3 : Météo
        print("[TEST 3] Question météo")
        reponse = await orchestrateur.handle_message(
            user_id="demo-user-002",
            message="Quel temps fait-il à Tunis aujourd'hui ?",
        )
        print(f"Dourbia : {reponse}\n")

        # Exemple 4 : Réservation voiture
        print("[TEST 4] Réservation voiture")
        reponse = await orchestrateur.handle_message(
            user_id="demo-user-003",
            message="Je voudrais louer une voiture à Tunis du 10 au 15 juillet",
        )
        print(f"Yasmine : {reponse}\n")

        # Exemple 5 : Smalltalk
        print("[TEST 5] Smalltalk")
        reponse = await orchestrateur.handle_message(
            user_id="demo-user-001",
            message="Bonjour !",
        )
        print(f"Dourbia : {reponse}\n")

    asyncio.run(demo())
