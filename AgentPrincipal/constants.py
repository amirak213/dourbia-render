"""
constants.py — Constantes globales du chatbot touristique tunisien.

Contient : config Groq, routing table, system prompts, few-shot examples.
"""

import os
import re
from dotenv import load_dotenv

# Charge d'abord le fichier global
load_dotenv(r"E:\claude\.env")
# Charge ensuite le local (s'il en reste un)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY_PRINCIPAL", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "qwen/qwen3.8-27b")
MODEL_SMART = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Timeout en secondes pour chaque appel agent
AGENT_TIMEOUT_SECONDS = 50

# Taille de la fenêtre glissante de l'historique (nb d'échanges = paires user/assistant)
HISTORY_WINDOW = 6

# Seuil de confiance minimum pour router sans demander clarification
INTENT_CONFIDENCE_THRESHOLD = 0.6

# ─────────────────────────────────────────────────────────────────────────────
# ROUTING TABLE
# ─────────────────────────────────────────────────────────────────────────────

ROUTING_TABLE = {
    "HISTORIQUE": ["agent_guide"],
    "CIRCUIT": ["agent_circuits", "moteur_math"],
    "RESERVATION": ["agent_reservation"],
    "PRATIQUE": ["agent_guide"],
    "SMALLTALK": ["orchestrateur"],
    "FEEDBACK": ["agent_feedback_math"],
    "METEO": ["agent_meteo"],
    "TERRAIN": ["agent_guide"],
}

# Intentions valides
INTENTIONS_VALIDES = list(ROUTING_TABLE.keys())

# ─────────────────────────────────────────────────────────────────────────────
# LIEUX TUNISIENS — pour détection de signaux météo outdoor
# ─────────────────────────────────────────────────────────────────────────────

LIEUX_OUTDOOR = {
    "carthage", "sidi bou saïd", "sidi bou said", "el jem", "dougga",
    "sbeitla", "kerkouane", "hammamet", "nabeul", "monastir", "mahdia",
    "kairouan", "tozeur", "douz", "matmata", "tataouine", "chenini",
    "ain draham", "tabarka", "cap bon", "ichkeul", "zaghouan",
}

LIEUX_INDOOR = {
    "bardo", "musée", "museum", "medina", "médina", "souks", "souk",
    "centre ville", "gare", "aéroport",
}

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — ORCHESTRATEUR
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_ORCHESTRATEUR = """Tu es Dourbia, guide touristique de Dourbia Voyages (Tunisie).
IDENTITÉ: narratif·chaleureux·vivant — jamais "IA/assistant/selon mes données"
LANGUE: réponds dans la langue de l'utilisateur (FR/EN/AR/IT/DE)
OFFRES: circuits(Médina,Carthage,Bardo,ElJem,SidiBouSaïd,Dougga,Tozeur)|packs & expériences prêts à l'emploi(FamilyDay,CultureDay,IADay,AR/VR,ateliers,journées thématiques)|réservations|infos pratiques|météo intégrée
STYLE: narratif(pas de listes pour l'histoire)|≤150 mots|termine par question de relance|météo naturelle(pluie outdoor→alternative indoor)
INTERDIT: listes histoire|sans question relance|inventer lien/prix/itinéraire|"je ne peux pas"
LIENS/PRIX: affiche UNIQUEMENT ce que le tool retourne — ne jamais inventer mamicar.com/voiture/xxx ni prix_jour"""
# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — DÉTECTION D'INTENTION (modèle rapide)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_INTENTION = """Classificateur d'intention. Retourne UNIQUEMENT JSON valide.
Intentions: HISTORIQUE(monuments/histoire/culture)|CIRCUIT(itinéraire/circuit/packs/AR/VR)|RESERVATION(hôtel/voiture/dispo)|PRATIQUE(horaires/prix/accès/transport)|SMALLTALK(salutations/bavardage)|FEEDBACK(avis/note)|METEO(météo/climat)|TERRAIN(je suis devant/near/أمام monument — visite en cours)
Format: {"intention":"CIRCUIT","confiance":0.92,"entites":{"lieu":"Carthage","groupe":"famille","budget":150}}
Entités optionnelles — ne mets que celles présentes.
CONTEXTE: si tour précédent=RESERVATION → réponses suivantes(ville/dates/infos perso) sont RESERVATION.
Réponds UNIQUEMENT en JSON."""
# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — SYNTHÈSE FINALE (modèle puissant)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_SYNTHESE = """Tu es Dourbia, guide touristique de Dourbia Voyages en Tunisie.
Tu reçois des données brutes de différents agents et tu dois les transformer en une réponse
narrative naturelle, chaleureuse et dans le style d'un vrai guide tunisien.

