"""
profil_synthetique.py — Profil visiteur construit à la volée depuis les signaux du message.

Bypasse complètement get_client() / la table `clients`.
Utilisé par AgentCircuitsWrapper pour appeler calculateur.recommander()
sans nécessiter un client enregistré en base PostgreSQL.

Attributs lus par PertinenceCalculator.calculer_pertinence() :
    - preference_epoque   → calculer_score_thematique()
    - types_preferes      → calculer_score_type()
    - duree_max           → calculer_score_duree()
    - budget_max          → calculer_score_budget()
    - type_tarif          → calculer_score_budget() (mapping tarif)

Tous ont des fallbacks neutres dans PertinenceCalculator —
un attribut None/absent donne un score de 0.5 à 0.7, pas un crash.
"""

from __future__ import annotations
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# MAPPING SIGNAUX → ATTRIBUTS PROFIL
# ─────────────────────────────────────────────────────────────────────────────

# Mapping type_groupe → type_tarif PostgreSQL
_TYPE_GROUPE_TO_TARIF = {
    "famille": "resident",
    "couple": "resident",
    "solo": "resident",
    "groupe": "resident",
    # Cas spéciaux détectables plus tard si besoin
    "etudiant": "etudiant",
    "scolaire": "etudiant",
    "retraite": "retraite",
    "etranger": "etranger",
}

# Mapping type_activite → types_preferes (vocabulaire PertinenceCalculator)
_ACTIVITE_TO_TYPES = {
    "historique": ["historique", "culturel", "archeologie"],
    "musee": ["musee", "culturel"],
    "ar_vr": ["technologie", "culturel", "historique"],
    "nature": ["nature", "plage"],
    "culturel": ["culturel", "historique"],
}

# Mapping type_activite → preference_epoque
_ACTIVITE_TO_EPOQUE = {
    "historique": ["antiquite", "punique", "romain"],
    "musee": ["antiquite", "medieval", "moderne"],
    "ar_vr": ["antiquite", "moderne"],
    "nature": [],
    "culturel": ["medieval", "ottoman", "moderne"],
}

# Mapping duree (string signal) → duree_max en minutes
_DUREE_TO_MINUTES = {
    "demi-journée": 180,
    "journée": 480,
    "week-end": 960,
}


# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PROFIL SYNTHÉTIQUE
# ─────────────────────────────────────────────────────────────────────────────


