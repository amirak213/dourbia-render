"""
output_guard.py

Module de guardrails de SORTIE pour Dourbia.
Détecte les dérives du chatbot (hallucination, langage inapproprié, hors-sujet)
en post-traitement déterministe, après génération de la réponse.

Deux niveaux :
- Niveau 1 (générique) : applicable à TOUS les agents du chatbot.
- Niveau 2 (RAG) : applicable uniquement à AgentHistorique, nécessite des
  chunks source pour vérifier le grounding factuel.

Ne bloque rien par défaut : retourne des flags à exploiter en aval.
Zéro appel LLM supplémentaire — réutilise l'embedding déjà en cache
(_encode_cached, mutualisé avec AgentHistorique).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np


# ---------------------------------------------------------------------------
# NIVEAU 1a — Langage inapproprié (FR / EN / AR) — générique, tous agents
# ---------------------------------------------------------------------------

# Liste basique et extensible. À compléter selon les besoins réels observés.
MOTS_INTERDITS_FR = [
    "merde",
    "putain",
    "connard",
    "connasse",
    "salope",
    "enculé",
    "pute",
    "bordel de merde",
    "nique",
]

MOTS_INTERDITS_EN = [
    "fuck",
    "shit",
    "bitch",
    "asshole",
    "bastard",
    "cunt",
    "dick",
]

# TODO (Amira) : à compléter/valider — liste de mots-clés arabe standard.
# Placeholder minimal, à ne pas considérer comme couverture suffisante.
MOTS_INTERDITS_AR = [
    "كلب",  # exemple générique, à revoir
]

_PATTERN_LANGAGE = re.compile(
    r"(?:\b(?:"
    + "|".join(re.escape(m) for m in MOTS_INTERDITS_FR + MOTS_INTERDITS_EN)
    + r")\b)"
    r"|(?:" + "|".join(re.escape(m) for m in MOTS_INTERDITS_AR) + r")",
    re.IGNORECASE | re.UNICODE,
)


def _detect_langage_inapproprie(texte: str) -> tuple[bool, list[str]]:
    """
    Détecte la présence de langage inapproprié en FR/EN/AR par regex.
    Ne cherche pas à identifier la langue : applique les 3 listes,
    un texte propre dans une langue ne matchera pas les patterns des autres.
    """
    matches = _PATTERN_LANGAGE.findall(texte)
    termes_uniques = sorted(set(m.lower() for m in matches if m))
    return (len(termes_uniques) > 0, termes_uniques)


# ---------------------------------------------------------------------------
# NIVEAU 1b — Détection hors-sujet — générique, tous agents
# ---------------------------------------------------------------------------

# Corpus de référence multilingue représentant le domaine
# "tourisme et histoire de Carthage / La Marsa / Tunisie".
# Volontairement large (pas juste histoire) pour couvrir aussi les agents
# circuit/réservation/guidage, pas seulement AgentHistorique.
CORPUS_REFERENCE_DOMAINE = [
    # Français
    "Carthage est un site archéologique majeur fondé par les Phéniciens en Tunisie.",
    "La Marsa est une station balnéaire prisée près de Tunis avec ses plages et cafés.",
    "Les thermes d'Antonin à Carthage sont parmi les plus grands thermes romains du monde antique.",
    "Un circuit touristique permet de visiter plusieurs monuments historiques en une journée.",
    "Le tarif d'entrée au site archéologique dépend du statut du visiteur, étudiant ou résident.",
    "Sidi Bou Said est un village pittoresque connu pour son architecture bleue et blanche.",
    "Vous pouvez réserver votre visite guidée directement en ligne pour la date souhaitée.",
    "Le mode guide GPS vous signale les monuments à proximité pendant votre parcours.",
    # English
    "Carthage was an ancient Phoenician city that became a major Roman settlement in Tunisia.",
    "La Marsa is a coastal suburb near Tunis known for its beaches and cafes.",
    "Visitors can book a guided tour to explore the historical monuments of the region.",
    "The archaeological site offers different ticket prices depending on visitor category.",
    # Arabe
    "قرطاج مدينة أثرية قديمة أسسها الفينيقيون في تونس.",
    "المرسى ضاحية ساحلية قريبة من تونس العاصمة تشتهر بشواطئها ومقاهيها.",
    "يمكن للزوار حجز جولة سياحية لاكتشاف المعالم التاريخية في المنطقة.",
    "سعر تذكرة الدخول إلى الموقع الأثري يختلف حسب فئة الزائر.",
]

SEUIL_HORS_SUJET_DEFAUT = 0.35


@lru_cache(maxsize=1)
def _corpus_centroid(embedding_model) -> np.ndarray:
    """
    Calcule et met en cache le centroïde (moyenne normalisée) des embeddings
    du corpus de référence. Calculé une seule fois au premier appel.

    Note : embedding_model doit exposer une méthode .encode(str) -> array-like,
    conforme à l'interface SentenceTransformer déjà utilisée dans orchestrateur.py.
    """
    embeddings = [
        np.array(embedding_model.encode(phrase)) for phrase in CORPUS_REFERENCE_DOMAINE
    ]
    matrice = np.vstack(embeddings)
    centroid = matrice.mean(axis=0)
    return centroid / np.linalg.norm(centroid)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _detect_hors_sujet(
    reponse: str,
    question: str,
    embedding_model,
    seuil: float = SEUIL_HORS_SUJET_DEFAUT,
) -> tuple[bool, float]:
    """
    Compare l'embedding de (question + réponse) au centroïde du corpus
    de référence du domaine. Sous le seuil -> flag hors-sujet.
    """
    texte_combine = f"{question} {reponse}".strip()
    embedding = np.array(embedding_model.encode(texte_combine))
    centroid = _corpus_centroid(embedding_model)
    score = _cosine_sim(embedding, centroid)
    return (score < seuil, round(score, 4))


# ---------------------------------------------------------------------------
# NIVEAU 2 — Grounding check contre les chunks RAG — AgentHistorique uniquement
# ---------------------------------------------------------------------------

_PATTERN_ANNEE = re.compile(
    r"\b(1[0-9]{3}|2[0-9]{3}|[0-9]{1,2}(?:er)?\s+(?:siècle|century|قرن))\b",
    re.IGNORECASE,
)
_PATTERN_NOMBRE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:DT|TND|km|m|%|dinars?)?\b")
_PATTERN_NOM_PROPRE = re.compile(
    r"\b[A-ZÀ-Ý][a-zà-ÿ'-]{2,}(?:\s+[A-ZÀ-Ý][a-zà-ÿ'-]{2,})*\b"
)

_STOPWORDS_DEBUT = {
    "Le",
    "La",
    "Les",
    "Un",
    "Une",
    "Des",
    "Ce",
    "Cette",
    "Ces",
    "Il",
    "Elle",
    "Ils",
    "Elles",
    "Vous",
    "Nous",
    "Je",
    "Tu",
}


def _normaliser(texte: str) -> str:
    """Minuscule + suppression des accents pour comparaison robuste."""
    texte = texte.lower()
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return texte


_PATTERN_FRONTIERE_PHRASE = re.compile(
    r"(?:^|[.!?]\s+)([A-ZÀ-Ý][a-zà-ÿ'-]{2,}(?:\s+[A-ZÀ-Ý][a-zà-ÿ'-]{2,})*)"
)


def _positions_debut_phrase(texte: str) -> set[str]:
    """
    Retourne l'ensemble des candidats 'nom propre' qui apparaissent
    en tout début de phrase (donc capitalisés par simple grammaire,
    pas parce que ce sont des noms propres).
    """
    return {m.group(1) for m in _PATTERN_FRONTIERE_PHRASE.finditer(texte)}


def _extraire_faits(texte: str) -> list[str]:
    """
    Extraction grossière de 'faits vérifiables' : dates, nombres, noms propres.
    Volontairement simple (regex, pas de NER) — objectif : signal, pas preuve.

    Un candidat nom propre capitalisé n'est retenu que s'il apparaît AU MOINS
    UNE FOIS ailleurs qu'en tout début de phrase — ça élimine mécaniquement
    les mots capitalisés par simple règle grammaticale (ex: "Cependant, ...",
    "Bienvenue à ...") sans avoir à maintenir une liste de connecteurs.
    """
    faits = set()

    faits.update(_PATTERN_ANNEE.findall(texte))
    faits.update(m.strip() for m in _PATTERN_NOMBRE.findall(texte) if m.strip())

    candidats_debut_phrase = _positions_debut_phrase(texte)
    tous_candidats = _PATTERN_NOM_PROPRE.findall(texte)

    for candidat in tous_candidats:
        premier_mot = candidat.split()[0]
        if premier_mot in _STOPWORDS_DEBUT and len(candidat.split()) == 1:
            continue
        # Rejeter si CE candidat n'apparaît QUE comme mot de début de phrase
        # (c'est-à-dire jamais ailleurs dans le texte)
        occurrences_totales = len(re.findall(re.escape(candidat), texte))
        est_uniquement_debut_phrase = (
            candidat in candidats_debut_phrase and occurrences_totales <= 1
        )
        if est_uniquement_debut_phrase:
            continue
        faits.add(candidat)

    return sorted(faits)


def _extraire_titre(source) -> str:
    """
    Extrait le titre d'une source, qu'elle soit un dict ({'title': ...})
    ou un objet (SourceRef.title). Retourne '' si introuvable.
    """
    if isinstance(source, dict):
        return str(source.get("title") or "")
    return str(getattr(source, "title", "") or "")

def _extraire_chunk_text(source) -> str:
    """
    Extrait le texte du chunk d'une source, qu'elle soit un dict
    ({'chunk_text': ...}) ou un objet. Retourne '' si introuvable
    (ex: source web, ou ancien format sans chunk_text).
    """
    if isinstance(source, dict):
        return str(source.get("chunk_text") or "")
    return str(getattr(source, "chunk_text", "") or "")

def _detect_hallucination(reponse: str, sources: list) -> tuple[bool, list[str]]:
    """
        Grounding check : vérifie que les faits vérifiables (noms propres, dates,
        chiffres) mentionnés dans la réponse sont présents dans le texte des
        chunks sources (chunk_text) ou, à défaut, dans leurs titres.
    
        Si une source n'a pas de chunk_text (ex: fallback web, ancien format),
        seul son titre sert de référence pour elle — grounding partiel dans ce cas,
        signal plus faible pour les faits qui ne reposent que sur des sources web.

        Si sources est vide, on ne peut rien vérifier -> pas de flag (évite faux positifs).
    """

    if not sources:
        return (False, [])

    tous_faits = _extraire_faits(reponse)
    if not tous_faits:
        return (False, [])

    texte_verification = " ".join(
        _normaliser(_extraire_titre(s)) + " " + _normaliser(_extraire_chunk_text(s))
        for s in sources
    )

    faits_non_verifies = [
        fait for fait in tous_faits 
        if _normaliser(fait) not in texte_verification
    ]

    seuil_ratio = 0.7
    min_faits_non_verifies = 3
    ratio_non_verifie = len(faits_non_verifies) / len(tous_faits)
    hallucination = (
        ratio_non_verifie >= seuil_ratio
        and len(faits_non_verifies) >= min_faits_non_verifies
    )

    return (hallucination, faits_non_verifies)


# ---------------------------------------------------------------------------
# Résultat structuré
# ---------------------------------------------------------------------------


@dataclass
class OutputGuardResult:
    langage_inapproprie: bool = False
    termes_detectes: list[str] = field(default_factory=list)

    hors_sujet: bool = False
    score_similarite_domaine: float = 0.0

    hallucination_potentielle: bool = False
    faits_non_verifies: list[str] = field(default_factory=list)

    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Points d'entrée publics
# ---------------------------------------------------------------------------


def check_output_generic(
    reponse: str,
    question_originale: str,
    embedding_model,
    seuil_hors_sujet: float = SEUIL_HORS_SUJET_DEFAUT,
) -> OutputGuardResult:
    """
    Check Niveau 1 uniquement (langage inapproprié + hors-sujet).
    Applicable à TOUS les agents du chatbot.

    Args:
        reponse: texte généré par l'agent, à vérifier.
        question_originale: question de l'utilisateur.
        embedding_model: modèle avec méthode .encode(str), fourni par l'appelant
                          (ex: self._embedding_model dans orchestrateur.py).
        seuil_hors_sujet: seuil de similarité cosinus configurable.
    """
    langage_flag, termes = _detect_langage_inapproprie(reponse)
    hors_sujet_flag, score_sim = _detect_hors_sujet(
        reponse, question_originale, embedding_model, seuil_hors_sujet
    )

    return OutputGuardResult(
        langage_inapproprie=langage_flag,
        termes_detectes=termes,
        hors_sujet=hors_sujet_flag,
        score_similarite_domaine=score_sim,
        details={
            "niveau": "generique",
            "seuil_hors_sujet_utilise": seuil_hors_sujet,
        },
    )


def check_output_rag(
    reponse: str,
    sources: list,
    question_originale: str,
    embedding_model,
    seuil_hors_sujet: float = SEUIL_HORS_SUJET_DEFAUT,
) -> OutputGuardResult:
    """
    Check Niveau 1 + Niveau 2 (grounding sur chunk_text + titres des sources).
    Spécifique à AgentHistorique.

    
    """

    resultat = check_output_generic(
        reponse, question_originale, embedding_model, seuil_hors_sujet
    )

    hallu_flag, faits_kos = _detect_hallucination(reponse, sources)
    resultat.hallucination_potentielle = hallu_flag
    resultat.faits_non_verifies = faits_kos
    resultat.details["niveau"] = "rag_degrade"
    resultat.details["nb_sources"] = len(sources)

    return resultat