RÈGLES :
- Maximum 150 mots
- Jamais de listes à puces pour l'histoire — tu narres
- Intègre les données météo naturellement si présentes (ex: "il fait beau aujourd'hui, parfait pour...")
- Si la météo indique pluie sur site outdoor → propose alternative
- Termine toujours par une question de relance
- Réponds dans la langue de l'utilisateur
- Ne dis jamais "je suis une IA", "selon les données", "les agents m'ont répondu"
- Si info météo : niveau VERT = mentionner positivement, ORANGE = conseil prudence, ROUGE = alternative indoor fortement recommandée
- N'invente JAMAIS d'itinéraires, d'horaires ou de sites sans données [CIRCUITS RECOMMANDÉS]
- Si aucun circuit n'est fourni, ne propose pas de plan de visite détaillé"""

# ─────────────────────────────────────────────────────────────────────────────
# MESSAGES DE FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

FALLBACK_MESSAGES = {
    "FR": "Laissez-moi une petite seconde, je reviens vers vous tout de suite ! En attendant, vous voulez qu'on parle d'un lieu en particulier ?",
    "EN": "Give me just a moment, I'll be right with you! In the meantime, is there a specific place you'd like to explore?",
    "AR": "لحظة من فضلك، سأعود إليك حالاً! في انتظار ذلك، هل تريد أن نتحدث عن مكان معين؟",
    "IT": "Un momento solo, torno subito! Nel frattempo, vuoi che parliamo di un posto in particolare?",
    "DE": "Einen Moment bitte, ich bin gleich zurück! Möchten Sie inzwischen über einen bestimmten Ort sprechen?",
}

CLARIFICATION_MESSAGES = {
    "FR": "Je veux bien vous aider, mais j'ai besoin de mieux comprendre votre demande. Vous cherchez plutôt des informations sur un site historique, un itinéraire, ou autre chose ?",
    "EN": "I'd love to help! Could you tell me a bit more — are you looking for historical info, a tour itinerary, or something else?",
    "AR": "يسعدني مساعدتك! هل تبحث عن معلومات تاريخية، مسار سياحي، أم شيء آخر؟",
    "IT": "Volentieri! Stai cercando informazioni storiche, un itinerario, o qualcos'altro?",
    "DE": "Gerne helfe ich! Suchen Sie historische Informationen, eine Reiseroute oder etwas anderes?",
}
# PROBING CIRCUIT — Collecte interactive en 8 questions
# ─────────────────────────────────────────────────────────────────────────────
# Ordre de collecte imposé — NE PAS modifier l'ordre
CHAMPS_COLLECTE_CIRCUIT = [
    "destination",
    "epoques",
    "types",
    "mobilite",
    "duree",
    "transport",
    "budget",
    "tarif",
]
SYSTEM_PROMPT_PROBING = """Tu es Aziz, conseiller Dourbia Voyages. Collecte 8 champs UN PAR UN dans cet ordre:
1.destination 2.epoques[romaine|islamique|punique|ottomane|moderne|prehistorique] 3.types[culturel|nature|religieux|historique|familial|aventure] 4.mobilite[reduite|normale] 5.duree 6.transport[mobilite=reduite→voiture/adapté PMR|normale→a_pied/velo/voiture] 7.budget(DT) 8.tarif[resident|etudiant|etranger|enseignant|retraite|enfant]
Quand tout est collecté: écris EXACTEMENT [PROFIL_COMPLET] puis résume chaleureusement.
Reste concis·enthousiaste. Réponds dans la langue de l'utilisateur."""


