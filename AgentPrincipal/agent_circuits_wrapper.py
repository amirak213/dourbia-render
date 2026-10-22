"""
agent_circuits_wrapper.py — Pont entre l'orchestrateur et la couche math existante.

MODIFICATION PRINCIPALE v2 :
    Bypass complet de get_client() / recommander_pour_client().
    On appelle directement systeme.calculateur.recommander(profil=ProfilSynthetique)
    ce qui permet de recommander sans client en base PostgreSQL.

    Pipeline :
        signaux (dict) → ProfilSynthetique → calculateur.recommander()
                       → AgentRecommandationPrincipal (enrichissement agents)
                       → dict standardisé
"""

import asyncio
import logging
import sys
from typing import Optional

from constants import PATH_CIRCUIT_AGENT
from circuit_presentation import fusionner_avec_circuits_bruts, prix_pour_tarif
from profil_synthetique import ProfilSynthetique

log = logging.getLogger("chatbot.agent_circuits")

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT DYNAMIQUE DU MOTEUR MATH
# ─────────────────────────────────────────────────────────────────────────────


def _import_circuit_agent():
    """Import dynamique depuis stage_AI_agentique--master."""
    if PATH_CIRCUIT_AGENT not in sys.path:
        sys.path.insert(0, PATH_CIRCUIT_AGENT)
    try:
        from Agent_principal import AgentRecommandationPrincipal  # type: ignore

        return AgentRecommandationPrincipal
    except ImportError as e:
        log.error(
            f"[CIRCUITS] Impossible d'importer AgentRecommandationPrincipal : {e}"
        )
        return None
    except Exception as e:
        log.error(f"[CIRCUITS] Erreur import : {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# WRAPPER PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────


class AgentCircuitsWrapper:
    """
    Wrapper autour de AgentRecommandationPrincipal pour le pipeline orchestrateur.

    Changement v2 :
        - Ne crée plus de client en base
        - Construit un ProfilSynthetique depuis les signaux
        - Appelle calculateur.recommander() directement
        - Enrichit ensuite avec AgentRecommandationPrincipal si disponible

    Retourne un dict standardisé :
    {
        "disponible": True,
        "circuits": [
            {
                "circuit_id": "CTH-001",
                "nom": "Carthage + Sidi Bou Saïd",
                "score_global": 0.87,
                "duree_minutes": 240,
                "prix_dt": 35,
                "type": "culturel",
                "outdoor": True,
                "description": "...",
                "explication": "Correspond à votre budget famille...",
                "conseil_meteo": "",
            }
        ],
        "nb_total": 3,
        "profil_utilise": {...},     ← pour le prompt de synthèse
        "manquants": ["budget"],     ← signaux absents qui auraient aidé
        "erreur": None
    }
    """

    def __init__(self, systeme_recommandation=None):
        self._systeme = systeme_recommandation
        self._agent = None  # AgentRecommandationPrincipal (enrichissement)
        self._available = True

    # ─────────────────────────────────────────────────────────────────────────
    # INIT LAZY
    # ─────────────────────────────────────────────────────────────────────────

    def _get_agent_enrichisseur(self):
        """
        Lazy init de AgentRecommandationPrincipal.
        Optionnel — si indisponible, on retourne les résultats bruts du calculateur.
        """
        if self._agent is None and self._available and self._systeme is not None:
            try:
                AgentClass = _import_circuit_agent()
                if AgentClass is None:
                    self._available = False
                    return None
                self._agent = AgentClass(self._systeme)
                log.info("[CIRCUITS] AgentRecommandationPrincipal initialisé")
            except Exception as e:
                log.error(f"[CIRCUITS] Erreur init agent enrichisseur : {e}")
                self._available = False
        return self._agent

    def set_systeme(self, systeme) -> None:
        """Injecte le système de recommandation après init."""
        self._systeme = systeme
        self._agent = None
        self._available = True
        log.info("[CIRCUITS] Système de recommandation injecté")

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTHODE PRINCIPALE
    # ─────────────────────────────────────────────────────────────────────────

    async def get_recommendations(
        self,
        user_id: str,
        signals: dict,
        n: int = 3,
        meteo_data: Optional[dict] = None,
        profil_override: Optional[ProfilSynthetique] = None,
    ) -> dict:
        """
        Obtient les recommandations de circuits depuis les signaux du message.

        Bypasse get_client() — aucun client en base requis.

        Args:
            user_id:     ID session (non utilisé pour la DB, juste pour les logs)
            signals:     Signaux extraits du message (budget, groupe, durée, lieu...)
            n:           Nombre de circuits souhaités
            meteo_data:  Données météo brutes (optionnel, pour réordonner outdoor/indoor)

        Returns:
            Dict standardisé avec circuits recommandés
        """
        if self._systeme is None:
            log.warning("[CIRCUITS] Aucun système fourni — fallback hardcodé")
            return self._fallback_response()

        # ── Étape 1 : Construire (ou récupérer) le profil synthétique ─────
        if profil_override is not None:
            profil = profil_override
        else:
            profil = ProfilSynthetique.depuis_signaux(signals)
        suffisant, manquants = profil.est_suffisant_pour_recommandation()

        log.info(f"[CIRCUITS] Profil synthétique : {profil}")
        if manquants:
            log.info(f"[CIRCUITS] Signaux manquants : {manquants}")

        try:
            # ── Étape 2 : Appel direct au calculateur (bypass get_client) ─
            result_brut = await asyncio.to_thread(
                self._appel_calculateur_direct,
                profil,
                n * 2,  # On demande le double pour avoir de la marge
            )

            if not result_brut:
                return self._fallback_response(
                    erreur="calculateur_vide", manquants=manquants
                )

            # ── Étape 3 : Enrichissement avec AgentRecommandationPrincipal ─
            # (optionnel — adaptation saisonnière, similaires, feedbacks)
            circuits_enrichis = await asyncio.to_thread(
                self._enrichir_avec_agent,
                result_brut,
                profil,
            )

            # ── Étape 4 : Normalisation format standardisé ────────────────
            circuits = self._normaliser(
                circuits_enrichis, meteo_data, tarif=profil.type_tarif
            )

            # ── Étape 5 : Réordonner selon météo ─────────────────────────
            circuits = self._reorder_for_weather(circuits, meteo_data)

            return {
                "disponible": True,
                "response": "",
                "error": None,
                "payload": {
                    "_raw": {
                        "circuits": circuits[:n],
                        "nb_total": len(result_brut),
                        "profil_utilise": profil.to_dict(),
                        "manquants": manquants,
                    }
                },
            }

        except asyncio.TimeoutError:
            log.warning("[CIRCUITS] Timeout")
            return self._fallback_response(erreur="timeout", manquants=manquants)
        except Exception as e:
            log.error(f"[CIRCUITS] Erreur inattendue : {e}", exc_info=True)
            return self._fallback_response(erreur=str(e), manquants=manquants)

    # ─────────────────────────────────────────────────────────────────────────
    # APPEL DIRECT AU CALCULATEUR (synchrone, dans asyncio.to_thread)
    # ─────────────────────────────────────────────────────────────────────────

    def _appel_calculateur_direct(
        self,
        profil: ProfilSynthetique,
        n: int,
    ) -> list:
        """
        Bypasse get_client() et recommander_pour_client().
        Appelle directement systeme.calculateur.recommander(profil=profil).

        Returns:
            Liste brute de résultats calculer_pertinence()
        """
        try:
            # Accéder au calculateur PertinenceCalculator
            calculateur = getattr(self._systeme, "calculateur", None)
            if calculateur is None:
                log.error("[CIRCUITS] systeme.calculateur introuvable")
                return []

            # Appel direct — ProfilSynthetique duck-typing compatible
            recommandations = calculateur.recommander(
                profil=profil,
                n_recommandations=n,
                exclure_ids=[],  # Nouveau visiteur : rien à exclure
            )

            log.info(
                f"[CIRCUITS] {len(recommandations)} circuits calculés par pertinence"
            )
            return recommandations

        except Exception as e:
            log.error(f"[CIRCUITS] Erreur calculateur direct : {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # ENRICHISSEMENT AVEC AgentRecommandationPrincipal (optionnel)
    # ─────────────────────────────────────────────────────────────────────────

    def _enrichir_avec_agent(
        self,
        circuits_bruts: list,
        profil: ProfilSynthetique,
    ) -> list:
        """
        Enrichit les résultats bruts du calculateur avec les agents spécialisés
        (adaptation saisonnière, circuits similaires, feedbacks récents).

        Si AgentRecommandationPrincipal n'est pas disponible → retourne les bruts.
        """
        agent = self._get_agent_enrichisseur()
        if agent is None:
            log.info(
                "[CIRCUITS] Pas d'enrichissement agent (non disponible) — résultats bruts"
            )
            return circuits_bruts

        try:
            enrichis = []
            saison = agent._get_saison_actuelle()

            for rec in circuits_bruts:
                circuit_id = rec.get("circuit_id", "")

                # Circuits similaires (AgentCircuit)
                similaires = []
                try:
                    similaires = agent.agent_circuit.suggerer_circuit_similaire(
                        circuit_id, n=2
                    )
                except Exception:
                    pass

                # Adaptation saisonnière
                adaptation = agent._adapter_a_la_saison(rec, saison)

                # Feedbacks récents
                feedbacks = agent._check_feedbacks_recents(circuit_id)

                # Catégorie
                categorie = agent._trouver_categorie_circuit(circuit_id)

                rec_enrichi = {
                    **rec,
                    "metadonnees_agents": {
                        "similaires": similaires,
                        "adaptation_saison": adaptation,
                        "feedbacks_recents": feedbacks,
                        "categorie": categorie,
                    },
                }

                # Score agent (compatibilité profil + saison + feedbacks)
                # Note : _calculer_score_agent() attend un objet client avec getattr —
                # ProfilSynthetique est duck-typing compatible
                try:
                    rec_enrichi["score_agent"] = agent._calculer_score_agent(
                        rec_enrichi, profil, {"saison": saison}
                    )
                    # Recalcul score global (moyenne score calculateur + score agent)
                    rec_enrichi["score_global"] = round(
                        (rec.get("score_global", 0.5) + rec_enrichi["score_agent"]) / 2,
                        3,
                    )
                except Exception as e:
                    log.debug(
                        f"[CIRCUITS] Calcul score agent échoué pour {circuit_id} : {e}"
                    )
                    rec_enrichi["score_agent"] = rec.get("score_global", 0.5)

                enrichis.append(rec_enrichi)

            # Re-trier après enrichissement
            enrichis.sort(key=lambda x: x["score_global"], reverse=True)
            log.info(
                f"[CIRCUITS] Enrichissement agent terminé ({len(enrichis)} circuits)"
            )
            return enrichis

        except Exception as e:
            log.warning(
                f"[CIRCUITS] Erreur enrichissement agent : {e} — retour résultats bruts"
            )
            return circuits_bruts

    # ─────────────────────────────────────────────────────────────────────────
    # NORMALISATION FORMAT STANDARDISÉ
    # ─────────────────────────────────────────────────────────────────────────

    def _circuits_brut(self) -> list:
        calculateur = getattr(self._systeme, "calculateur", None)
        return list(getattr(calculateur, "circuits", []) or [])

    def _normaliser(
        self,
        circuits_raw: list,
        meteo_data: Optional[dict],
        tarif: str = "etranger",
    ) -> list:
        """
        Normalise les résultats vers le format attendu par l'orchestrateur.
        Fusionne avec les données complètes du circuit (monuments, tarifs, durée).
        """
        normalized = []
        circuits_brut = self._circuits_brut()

        for rec in circuits_raw:
            merged = fusionner_avec_circuits_bruts(rec, circuits_brut)
            circuit_id = merged.get("circuit_id", "")
            meta = merged.get("metadonnees_agents", rec.get("metadonnees_agents", {}))
            categorie = meta.get("categorie", "")
            outdoor = categorie in ("nature", "plage", "culturel_outdoor", "ruines", "")
            monuments = merged.get("noms", merged.get("monuments", []))
            if not isinstance(monuments, list):
                monuments = []
            duree_raw = merged.get("duree_totale", merged.get("duree", 0))
            prix = prix_pour_tarif(merged, tarif)

            circuit = {
                "circuit_id": circuit_id,
                "nom": merged.get("nom") or _id_to_nom(circuit_id),
                "score_global": round(merged.get("score_global", 0.5), 3),
                "score_agent": round(
                    merged.get("score_agent", merged.get("score_global", 0.5)), 3
                ),
                "duree_minutes": int(float(duree_raw or 0)),
                "duree_totale": duree_raw,
                "prix_dt": prix,
                "prix": prix,
                "type": merged.get("type_dominant", categorie or "culturel"),
                "outdoor": outdoor,
                "categorie": categorie,
                "description": merged.get("description", ""),
                "monuments": monuments,
                "noms": monuments,
                "explication": _generer_explication(merged, meta),
                "score_details": merged.get("details", {}),
                "similaires": meta.get("similaires", []),
                "feedbacks": meta.get("feedbacks_recents", {}),
                "conseil_meteo": "",
                "donnees_completes": merged,
            }
            normalized.append(circuit)

        return normalized

    # ─────────────────────────────────────────────────────────────────────────
    # RÉORDONNAGE MÉTÉO
    # ─────────────────────────────────────────────────────────────────────────

    def _reorder_for_weather(self, circuits: list, meteo_data: Optional[dict]) -> list:
        """
        Si mauvais temps : circuits indoor en premier, outdoor en dernier.
        Ne supprime jamais un circuit.
        """
        if not meteo_data or not meteo_data.get("disponible"):
            return circuits

        alerte = meteo_data.get("donnees_brutes", {}).get("alerte", {})
        outdoor_ok = alerte.get("outdoor_ok", True)

        if outdoor_ok:
            return circuits

        indoor = [c for c in circuits if not c.get("outdoor", True)]
        outdoor = [c for c in circuits if c.get("outdoor", True)]
        log.info(
            f"[CIRCUITS] Réordonnage météo : {len(indoor)} indoor avant {len(outdoor)} outdoor"
        )
        return indoor + outdoor

    # ─────────────────────────────────────────────────────────────────────────
    # FALLBACK
    # ─────────────────────────────────────────────────────────────────────────

    def _fallback_response(
        self,
        erreur: Optional[str] = None,
        manquants: Optional[list] = None,
    ) -> dict:
        """Circuits hardcodés quand le moteur math est indisponible."""
        return {
            "disponible": False,
            "response": "",
            "error": erreur or "service_indisponible",
            "payload": {
                "_raw": {
                    "circuits": _get_fallback_circuits(),
                    "nb_total": 0,
                    "profil_utilise": {},
                    "manquants": manquants or [],
                }
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _id_to_nom(circuit_id: str) -> str:
    """Génère un nom lisible depuis l'ID si le circuit n'a pas de nom."""
    mapping = {
        "CTH": "Carthage",
        "MED": "Médina de Tunis",
        "BAR": "Musée du Bardo",
        "SBS": "Sidi Bou Saïd",
        "ELJ": "El Jem",
        "DGG": "Dougga",
        "KAI": "Kairouan",
        "TOZ": "Tozeur",
    }
    prefix = circuit_id[:3].upper() if circuit_id else ""
    base = mapping.get(prefix, circuit_id)
    return base


def _generer_explication(rec: dict, meta: dict) -> str:
    """
    Génère une explication courte et humaine pour le prompt de synthèse.
    Utilisée par _synthesize_response() pour construire le contexte agents.
    """
    parties = []

    score = rec.get("score_global", 0)
    if score >= 0.8:
        parties.append("Excellent match")
    elif score >= 0.65:
        parties.append("Bon match")
    else:
        parties.append("Circuit disponible")

    details = rec.get("details", {})
    if details.get("budget", 0) >= 0.8:
        parties.append("dans le budget")
    if details.get("duree", 0) >= 0.8:
        parties.append("durée adaptée")

    adaptation = meta.get("adaptation_saison", {})
    if adaptation.get("pertinence_saison") == "forte":
        parties.append(adaptation.get("message", ""))

    feedbacks = meta.get("feedbacks_recents", {})
    moyenne = feedbacks.get("moyenne")
    if moyenne and moyenne >= 4.0:
        parties.append(f"très apprécié ({moyenne:.1f}/5)")

    return " · ".join(p for p in parties if p)


def _get_fallback_circuits() -> list:
    """Circuits par défaut quand le moteur math n'est pas disponible."""
    return [
        {
            "circuit_id": "MEDINA-001",
            "nom": "Médina de Tunis — Cœur historique",
            "score_global": 0.85,
            "duree_minutes": 180,
            "prix_dt": 25,
            "type": "culturel",
            "outdoor": False,
            "description": "Souks, zaouïas, la Grande Mosquée Zitouna — le labyrinthe vivant de Tunis",
            "explication": "Circuit indoor, idéal par toute météo",
            "conseil_meteo": "",
        },
        {
            "circuit_id": "CARTHAGE-001",
            "nom": "Carthage + Sidi Bou Saïd",
            "score_global": 0.82,
            "duree_minutes": 240,
            "prix_dt": 40,
            "type": "culturel_outdoor",
            "outdoor": True,
            "description": "Ruines puniques et romaines, expérience AR, village bleu-blanc de Sidi Bou Saïd",
            "explication": "Circuit phare de la startup",
            "conseil_meteo": "",
        },
        {
            "circuit_id": "BARDO-001",
            "nom": "Musée National du Bardo",
            "score_global": 0.79,
            "duree_minutes": 150,
            "prix_dt": 20,
            "type": "musee",
            "outdoor": False,
            "description": "La plus grande collection de mosaïques romaines au monde",
            "explication": "Parfait par temps de pluie",
            "conseil_meteo": "",
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

_circuits_wrapper_instance: Optional[AgentCircuitsWrapper] = None


def get_circuits_wrapper(systeme=None) -> AgentCircuitsWrapper:
    """Retourne l'instance singleton du wrapper circuits."""
    global _circuits_wrapper_instance
    if _circuits_wrapper_instance is None:
        _circuits_wrapper_instance = AgentCircuitsWrapper(systeme)
    elif systeme and _circuits_wrapper_instance._systeme is None:
        _circuits_wrapper_instance.set_systeme(systeme)
    return _circuits_wrapper_instance
