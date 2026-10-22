from __future__ import annotations
import asyncio, json, logging, re, unicodedata
from datetime import date as _date
from typing import Optional
from core.config import settings
from core.types import ClientProfile, IntentionClient

log = logging.getLogger("dourbia.planning")

_CONFIRMATION_WORDS = frozenset({
    "oui", "yes", "ok", "okay", "confirm", "confirme", "confirmé", "confirmee",
    "d'accord", "daccord", "accord", "valide", "validate", "yep", "yeah", "correct",
})

def is_reservation_confirmation(message: str) -> bool:
    msg = message.lower().strip().rstrip("!.?").replace("'", "'")
    if len(msg.split()) > 3:
        return False
    return msg in _CONFIRMATION_WORDS


def history_has_reservation_recap(history: list) -> bool:
    for msg in reversed(history or []):
        if msg.get("role") != "assistant":
            continue
        content = (msg.get("content") or "").lower()
        markers = (
            "confirmez-vous", "répondez 'oui'", "repondez 'oui'",
            "voici ce que je vais réserver", "confirm?", "reply 'yes'",
        )
        if any(m in content for m in markers):
            return True
    return False

_INTENTION_PROMPT = """Classifie le message dans UNE catégorie :
decouverte|recherche|reservation|annulation|suivi|meteo|faq|inconnu
JSON: {{"intention":"...","confidence":0.0-1.0}}
Message: "{message}" """

async def detect_intention(message: str, groq_client) -> tuple[IntentionClient, float]:
    msg_lower = message.lower()
    heuristics = {
        IntentionClient.ANNULATION: ["annul","cancel","supprimer ma réservation"],
        IntentionClient.SUIVI:      ["mes réservations","mon dossier","statut","res-"],
        IntentionClient.METEO:      ["météo","meteo","weather","temps qu'il fait"],
        IntentionClient.RESERVATION:["je veux réserver","réserver la","book","prendre la voiture"],
        IntentionClient.RECHERCHE:  ["voiture","cherche","louer","disponible","trouver","besoin d'une"],
    }
    for intention, keywords in heuristics.items():
        if any(kw in msg_lower for kw in keywords):
            return intention, 0.85
    try:
        resp = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model=settings.groq_model_fast, max_tokens=60, temperature=0,
            response_format={"type":"json_object"},
            messages=[{"role":"user","content":_INTENTION_PROMPT.format(message=message[:300])}])
        raw = json.loads(resp.choices[0].message.content)
        try: return IntentionClient(raw.get("intention","inconnu")), float(raw.get("confidence",0.5))
        except: return IntentionClient.INCONNU, 0.3
    except Exception as e:
        log.debug(f"[PLANNING] detect_intention : {e}")
        return IntentionClient.INCONNU, 0.3

_EXTRACT_PROMPT = """Extrait les infos du message. JSON uniquement, null si absent.
Dates: YYYY-MM-DD. Année: {year}. Budget: nombre seul.
Catégorie: Economique|Confort|Familiale|Luxe|Desert/Sahari|Electrique|Utilitaire
Message: "{message}"
JSON: {{"client_nom":null,"client_tel":null,"client_email":null,"ville_preferee":null,
"budget_max":null,"categorie_pref":null,"nb_places_min":null,"transmission":null,
"climatisation":null,"dates_debut":null,"dates_fin":null}}"""

async def extract_profile(message: str, groq_client) -> Optional[ClientProfile]:
    try:
        resp = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model=settings.groq_model_fast, max_tokens=300, temperature=0,
            response_format={"type":"json_object"},
            messages=[{"role":"user","content":_EXTRACT_PROMPT.format(
                message=message[:400], year=_date.today().year)}])
        data = {k:v for k,v in json.loads(resp.choices[0].message.content).items() if v is not None}
        return ClientProfile(**data) if data else None
    except Exception as e:
        log.debug(f"[PLANNING] extract_profile : {e}"); return None

class TaskPlan:
    def __init__(self, intention, needs_search=False, needs_reservation=False,
                 missing_fields=None, pre_fetch_tools=None,
                 known_ville=None, known_dates=None):
        self.intention = intention
        self.needs_search = needs_search
        self.needs_reservation = needs_reservation
        self.missing_fields = missing_fields or []
        self.pre_fetch_tools = pre_fetch_tools or []
        self.known_ville = known_ville
        self.known_dates = known_dates