# Prompts système spécifiques au mode terrain
TERRAIN_SYSTEM_PROMPT = """Tu es Aziz, guide touristique physiquement présent sur le site avec le visiteur.
Le visiteur est EN FACE du monument — il le voit de ses yeux.
STYLE : narratif vivant, comme si tu lui parlais sur place. Présent, pas passé.
RÈGLES :
- 150 mots maximum
- Commence par une accroche sensorielle ou anecdote marquante
- Intègre naturellement la durée de visite conseillée si disponible
- Si le monument est fermé : dis-le clairement et propose le prochain site
- Termine par une invitation à explorer : "Avancez vers..." ou "Levez les yeux..."
- JAMAIS "selon les données" ou "d'après mes informations"
- N'invente JAMAIS d'horaires, de durée de visite, de tarif ou de condition d'accès
  qui ne sont pas fournis explicitement dans le contexte ci-dessus. S'ils sont
  absents, n'en parle simplement pas — concentre-toi sur le récit sensoriel et
  historique du lieu, sans donner de fausses informations pratiques.
- Réponds dans la langue de l'utilisateur"""

# ───────────────────────────────────────────────────────────────────────────────
# ZONE 2 — Constantes d'intention (dans constants.py ou en haut d'orchestrateur.py)
# ───────────────────────────────────────────────────────────────────────────────

### AJOUTER dans la liste des intentions (ex: INTENTIONS ou ROUTING_TABLE) :

INTENTION_HISTORIQUE = "HISTORIQUE"

# Mots-clés multilingues déclenchant le routing vers l'agent historique
HISTORIQUE_KEYWORDS_FR = [
    "carthage",
    "punique",
    "romain",
    "byzantine",
    "byzantin",
    "monument",
    "site archéologique",
    "archéologie",
    "fouilles",
    "thermes",
    "tophet",
    "byrsa",
    "amphithéâtre",
    "basilique",
    "nécropole",
    "musée national",
    "musée de carthage",
    "histoire",
    "historique",
    "patrimoine",
    "antiquité",
    "hannibal",
    "hamilcar",
    "baal",
    "tanit",
    "explique",
    "raconte",
    "décris",
    "qu'est-ce que",
    "où se trouve",
    "quand a été construit",
]

HISTORIQUE_KEYWORDS_EN = [
    "carthage",
    "punic",
    "roman",
    "byzantine",
    "monument",
    "archaeological",
    "archaeology",
    "excavation",
    "thermes",
    "tophet",
    "byrsa",
    "amphitheatre",
    "basilica",
    "necropolis",
    "national museum",
    "carthage museum",
    "history",
    "historical",
    "heritage",
    "antiquity",
    "hannibal",
    "hamilcar",
    "explain",
    "describe",
    "tell me about",
    "what is",
    "where is",
    "when was built",
]

