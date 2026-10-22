"""
circuit_presentation.py — Affichage des circuits comme l'agent circuit (stage_AI_agentique).

Reproduit print_circuit_card + generer_explication en texte brut pour le CLI master.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Callable, Optional

from constants import (
    PATH_CIRCUIT_AGENT,
    GROQ_API_KEY,
    MODEL_SMART,
    AGENT_TIMEOUT_SECONDS,
)
from groq import Groq

log = logging.getLogger("chatbot.circuit_presentation")

_groq = Groq(api_key=GROQ_API_KEY)

_MAPPING_COUT = {
    "resident": "cout_resident",
    "résident": "cout_resident",
    "etudiant": "cout_etudiant",
    "étudiant": "cout_etudiant",
    "etranger": "cout_etranger",
    "étranger": "cout_etranger",
    "enseignant": "cout_enseignant",
    "retraite": "cout_retraite",
    "retraité": "cout_retraite",
    "enfant": "cout_enfant",
}

SYSTEM_EXPLICATION_CIRCUITS = """\
Tu es un guide touristique expert, passionné et chaleureux, spécialisé en Tunisie.
Tu présentes des recommandations de circuits en français, de façon naturelle et convaincante.
Pour chaque circuit : 2-3 phrases. Mets en avant l'expérience vécue, pas les chiffres.
Commence par une phrase d'accroche personnalisée selon le profil du visiteur."""


def _ensure_circuit_path():
    if PATH_CIRCUIT_AGENT not in sys.path:
        sys.path.insert(0, PATH_CIRCUIT_AGENT)


def _charger_distances() -> Optional[Callable]:
    try:
        _ensure_circuit_path()
        from db import charger_distances_circuit  # type: ignore

        return charger_distances_circuit
    except Exception as e:
        log.debug(f"[PRESENTATION] Distances indisponibles : {e}")
        return None


def fusionner_avec_circuits_bruts(rec: dict, circuits_brut: list) -> dict:
    """Jointure scoring + données complètes du circuit (comme chat.py mode_nouveau_client)."""
    cid = rec.get("circuit_id", "")
    full = next(
        (c for c in circuits_brut if c.get("circuit_id") == cid),
        {},
    )
    return {**full, **rec}


def prix_pour_tarif(circuit: dict, tarif: str) -> float:
    col = _MAPPING_COUT.get((tarif or "etranger").lower(), "cout_etranger")
    prix = circuit.get(col)
    if prix is not None:
        try:
            return float(prix)
        except (TypeError, ValueError):
            pass

    tarifs = circuit.get("tarifs") or circuit.get("cout_par_categorie") or {}
    if isinstance(tarifs, dict):
        cle = (tarif or "etranger").lower()
        if cle in tarifs:
            return float(tarifs[cle])
        if "etranger" in tarifs:
            return float(tarifs["etranger"])

    return float(circuit.get("prix", circuit.get("prix_dt", 0)) or 0)


def _nom_circuit(circuit: dict) -> str:
    nom = circuit.get("nom")
    if nom and nom != circuit.get("circuit_id"):
        return str(nom)
    monuments = circuit.get("monuments") or circuit.get("noms") or []
    if isinstance(monuments, list) and monuments:
        if len(monuments) <= 2:
            return " · ".join(str(m) for m in monuments)
        return f"{monuments[0]} · {monuments[1]} (+{len(monuments) - 2})"
    return circuit.get("circuit_id", "Circuit")


def formater_carte_circuit(
    circuit: dict,
    rank: int,
    score: float,
    transport: str = "voiture",
    tarif: str = "etranger",
    charger_distances=None,
) -> str:
    """Version texte de print_circuit_card (stage_AI_agentique/chat.py)."""
    lignes = [f"\n  ┌─ #{rank} " + "─" * 50]
    nom = _nom_circuit(circuit)
    lignes.append(f"  │ 🗺  {nom}")

    duree = circuit.get("duree_totale", circuit.get("duree", circuit.get("duree_minutes", "?")))
    if isinstance(duree, float):
        duree = f"{duree:.0f}"
    prix = prix_pour_tarif(circuit, tarif)
    lignes.append(
        f"  │ ⏱  Durée : {duree} min  |  💰 Prix : {prix:.0f} DT  |  ⭐ Score : {score:.0%}"
    )

    monuments = circuit.get("monuments") or circuit.get("noms") or []
    if isinstance(monuments, list) and monuments:
        extrait = monuments[:3]
        suite = f" + {len(monuments) - 3} autres" if len(monuments) > 3 else ""
        lignes.append(f"  │ 🏛  {', '.join(str(m) for m in extrait)}{suite}")

    if isinstance(monuments, list) and len(monuments) >= 2 and charger_distances:
        transport_norm = (transport or "voiture").lower()
        if transport_norm in ("a_pied", "à pied", "marche", "pied"):
            col_duree = "duree_pied_min"
            icone = "🚶"
        elif transport_norm in ("velo", "vélo", "bicyclette", "bike"):
            col_duree = "duree_velo_min"
            icone = "🚴"
        else:
            col_duree = "duree_voiture_min"
            icone = "🚗"

        try:
            distances = charger_distances(monuments)
        except Exception:
            distances = []

        if distances:
            lignes.append(f"  │   {icone} Itinéraire :")
            for d in distances:
                f_lieu = d.get("from_lieu", "?")
                t_lieu = d.get("to_lieu", "?")
                dist_km = d.get("distance_km")
                duree_t = d.get(col_duree)
                dist_str = f"{dist_km} km" if dist_km is not None else "? km"
                duree_str = f"{duree_t} min" if duree_t is not None else "? min"
                lignes.append(f"  │     {f_lieu} → {t_lieu}  ({dist_str}, {duree_str})")

    lignes.append("  └" + "─" * 55)
    return "\n".join(lignes)