class ProfilSynthetique:
    """
    Objet profil compatible avec PertinenceCalculator, construit depuis
    les signaux extraits du message utilisateur.

    Pas de requête PostgreSQL, pas de client en base.
    Compatible duck-typing avec les objets Client de db.py.

    Usage :
        profil = ProfilSynthetique.depuis_signaux(signaux)
        recommandations = calculateur.recommander(profil=profil, n_recommandations=3)
    """

    def __init__(
        self,
        budget_max: Optional[float] = None,
        duree_max: Optional[int] = None,
        types_preferes: Optional[list] = None,
        preference_epoque: Optional[list] = None,
        type_tarif: str = "resident",
        taille_groupe: Optional[int] = None,
        type_groupe: Optional[str] = None,
        lieu: Optional[str] = None,
    ):
        # Attributs lus par PertinenceCalculator
        self.budget_max = budget_max  # float DT (None = pas de contrainte)
        self.duree_max = duree_max  # int minutes (None = pas de contrainte)
        self.types_preferes = types_preferes or []
        self.preference_epoque = preference_epoque or []
        self.type_tarif = type_tarif  # 'resident', 'etranger', 'etudiant'...

        # Attributs supplémentaires (utilisés par AgentRecommandationPrincipal)
        self.taille_groupe = taille_groupe
        self.type_groupe = type_groupe
        self.lieu = lieu

        # Compatibilité avec get_client() / recommander_pour_client()
        # Ces attributs évitent les AttributeError si le code existant y accède
        self.id = "visiteur_temp"
        self.user_id = "visiteur_temp"
        self.historique_circuits = []  # Pas d'exclusions pour un nouveau visiteur

    # ─────────────────────────────────────────────────────────────────────────
    # FACTORY METHOD PRINCIPALE
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def depuis_signaux(cls, signaux: dict) -> "ProfilSynthetique":
        """
        Construit un ProfilSynthetique depuis les signaux extraits
        par OrchestratorAgent._extract_profile_signals().

        Args:
            signaux: {
                "budget": 150,
                "taille_groupe": 4,
                "type_groupe": "famille",
                "duree": "journée",
                "lieu": "Carthage",
                "type_activite": "historique",
                "outdoor_detected": True,
            }

        Returns:
            ProfilSynthetique prêt pour calculateur.recommander()
        """
        # ── Budget ────────────────────────────────────────────────────────
        budget_raw = signaux.get("budget")
        budget_max = float(budget_raw) if budget_raw else None

        # Si budget total pour groupe → diviser par taille groupe
        taille = signaux.get("taille_groupe")
        if budget_max and taille and taille > 1:
            budget_max = budget_max / taille

        # ── Durée → minutes ───────────────────────────────────────────────
        duree_str = signaux.get("duree", "")
        duree_max = None
        if duree_str in _DUREE_TO_MINUTES:
            duree_max = _DUREE_TO_MINUTES[duree_str]
        elif duree_str and "jour" in duree_str:
            # Ex: "3 jours" → extraire le nombre
            try:
                nb = int(duree_str.split()[0])
                duree_max = nb * 480  # 8h par jour
            except (ValueError, IndexError):
                pass

        # ── Type tarif ────────────────────────────────────────────────────
        type_groupe = signaux.get("type_groupe", "")
        type_tarif = _TYPE_GROUPE_TO_TARIF.get(type_groupe, "resident")

        # ── Types préférés ────────────────────────────────────────────────
        type_activite = signaux.get("type_activite", "")
        types_preferes = _ACTIVITE_TO_TYPES.get(type_activite, [])

        # Enrichissement depuis le lieu détecté
        lieu = signaux.get("lieu", "")
        if lieu:
            lieu_lower = lieu.lower()
            if any(
                h in lieu_lower for h in ["carthage", "dougga", "sbeitla", "el jem"]
            ):
                if "historique" not in types_preferes:
                    types_preferes = ["historique", "culturel"] + types_preferes
            elif "bardo" in lieu_lower:
                if "musee" not in types_preferes:
                    types_preferes = ["musee", "culturel"] + types_preferes

        # ── Époque préférée ───────────────────────────────────────────────
        preference_epoque = _ACTIVITE_TO_EPOQUE.get(type_activite, [])

        return cls(
            budget_max=budget_max,
            duree_max=duree_max,
            types_preferes=types_preferes,
            preference_epoque=preference_epoque,
            type_tarif=type_tarif,
            taille_groupe=taille,
            type_groupe=type_groupe,
            lieu=lieu,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # FACTORY METHOD DEPUIS COLLECTE PROBING (8 questions)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def depuis_collecte(cls, collecte: dict) -> "ProfilSynthetique":
        """
        Construit un ProfilSynthetique depuis les 8 champs collectés
        par le probing interactif de l'orchestrateur.
        Args:
            collecte: {
                "destination": "Tunis",
                "epoques": ["romaine", "punique"],
                "types": ["culturel", "historique"],
                "mobilite": "normale",
                "duree": "3h",        # ou "180", "3h30", "demi-journée"
                "transport": "voiture",
                "budget": 100,         # ou "100", "100 DT"
                "tarif": "etranger",
            }
        Returns:
            ProfilSynthetique prêt pour calculateur.recommander()
        """
        import re as _re
        # ── Budget ────────────────────────────────────────────────────────
        budget_raw = collecte.get("budget")
        budget_max = None
        if budget_raw is not None:
            if isinstance(budget_raw, (int, float)):
                budget_max = float(budget_raw)
            elif isinstance(budget_raw, str):
                m = _re.search(r'(\d+(?:\.\d+)?)', str(budget_raw))
                if m:
                    budget_max = float(m.group(1))
        # ── Durée → minutes ───────────────────────────────────────────────
        duree_raw = collecte.get("duree", "")
        duree_max = None
        if isinstance(duree_raw, (int, float)):
            duree_max = int(duree_raw)
        elif isinstance(duree_raw, str):
            d = duree_raw.lower().strip()
            if d in _DUREE_TO_MINUTES:
                duree_max = _DUREE_TO_MINUTES[d]
            else:
                # Parse "3h", "3h30", "2h00"
                hm = _re.match(r'(\d+)\s*h\s*(\d+)?', d)
                if hm:
                    h = int(hm.group(1))
                    m = int(hm.group(2) or 0)
                    duree_max = h * 60 + m
                else:
                    # Parse "180 min", "180", "180min"
                    mm = _re.match(r'(\d+)\s*(?:min|minutes?)?$', d)
                    if mm:
                        duree_max = int(mm.group(1))
        # ── Type tarif ────────────────────────────────────────────────────
        tarif_raw = collecte.get("tarif", "etranger")
        if isinstance(tarif_raw, str):
            tarif_raw = tarif_raw.lower().strip()
        type_tarif = _TYPE_GROUPE_TO_TARIF.get(tarif_raw, tarif_raw)
        # Normalize to valid values
        tarifs_valides = {"resident", "etranger", "etudiant", "enseignant", "retraite", "enfant"}
        if type_tarif not in tarifs_valides:
            type_tarif = "etranger"
        # ── Types préférés ────────────────────────────────────────────────
        types_raw = collecte.get("types", [])
        if isinstance(types_raw, str):
            types_raw = [t.strip() for t in types_raw.replace(",", " ").split() if t.strip()]
        types_preferes = []
        for t in types_raw:
            mapped = _ACTIVITE_TO_TYPES.get(t.lower(), [t.lower()])
            for m in mapped:
                if m not in types_preferes:
                    types_preferes.append(m)
        # ── Époque préférée ───────────────────────────────────────────────
        epoques_raw = collecte.get("epoques", [])
        if isinstance(epoques_raw, str):
            epoques_raw = [e.strip() for e in epoques_raw.replace(",", " ").split() if e.strip()]
        preference_epoque = [e.lower() for e in epoques_raw]
        # ── Lieu ──────────────────────────────────────────────────────────
        lieu = collecte.get("destination", "")
        return cls(
            budget_max=budget_max,
            duree_max=duree_max,
            types_preferes=types_preferes,
            preference_epoque=preference_epoque,
            type_tarif=type_tarif,
            taille_groupe=None,
            type_groupe=None,
            lieu=lieu,
        )
    # ─────────────────────────────────────────────────────────────────────────
    # FUSION AVEC SIGNAUX SUPPLÉMENTAIRES
    # ─────────────────────────────────────────────────────────────────────────

    def enrichir(self, signaux_nouveaux: dict) -> "ProfilSynthetique":
        """
        Retourne un nouveau profil enrichi avec des signaux supplémentaires.
        Utilisé quand l'orchestrateur collecte des informations progressivement
        sur plusieurs tours de conversation.

        Non-destructif : retourne un nouveau profil, ne modifie pas self.
        """
        signaux_fusionnes = {
            "budget": (
                self.budget_max * (self.taille_groupe or 1) if self.budget_max else None
            ),
            "taille_groupe": self.taille_groupe,
            "type_groupe": self.type_groupe,
            "duree": self._minutes_to_duree_str(self.duree_max),
            "lieu": self.lieu,
        }
        # Les nouveaux signaux écrasent les anciens si fournis
        signaux_fusionnes.update(
            {k: v for k, v in signaux_nouveaux.items() if v is not None}
        )
        return ProfilSynthetique.depuis_signaux(signaux_fusionnes)

    def _minutes_to_duree_str(self, minutes: Optional[int]) -> Optional[str]:
        if not minutes:
            return None
        if minutes <= 180:
            return "demi-journée"
        if minutes <= 480:
            return "journée"
        return "week-end"

    # ─────────────────────────────────────────────────────────────────────────
    # DIAGNOSTIC
    # ─────────────────────────────────────────────────────────────────────────

    def est_suffisant_pour_recommandation(self) -> tuple[bool, list[str]]:
        """
        Vérifie si le profil a assez d'infos pour une recommandation pertinente.

        Returns:
            (suffisant: bool, champs_manquants: list[str])
        """
        manquants = []

        # Budget est le critère le plus impactant (poids 0.15 mais éliminatoire si dépassé)
        if not self.budget_max:
            manquants.append("budget")

        # Durée affecte fortement le score (poids 0.20)
        if not self.duree_max:
            manquants.append("duree")

        # Avec budget + durée on peut déjà recommander
        suffisant = len(manquants) <= 1

        return suffisant, manquants

    def to_dict(self) -> dict:
        """Sérialisation pour logs et session_memory."""
        return {
            "budget_max": self.budget_max,
            "duree_max": self.duree_max,
            "types_preferes": self.types_preferes,
            "preference_epoque": self.preference_epoque,
            "type_tarif": self.type_tarif,
            "taille_groupe": self.taille_groupe,
            "type_groupe": self.type_groupe,
            "lieu": self.lieu,
        }

    def __repr__(self) -> str:
        return (
            f"ProfilSynthetique("
            f"budget={self.budget_max}DT, "
            f"duree={self.duree_max}min, "
            f"groupe={self.type_groupe}×{self.taille_groupe}, "
            f"tarif={self.type_tarif}, "
            f"types={self.types_preferes})"
        )