# ──────────────────────────────────────────────────────────────
# VILLES RECONNUES (normalisées) — utilisées uniquement pour
# normaliser la casse, pas pour filtrer.
# ──────────────────────────────────────────────────────────────
VILLES_DB = [
    "tunis", "sfax", "sousse", "nabeul", "hammamet", "djerba",
    "monastir", "bizerte", "kairouan", "gabes", "gabès",
    "mahdia", "gafsa", "tataouine", "tozeur", "medenine",
    "beja", "jendouba", "kef", "siliana", "zaghouan", "ariana",
    "manouba", "ben arous", "la marsa", "sidi bouzid", "kasserine",
]

_LOCATION_KEYWORDS = [
    "à ", "a ", "sur ", "pour ", "vers ", "dans ", "en ", "autour de ",
    "région de ", "ville de ", "côté de ",
]

_STOPWORDS = {
    "voiture","voitures","location","auto","car","vous","nous","moi",
    "une","un","le","la","les","ma","mon","mes","quel","quelle",
}

def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode("ascii")

def _extract_ville_from_message(msg_lower: str, profil: dict) -> Optional[str]:
    """
    Cherche une ville dans le message OU dans le profil mémorisé.

    Stratégie :
    1. Profil DB en priorité (déjà validé par l'utilisateur).
    2. Correspondance exacte dans VILLES_DB (insensible aux accents).
    3. Heuristique libre : nom propre qui suit un mot-clé de localisation.
       Accepte n'importe quelle ville — pas seulement celles de la liste.
    """
    if profil.get("ville_preferee"):
        return profil["ville_preferee"]

    msg_norm = _norm(msg_lower)

    # Correspondance dans la liste connue
    for v in VILLES_DB:
        if _norm(v) in msg_norm:
            return v.capitalize()

    # Heuristique libre : "à Mahdia", "pour Rades", "dans Gafsa", etc.
    for kw in _LOCATION_KEYWORDS:
        pattern = re.escape(kw) + r"([A-ZÀ-Ö][a-zà-ö]+(?:\s[A-ZÀ-Ö][a-zà-ö]+)?)"
        match = re.search(pattern, msg_lower, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate.lower() not in _STOPWORDS and len(candidate) >= 3:
                return candidate.capitalize()

    return None


def build_task_plan(intention, profil, message):
    """
    Construit le plan d'exécution.

    CORRECTION BUG CRITIQUE : les dates sont lues depuis profil qui est
    déjà le profil FUSIONNÉ (DB + message courant) — donc dates_debut
    et dates_fin du message courant sont bien présentes ici.
    """
    msg_lower = message.lower()

    if intention == IntentionClient.RESERVATION:
        missing = [f for f, k in [
            ("nom", "client_nom"), ("téléphone", "client_tel"), ("email", "client_email")
        ] if not profil.get(k)]
        return TaskPlan(intention=intention, needs_reservation=True, missing_fields=missing)

    if intention in (IntentionClient.RECHERCHE, IntentionClient.DECOUVERTE):
        ville = _extract_ville_from_message(msg_lower, profil)

        # Dates : lues depuis le profil FUSIONNÉ (inclut le message courant)
        dates_debut = profil.get("dates_debut")
        dates_fin   = profil.get("dates_fin")
        dates_ok = bool(dates_debut)

        categorie_ok = bool(profil.get("categorie_pref") or profil.get("budget_max"))

        missing = []
        if not ville:
            missing.append("ville")
        if not dates_ok:
            missing.append("dates")
        # FIX BUG 1 : catégorie/budget est OBLIGATOIRE — 3 questions avant toute recherche.
        # On ne lance la recherche que si les 3 infos sont présentes OU si le client
        # répond vaguement ("peu importe", "non", etc.) — géré côté FOCUS dans le prompt.
        if not categorie_ok:
            missing.append("categorie_ou_budget")

        if missing:
            return TaskPlan(
                intention=IntentionClient.DECOUVERTE,
                needs_search=False,
                missing_fields=missing,
                known_ville=ville,
                known_dates=dates_debut,
            )

        return TaskPlan(
            intention=IntentionClient.RECHERCHE,
            needs_search=True,
            known_ville=ville,
            known_dates=dates_debut,
        )

    if intention == IntentionClient.SUIVI:
        return TaskPlan(intention=intention, pre_fetch_tools=["consulter_reservations"])

    # INCONNU ou FAQ : ne pas bloquer, laisser le modèle répondre librement
    return TaskPlan(intention=intention)


def build_focused_system_prompt(base_prompt, plan, episodic_context, lessons_context, profil_context):
    sections = [base_prompt]
    if lessons_context:
        sections.append(lessons_context)
    if episodic_context:
        sections.append(episodic_context)
    elif profil_context:
        sections.append(profil_context)

    if plan.needs_reservation and not plan.missing_fields:
        sections.append(
            "[FOCUS CRITIQUE] Le client confirme le récapitulatif. "
            "Tu DOIS appeler reserver_voiture IMMÉDIATEMENT avec les données du récap "
            "(voiture_id, client_nom, client_tel, client_email, date_debut, date_fin). "
            "INTERDIT d'écrire une confirmation sans appeler l'outil. "
            "Utilise le reservation_id RÉEL retourné par l'outil — jamais le placeholder RES-XXXXXX."
        )
    elif plan.intention == IntentionClient.RESERVATION and plan.missing_fields:
        sections.append(
            f"[FOCUS] Collecter dans cet ordre : {' → '.join(plan.missing_fields)}. "
            f"Un seul champ à la fois, de façon naturelle et chaleureuse."
        )

    elif plan.intention == IntentionClient.RECHERCHE and not plan.missing_fields:
        ville_hint = f" ville='{plan.known_ville}'" if plan.known_ville else ""
        date_hint  = f" date_debut='{plan.known_dates}'" if plan.known_dates else ""
        sections.append(
            f"[FOCUS] Appelle rechercher_avec_fallback_scraping IMMÉDIATEMENT."
            f" Paramètres extraits :{ville_hint}{date_hint}."
            f" N'attends PAS d'autres infos. Propose les résultats directement."
        )

    elif plan.intention == IntentionClient.DECOUVERTE and plan.missing_fields:
        if "ville" in plan.missing_fields:
            focus_msg = (
                "[FOCUS] Tu ne connais pas encore la ville. "
                "Pose UNE seule question naturelle et chaleureuse pour la connaître. "
                "Exemple : 'Vous avez une ville en tête ?' ou 'C'est pour quelle ville ?'. "
                "N'appelle AUCUN tool. Ne propose PAS de voitures."
            )
        elif "dates" in plan.missing_fields:
            ville_connue = plan.known_ville or "cette ville"
            focus_msg = (
                f"[FOCUS] Tu connais la ville ({ville_connue}) mais pas les dates. "
                "Pose UNE question naturelle pour les dates de location. "
                "Exemple : 'C'est pour quelles dates ?' ou 'Vous partez quand ?'. "
                "N'appelle AUCUN tool. Ne propose PAS de voitures sans dates."
            )
        elif "categorie_ou_budget" in plan.missing_fields:
            ville_connue = plan.known_ville or "cette ville"
            focus_msg = (
                f"[FOCUS] Tu connais la ville ({ville_connue}) et les dates. "
                "C'est la dernière question avant de chercher. "
                "Pose UNE question naturelle sur la catégorie ou le budget. "
                "Exemple : 'Vous avez une préférence ? Économique, confort, SUV... ou un budget max par jour ?' "
                "IMPORTANT : si le client dit 'peu importe', 'non', 'pas de préférence', 'surprise-moi', "
                "ou répond vaguement → n'insiste pas, appelle immédiatement rechercher_avec_fallback_scraping "
                "avec les infos connues, sans budget ni catégorie. "
                "N'appelle AUCUN tool si le client n'a pas encore répondu à cette question."
            )
        else:
            focus_msg = (
                "[FOCUS] Il manque des informations. "
                "Pose une question naturelle pour compléter, une à la fois."
            )
        sections.append(focus_msg)

    # INCONNU/FAQ : ajouter un FOCUS générique pour éviter comportement imprévisible
    elif plan.intention in (IntentionClient.INCONNU, IntentionClient.FAQ):
        sections.append(
            "[FOCUS] Le message n'est pas clairement lié à une recherche de voiture. "
            "Réponds de façon naturelle et chaleureuse. Si tu peux aider autrement, propose-le. "
            "Si le client semble vouloir louer, pose une question pour comprendre son besoin."
        )

    return "\n\n".join(sections)
