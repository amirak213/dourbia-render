"""
onboarding.py — Probing interactif (8 questions) pour construire un ProfilSynthetique
et déclencher une recommandation de circuit.
"""

import asyncio
import json
import logging
import re
from groq import Groq

from constants import (
    GROQ_API_KEY,
    MODEL_FAST,
    AGENT_TIMEOUT_SECONDS,
    SYSTEM_EXTRACTION_PROBING,
    CHAMPS_COLLECTE_CIRCUIT,
    get_questions_probing,
    INTRO_PROBING_BY_LANG,
    MSG_PROBING_INCOMPRIS,
    MSG_PROBING_RECAP_INTRO,
    MSG_PROBING_PREPARE,
)
from profil_synthetique import ProfilSynthetique

log = logging.getLogger("chatbot.onboarding")

_groq = Groq(api_key=GROQ_API_KEY)

_EPOQUES_VALEURS = frozenset(
    {"romaine", "islamique", "punique", "ottomane", "moderne", "prehistorique"}
)
_EPOQUES_ALIASES = {
    "roman": "romaine", "islamic": "islamique", "punic": "punique",
    "ottoman": "ottomane", "modern": "moderne", "prehistoric": "prehistorique",
}
_TYPES_ALIASES = {
    "cultural": "culturel", "religious": "religieux", "historical": "historique",
    "family": "familial", "family-friendly": "familial", "adventure": "aventure",
}
_TYPES_VALEURS = frozenset(
    {"culturel", "nature", "religieux", "historique", "familial", "aventure"}
)
_TARIFS_VALEURS = frozenset(
    {"resident", "etudiant", "etranger", "enseignant", "retraite", "enfant"}
)
_TRANSPORT_VALEURS = frozenset({"a_pied", "velo", "voiture", "autre"})


_TARIF_ALIASES = {
    "résident": "resident",
    "resident": "resident",
    "tunisien": "resident",
    "étudiant": "etudiant",
    "etudiant": "etudiant",
    "étranger": "etranger",
    "etranger": "etranger",
    "enseignant": "enseignant",
    "retraité": "retraite",
    "retraite": "retraite",
    "enfant": "enfant",
}


def detect_tarif(message: str) -> str | None:
    """Détecte une catégorie tarifaire explicite dans un texte utilisateur."""
    msg = (message or "").lower().strip()
    for alias, tarif in _TARIF_ALIASES.items():
        if alias in msg:
            return tarif
    if msg in _TARIFS_VALEURS:
        return msg
    return None


def _parse_json_robuste(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    depth, start = 0, None
    for i, ch in enumerate(raw):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    break
    return {}


def _champ_rempli(profil_collecte: dict, champ: str) -> bool:
    val = profil_collecte.get(champ)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (list, dict)):
        return bool(val)
    return True


def champs_manquants(profil_collecte: dict) -> list[str]:
    """Retourne les champs de collecte encore vides, dans l'ordre imposé."""
    return [c for c in CHAMPS_COLLECTE_CIRCUIT if not _champ_rempli(profil_collecte, c)]


def _question_pour_champ(champ: str, profil_collecte: dict, langue: str = "FR") -> str:
    questions = get_questions_probing(langue)
    if champ == "transport" and profil_collecte.get("mobilite") == "reduite":
        if langue == "EN":
            return (
                "What mode of transport do you prefer?\n"
                "Given your reduced mobility, adapted options are:\n"
                "  • car\n  • other PMR-adapted transport"
            )
        return (
            "Quel mode de transport préférez-vous ?\n"
            "Compte tenu de votre mobilité réduite, les options adaptées sont :\n"
            "  • voiture\n  • autre transport adapté PMR"
        )
    return questions[champ]