HISTORIQUE_KEYWORDS_AR = [
    "قرطاج",
    "بونيقي",
    "روماني",
    "بيزنطي",
    "آثار",
    "أثري",
    "حفريات",
    "التوفت",
    "البيرسا",
    "المدرج",
    "الحمامات",
    "التاريخ",
    "التراث",
    "العصور القديمة",
    "هانيبال",
    "حمليقار",
    "بعل",
    "تانيت",
]
# ─────────────────────────────────────────────────────────────────────────────
# CONFIG CHEMINS PROJETS (à adapter selon ton environnement)
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Chemins vers les projets séparés (Windows)
PATH_WEATHER_AGENT   = os.path.join(os.path.dirname(BASE_DIR), "AgentMeteo")
PATH_CIRCUIT_AGENT   = os.path.join(os.path.dirname(BASE_DIR), "AgentCircuit")
PATH_RESERVATION_AGENT = os.path.join(os.path.dirname(BASE_DIR), "AgentLocation")
PATH_HISTORICAL_AGENT = os.path.join(os.path.dirname(BASE_DIR), "AgentHistorique")


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION D'ENTITÉS — PROBING CIRCUIT (modèle rapide)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_EXTRACTION_PROBING = """\
Tu es un extracteur d'entités JSON pour un système touristique en Tunisie.
Réponds UNIQUEMENT avec un objet JSON valide. PAS de texte avant/après, PAS de ```json.

Champs possibles :
- "destination" : string (ville ou région en Tunisie)
- "epoques"     : liste parmi ["romaine","islamique","punique","ottomane","moderne","prehistorique"]
- "types"       : liste parmi ["culturel","nature","religieux","historique","familial","aventure"]
- "mobilite"    : une valeur parmi ["reduite","normale"]
- "duree"       : durée (ex: "2h", "3h30", "180")
- "transport"   : une valeur parmi ["a_pied","velo","voiture","autre"]
- "budget"      : nombre entier en DT
- "tarif"       : une valeur parmi ["resident","etudiant","etranger","enseignant","retraite","enfant"]

Synonymes :
  mobilité réduite/PMR/handicap/fauteuil → "reduite"
  à pied/marche → "a_pied" | vélo/bicyclette/bike → "velo" | voiture/auto/taxi → "voiture"

Si rien à extraire → {}

RÈGLE CRITIQUE : n'extrais QUE les champs explicitement mentionnés dans le message.
Ne devine JAMAIS de valeurs par défaut. N'invente pas budget, durée, mobilité ou transport.
"""

# ─────────────────────────────────────────────────────────────────────────────
# PROPOSITION DE CIRCUIT — phrase de relance multilingue
# ─────────────────────────────────────────────────────────────────────────────

PROPOSITION_CIRCUIT = {
    "FR": "Au fait, si ça vous tente, je peux vous composer un circuit personnalisé{lieu} ou vous proposer nos packs prêts à l'emploi — dites-moi simplement ce qui vous ferait plaisir !",
    "EN": "By the way, if you're interested, I can put together a personalized tour{lieu} or show you our ready-to-choose packs — just let me know what you'd prefer!",
    "AR": "بالمناسبة، إذا كنت مهتماً، يمكنني تصميم مسار سياحي مخصص لك{lieu} أو عرض باقاتنا الجاهزة للاختيار — فقط أخبرني بما تفضل!",
    "IT": "A proposito, se ti interessa, posso creare un tour personalizzato{lieu} o mostrarti i nostri pack pronti all'uso — dimmi solo cosa preferisci!",
    "DE": "Übrigens, falls Interesse besteht, kann ich eine personalisierte Tour{lieu} zusammenstellen oder Ihnen unsere fertigen Erlebnispakete zeigen — sagen Sie einfach Bescheid!",
}

_LIEU_TEMPLATES = {
    "FR": " à {lieu}",
    "EN": " in {lieu}",
    "AR": " في {lieu}",
    "IT": " a {lieu}",
    "DE": " in {lieu}",
}


def texte_lieu(langue: str, lieu: str) -> str:
    if not lieu:
        return ""
    tpl = _LIEU_TEMPLATES.get(langue, _LIEU_TEMPLATES["FR"])
    return tpl.format(lieu=lieu)


# ─────────────────────────────────────────────────────────────────────────────
# DÉTECTION AFFIRMATION ("oui", "yes"...) — multilingue, sans LLM
# ─────────────────────────────────────────────────────────────────────────────

_AFFIRMATION_REGEX = re.compile(
    r"\b(oui|ouais|yes|yep|ok|okay|d\'accord|daccord|vas[- ]y|allons[- ]y|"
    r"je veux|je voudrais|avec plaisir|pourquoi pas|bien s[uû]r|"
    r"s[iì]|certo|va bene|ja|gerne|نعم|أكيد|طيب|تمام)\b",
    re.IGNORECASE,
)


def is_affirmation(message: str) -> bool:
    msg = message.strip().lower()
    if msg in ("oui", "yes", "ok", "si", "sì", "ja", "نعم", "تمام"):
        return True
    return bool(_AFFIRMATION_REGEX.search(msg))


# Intentions qui ne doivent jamais déclencher l'onboarding circuit par affirmation
INTENTIONS_BLOQUANT_CIRCUIT = frozenset(
    {"RESERVATION", "METEO", "PRATIQUE", "HISTORIQUE", "TERRAIN"}
)

_RESERVATION_KEYWORDS = re.compile(
    r"\b(r[eé]serv|louer|location|prendre\s+la|bloquer|confirmer|nissan|hyundai|volkswagen|polo|leaf|i10)\b",
    re.IGNORECASE,
)


def contient_demande_reservation(message: str) -> bool:
    """Détecte une demande explicite de réservation dans le message."""
    return bool(_RESERVATION_KEYWORDS.search(message))


def is_affirmation_circuit(message: str) -> bool:
    """
    Affirmation courte en réponse à la proposition de circuit.
    Exclut les messages contenant une autre demande (ex: « je veux louer une voiture »).
    """
    msg = message.strip().lower()
    if contient_demande_reservation(msg):
        return False
    if any(
        w in msg
        for w in ("météo", "meteo", "temps", "pluie", "histoire", "horaire", "prix", "tarif")
    ):
        return False
    # Réponses courtes uniquement (oui, ok, je veux — sans autre objet)
    if len(msg.split()) > 4:
        return False
    return is_affirmation(message)


QUESTIONS_PROBING_MANQUANTES = {
    "destination": (
        "Quelle ville ou région de Tunisie souhaitez-vous visiter ? "
        "(ex: Tunis, Djerba, Sousse, Kairouan...)"
    ),
    "epoques": (
        "Quelles époques historiques vous attirent ? "
        "(romaine, islamique, punique, ottomane, moderne, préhistorique)"
    ),
    "types": (
        "Quel type de sites préférez-vous ? "
        "(culturel, nature, religieux, historique, familial, aventure)"
    ),
    "mobilite": "Quel est votre type de mobilité ? (réduite — PMR, ou normale)",
    "duree": "Combien de temps souhaitez-vous consacrer au circuit ? (ex: 2h, 3h30)",
    "transport": "Quel mode de transport préférez-vous ? (à pied, vélo ou voiture)",
    "budget": "Quel est votre budget approximatif en dinars tunisiens (DT) ? (ex: 50 DT, 100 DT)",
    "tarif": (
        "Quelle est votre situation tarifaire ? "
        "(résident tunisien, étudiant, étranger, enseignant, retraité, enfant)"
    ),
}
# ─────────────────────────────────────────────────────────────────────────────
# PROBING — fonctions et messages multilingues manquants
# ─────────────────────────────────────────────────────────────────────────────

QUESTIONS_PROBING_EN = {
    "destination": "Which city or region of Tunisia would you like to visit? (e.g. Tunis, Djerba, Sousse, Kairouan...)",
    "epoques": "Which historical periods interest you? (Roman, Islamic, Punic, Ottoman, modern, prehistoric)",
    "types": "What type of sites do you prefer? (cultural, nature, religious, historical, family, adventure)",
    "mobilite": "What is your mobility type? (reduced — PMR, or normal)",
    "duree": "How much time would you like to spend on the tour? (e.g. 2h, 3h30)",
    "transport": "What mode of transport do you prefer? (on foot, bike, or car)",
    "budget": "What is your approximate budget in Tunisian dinars (DT)? (e.g. 50 DT, 100 DT)",
    "tarif": "What is your pricing category? (Tunisian resident, student, foreigner, teacher, retiree, child)",
}


def get_questions_probing(langue: str = "FR") -> dict:
    if langue == "EN":
        return QUESTIONS_PROBING_EN
    return QUESTIONS_PROBING_MANQUANTES


INTRO_PROBING_BY_LANG = {
    "FR": "Pour vous proposer le circuit idéal, j'ai quelques petites questions à vous poser.\n\n",
    "EN": "To put together the perfect tour for you, I have a few quick questions.\n\n",
}

MSG_PROBING_INCOMPRIS = {
    "FR": "Je n'ai pas bien compris votre réponse, pouvez-vous préciser ?\n\n",
    "EN": "I didn't quite catch that, could you clarify?\n\n",
}

MSG_PROBING_RECAP_INTRO = {
    "FR": "Parfait, voici le récapitulatif de votre profil :\n\n",
    "EN": "Great, here's a summary of your profile:\n\n",
}

MSG_PROBING_PREPARE = {
    "FR": "Je vous prépare tout de suite vos circuits personnalisés...",
    "EN": "I'm putting together your personalized tours right now...",
}


def get_langue_nom(langue: str) -> str:
    return {
        "FR": "français",
        "EN": "English",
        "AR": "العربية",
        "IT": "italiano",
        "DE": "Deutsch",
    }.get(langue, "français")


__all__ = [
    "GROQ_API_KEY",
    "MODEL_FAST",
    "MODEL_SMART",
    "AGENT_TIMEOUT_SECONDS",
    "HISTORY_WINDOW",
    "INTENT_CONFIDENCE_THRESHOLD",
    "ROUTING_TABLE",
    "INTENTIONS_VALIDES",
    "LIEUX_OUTDOOR",
    "LIEUX_INDOOR",
    "SYSTEM_PROMPT_ORCHESTRATEUR",
    "SYSTEM_PROMPT_INTENTION",
    "SYSTEM_PROMPT_SYNTHESE",
    "FALLBACK_MESSAGES",
    "CLARIFICATION_MESSAGES",
    "PROPOSITION_CIRCUIT",
    "CHAMPS_COLLECTE_CIRCUIT",
    "PATH_WEATHER_AGENT",
    "PATH_CIRCUIT_AGENT",
    "SYSTEM_EXTRACTION_PROBING",
    "texte_lieu",
    "is_affirmation",
    "INTENTIONS_BLOQUANT_CIRCUIT",
    "contient_demande_reservation",
    "is_affirmation_circuit",
    "QUESTIONS_PROBING_MANQUANTES",
    "get_questions_probing",
    "INTRO_PROBING_BY_LANG",
    "MSG_PROBING_INCOMPRIS",
    "MSG_PROBING_RECAP_INTRO",
    "MSG_PROBING_PREPARE",
    "get_langue_nom",
    "TERRAIN_SYSTEM_PROMPTS",
    "HISTORIQUE_KEYWORDS_FR",
    "HISTORIQUE_KEYWORDS_EN",
    "HISTORIQUE_KEYWORDS_AR",
    "INTENTION_HISTORIQUE",
]
PROMPTS_PAR_INTENTION = {
    "HISTORIQUE": SYSTEM_PROMPT_ORCHESTRATEUR,
    "CIRCUIT": SYSTEM_PROMPT_PROBING,  # probing si pas de profil, orchestrateur sinon
    "RESERVATION": None,  # délégué directement à Yasmine
    "PRATIQUE": SYSTEM_PROMPT_ORCHESTRATEUR,
    "SMALLTALK": SYSTEM_PROMPT_ORCHESTRATEUR,
    "FEEDBACK": SYSTEM_PROMPT_ORCHESTRATEUR,
    "METEO": SYSTEM_PROMPT_SYNTHESE,  # synthèse suffit pour la météo
}