def _resume_profil(profil_collecte: dict) -> str:
    epoques = profil_collecte.get("epoques", [])
    if isinstance(epoques, list):
        epoques_str = " et ".join(epoques) if epoques else "variées"
    else:
        epoques_str = str(epoques) if epoques else "variées"

    return (
        f"Visiteur souhaitant découvrir {profil_collecte.get('destination') or 'la Tunisie'}, "
        f"passionné par {epoques_str}, mobilité {profil_collecte.get('mobilite', 'normale')}, "
        f"transport {profil_collecte.get('transport', 'voiture')}, "
        f"budget {profil_collecte.get('budget', '?')} DT, "
        f"durée max {profil_collecte.get('duree', '?')}"
    )


async def generer_explication_circuits(
    profil_collecte: dict,
    circuits: list[dict],
    tarif: str = "etranger",
) -> str:
    """Génère la présentation narrative LLM (comme generer_explication dans chat.py)."""
    if not circuits:
        return ""

    col_prix = _MAPPING_COUT.get((tarif or "etranger").lower(), "cout_etranger")
    circuits_txt = "\n".join(
        [
            f"Circuit {i + 1} — {_nom_circuit(c)} : "
            f"durée {c.get('duree_totale', c.get('duree', c.get('duree_minutes', '?')))} min, "
            f"prix {prix_pour_tarif(c, tarif):.0f} DT, "
            f"monuments : {', '.join(str(m) for m in (c.get('monuments') or c.get('noms') or [])[:4])}"
            for i, c in enumerate(circuits)
        ]
    )
    prompt = (
        f"Profil : {_resume_profil(profil_collecte)}\n\n"
        f"Circuits recommandés :\n{circuits_txt}\n\n"
        "Présente ces circuits de façon personnalisée et enthousiaste."
    )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _groq.chat.completions.create,
                model=MODEL_SMART,
                max_tokens=700,
                reasoning_effort="low",
                include_reasoning=False,
                temperature=0.75,
                messages=[
                    {"role": "system", "content": SYSTEM_EXPLICATION_CIRCUITS},
                    {"role": "user", "content": prompt},
                ],
            ),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        if response.choices[0].finish_reason == "length":
            log.warning("[PRESENTATION] Réponse tronquée (finish_reason=length)")
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning(f"[PRESENTATION] Explication LLM échouée : {e}")
        return ""


async def presenter_recommandations(
    recs: list[tuple[dict, float]],
    profil_collecte: dict,
    tarif: str = "etranger",
    transport: str = "voiture",
) -> str:
    """
    Assemble cartes détaillées + explication LLM + relance.
    recs : liste de (circuit_dict_complet, score)
    """
    if not recs:
        return "Je n'ai pas trouvé de circuit correspondant pour le moment."

    charger_distances = _charger_distances()
    parties = ["\n── Recommandations personnalisées " + "─" * 30]

    for i, (circuit, score) in enumerate(recs, 1):
        parties.append(
            formater_carte_circuit(
                circuit,
                i,
                score,
                transport=transport,
                tarif=tarif,
                charger_distances=charger_distances,
            )
        )

    explication = await generer_explication_circuits(profil_collecte, [c for c, _ in recs], tarif)
    if explication:
        parties.append(f"\n{explication}")

    parties.append(
        "\nCes circuits vous intéressent ? Vous pouvez :\n"
        '  • préciser une préférence (ex: "je préfère un budget de 80 DT")\n'
        '  • demander des détails (ex: "parle-moi du circuit 2")\n'
        "  • continuer à explorer d'autres sujets"
    )
    return "\n".join(parties)