def _parser_champ_local(champ: str, message: str) -> object | None:
    """Parse déterministe de la réponse utilisateur pour le champ attendu."""
    msg = message.strip().lower()
    if not msg:
        return None

    if champ == "destination":
        if msg in _EPOQUES_VALEURS or msg in _TYPES_VALEURS:
            return None
        if msg in _TARIFS_VALEURS or msg in {"normale", "reduite", "réduite"}:
            return None
        return message.strip()

    if champ == "epoques":
        found = [e for e in _EPOQUES_VALEURS if e in msg]
        for alias, canonical in _EPOQUES_ALIASES.items():
            if alias in msg and canonical not in found:
                found.append(canonical)
        return found or None

    if champ == "types":
        found = [t for t in _TYPES_VALEURS if t in msg]
        for alias, canonical in _TYPES_ALIASES.items():
            if alias in msg and canonical not in found:
                found.append(canonical)
        return found or None

    if champ == "mobilite":
        if any(w in msg for w in ("réduit", "reduit", "pmr", "handicap", "fauteuil")):
            return "reduite"
        if "normal" in msg:
            return "normale"
        return None

    if champ == "duree":
        hm = re.search(r"(\d+)\s*h\s*(\d+)?", msg)
        if hm:
            h = int(hm.group(1))
            m = int(hm.group(2) or 0)
            return f"{h}h{m:02d}" if m else f"{h}h"
        mm = re.search(r"(\d+)\s*(?:min|minutes?)", msg)
        if mm:
            return mm.group(1)
        if re.fullmatch(r"\d+", msg):
            return msg
        return None

    if champ == "transport":
        if any(w in msg for w in ("à pied", "a pied", "pied", "marche", "marcher")):
            return "a_pied"
        if any(w in msg for w in ("vélo", "velo", "bike", "bicyclette")):
            return "velo"
        if any(w in msg for w in ("voiture", "auto", "taxi", "motorisé", "motorise")):
            return "voiture"
        if "autre" in msg:
            return "autre"
        return None

    if champ == "budget":
        m = re.search(r"(\d+(?:\.\d+)?)", msg)
        if m:
            return int(float(m.group(1)))
        return None

    if champ == "tarif":
        return detect_tarif(msg)

    return None


def _en_liste_str(valeur: object) -> list[str] | None:
    if isinstance(valeur, str):
        items = [v.strip() for v in valeur.replace(",", " ").split() if v.strip()]
        return items or None
    if isinstance(valeur, list):
        items = [str(v).strip() for v in valeur if v is not None and str(v).strip()]
        return items or None
    return None


def _normaliser_valeur_champ(champ: str, valeur: object) -> object | None:
    if valeur in (None, "", [], {}):
        return None

    if champ == "epoques":
        items = _en_liste_str(valeur)
        if not items:
            return None
        return [e.lower() for e in items if e.lower() in _EPOQUES_VALEURS] or None

    if champ == "types":
        items = _en_liste_str(valeur)
        if not items:
            return None
        return [t.lower() for t in items if t.lower() in _TYPES_VALEURS] or None

    if champ == "mobilite":
        v = str(valeur).lower().strip()
        return v if v in {"reduite", "normale"} else None

    if champ == "transport":
        v = str(valeur).lower().strip()
        return v if v in _TRANSPORT_VALEURS else None

    if champ == "tarif":
        v = str(valeur).lower().strip()
        if v in {"résident", "réduit"}:
            v = "resident"
        return v if v in _TARIFS_VALEURS else None

    if champ == "budget":
        if isinstance(valeur, (int, float)):
            return int(valeur)
        m = re.search(r"(\d+(?:\.\d+)?)", str(valeur))
        return int(float(m.group(1))) if m else None

    if champ == "destination":
        dest = str(valeur).strip()
        return dest or None

    if champ == "duree":
        return str(valeur).strip() or None

    return valeur


async def extraire_entites_probing(message: str, champ_attendu: str) -> dict:
    prompt_champ = (
        f'\n\nExtrais UNIQUEMENT le champ "{champ_attendu}" du message ci-dessous. '
        "Ne devine aucune autre valeur. Si le champ n'est pas présent → {}"
    )
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _groq.chat.completions.create,
                model=MODEL_FAST,
                max_tokens=300,
                temperature=0.0,
                reasoning_effort="low",
                messages=[
                    {"role": "system", "content": SYSTEM_EXTRACTION_PROBING + prompt_champ},
                    {"role": "user", "content": message},
                ],
            ),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        raw = (response.choices[0].message.content or "").strip()
        entites = _parse_json_robuste(raw)
        return {k: v for k, v in entites.items() if k == champ_attendu}
    except Exception as e:
        log.warning(f"[ONBOARDING] Extraction échouée ({champ_attendu}) : {e}")
        return {}


def _enregistrer_reponse(
    profil_collecte: dict, champ_attendu: str, message: str, entites_llm: dict
) -> bool:
    """Enregistre la réponse pour le champ attendu. Retourne True si le champ est rempli."""
    valeur = _parser_champ_local(champ_attendu, message)
    if valeur is None and champ_attendu in entites_llm:
        valeur = entites_llm[champ_attendu]

    valeur = _normaliser_valeur_champ(champ_attendu, valeur)
    if valeur is None:
        return False

    profil_collecte[champ_attendu] = valeur
    return True


async def premiere_question(langue: str) -> tuple[str, list]:
    """Pose la première des 8 questions (aligné sur stage_AI_agentique--master)."""
    intro = INTRO_PROBING_BY_LANG.get(langue, INTRO_PROBING_BY_LANG["FR"])
    questions = get_questions_probing(langue)
    question = intro + questions["destination"]
    return question, [{"role": "assistant", "content": question}]


async def step(
    historique_probing: list, profil_collecte: dict, user_message: str, langue: str
) -> dict:
    """
    Exécute une étape du probing.
    Returns:
        {"reponse": str, "complete": bool, "profil_collecte": dict, "historique": list}
    """
    manquants_avant = champs_manquants(profil_collecte)
    if not manquants_avant:
        reponse = _generer_recap_profil(profil_collecte, langue)
        historique_probing = historique_probing + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reponse},
        ]
        return {
            "reponse": reponse,
            "complete": True,
            "profil_collecte": profil_collecte,
            "historique": historique_probing,
        }

    champ_attendu = manquants_avant[0]
    entites = await extraire_entites_probing(user_message, champ_attendu)
    enregistre = _enregistrer_reponse(
        profil_collecte, champ_attendu, user_message, entites
    )

    historique_probing = historique_probing + [
        {"role": "user", "content": user_message}
    ]

    manquants = champs_manquants(profil_collecte)
    if not manquants:
        reponse = _generer_recap_profil(profil_collecte, langue)
        historique_probing = historique_probing + [
            {"role": "assistant", "content": reponse}
        ]
        return {
            "reponse": reponse,
            "complete": True,
            "profil_collecte": profil_collecte,
            "historique": historique_probing,
        }

    if not enregistre:
        incompris = MSG_PROBING_INCOMPRIS.get(langue, MSG_PROBING_INCOMPRIS["FR"])
        reponse = (
            f"{incompris}"
            f"{_question_pour_champ(champ_attendu, profil_collecte, langue)}"
        )
    else:
        reponse = _question_pour_champ(manquants[0], profil_collecte, langue)

    historique_probing = historique_probing + [
        {"role": "assistant", "content": reponse}
    ]

    return {
        "reponse": reponse,
        "complete": False,
        "profil_collecte": profil_collecte,
        "historique": historique_probing,
    }


def _generer_recap_profil(profil_collecte: dict, langue: str = "FR") -> str:
    """Résumé structuré affiché à l'utilisateur à la fin du probing."""
    epoques = profil_collecte.get("epoques", [])
    if isinstance(epoques, list):
        epoques_str = ", ".join(epoques) if epoques else "non précisées"
    else:
        epoques_str = str(epoques)

    types = profil_collecte.get("types", [])
    if isinstance(types, list):
        types_str = ", ".join(types) if types else "non précisés"
    else:
        types_str = str(types)

    if langue == "EN":
        return (
            f"{MSG_PROBING_RECAP_INTRO['EN']}"
            f"- Destination: {profil_collecte.get('destination', '?')}\n"
            f"- Historical periods: {epoques_str}\n"
            f"- Site types: {types_str}\n"
            f"- Mobility: {profil_collecte.get('mobilite', '?')}\n"
            f"- Duration: {profil_collecte.get('duree', '?')}\n"
            f"- Transport: {profil_collecte.get('transport', '?')}\n"
            f"- Budget: {profil_collecte.get('budget', '?')} DT\n"
            f"- Pricing category: {profil_collecte.get('tarif', '?')}\n\n"
            f"{MSG_PROBING_PREPARE['EN']}"
        )

    intro = MSG_PROBING_RECAP_INTRO.get(langue, MSG_PROBING_RECAP_INTRO["FR"])
    prepare = MSG_PROBING_PREPARE.get(langue, MSG_PROBING_PREPARE["FR"])
    return (
        f"{intro}"
        f"- Destination : {profil_collecte.get('destination', '?')}\n"
        f"- Époques : {epoques_str}\n"
        f"- Types de sites : {types_str}\n"
        f"- Mobilité : {profil_collecte.get('mobilite', '?')}\n"
        f"- Durée : {profil_collecte.get('duree', '?')}\n"
        f"- Transport : {profil_collecte.get('transport', '?')}\n"
        f"- Budget : {profil_collecte.get('budget', '?')} DT\n"
        f"- Situation tarifaire : {profil_collecte.get('tarif', '?')}\n\n"
        f"{prepare}"
    )


def construire_profil_final(profil_collecte: dict) -> ProfilSynthetique:
    return ProfilSynthetique.depuis_collecte(profil_collecte)
