"""
packs_tool.py — Détection, récupération et formatage des packs touristiques.

Pas de LLM : tout est déterministe (regex + SQL + formatage statique).
Utilise psycopg2 (synchrone) comme le reste du projet.
"""

import os
import re
import logging
import textwrap
from collections import defaultdict

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from typing import Optional

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

log = logging.getLogger("chatbot.packs_tool")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG DB — même convention que stage_AI_agentique--master/db.py
# ─────────────────────────────────────────────────────────────────────────────

_DB_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "dbname": os.environ.get("PG_DBNAME", "sig_dourbia"),
    "user": os.environ.get("PG_USER", "postgres"),
    "password": os.environ.get("PG_PASSWORD", ""),
    "options": "-c client_encoding=UTF8",
}

# ─────────────────────────────────────────────────────────────────────────────
# ENCODING REPAIR — répare l'encodage CP850 mal stocké
# ─────────────────────────────────────────────────────────────────────────────

def _clean_encoding(val: str) -> str:
    """Répare les caractères CP850 mal décodés stockés dans la base de données."""
    if not val:
        return val
    try:
        return val.encode('cp1252', errors='ignore').decode('cp850', errors='ignore')
    except Exception:
        return val

# ─────────────────────────────────────────────────────────────────────────────
# 1. DÉTECTION INTENT « PACKS » — mots-clés FR / EN / AR
# ─────────────────────────────────────────────────────────────────────────────

_PACKS_KEYWORDS = re.compile(
    r"\b("
    r"packs?|forfaits?|offres?|produits?|catalogue"
    r"|voir les packs|quels packs|vos packs|nos packs"
    r"|exp[ée]riences?|ateliers?"
    r"|packages?"
    r")\b"
    r"|باقات?|عروض",
    re.IGNORECASE,
)


def is_packs_request(message: str) -> bool:
    """
    Retourne True si le message contient une demande liée aux packs.
    """
    return bool(_PACKS_KEYWORDS.search(message))


# ─────────────────────────────────────────────────────────────────────────────
# 2. FILTRAGE INTELLIGENT (PUBLIC CIBLE ET LIEU)
# ─────────────────────────────────────────────────────────────────────────────

# Mapping des catégories logiques de public vers les codes packs
_CATEGORY_MAPPING = {
    "famille": ["PACK-FAMILY-DAY"],
    "scolaires": ["PACK-CULTURE-ECOLE", "PACK-IA-DAY", "PACK-ATELIER-VRAR"],
    "entreprise": ["PACK-ATELIER-VRAR", "PACK-EVENEMENT"],
    "touriste": ["PACK-CARTHAGE-DJ", "PACK-CARTHAGE-JC", "PACK-CIRCUIT-MEDINA"],
    "evenement": ["PACK-EVENEMENT"],
    "agenda": ["PACK-AGENDA-CULTUREL", "PACK-ATELIERS-ART"],
}


def detect_filter_category(message: str) -> str | None:
    """Détecte la catégorie de public cible à partir du message en vérifiant les mots complets."""
    msg = message.lower().strip()
    words = re.findall(r'\b\w+\b', msg)
    
    # 1. Famille
    if any(k in words for k in ["famille", "familles", "family", "parent", "parents", "enfant", "enfants", "gamin", "gamins"]) or any(emoji in msg for emoji in ["👨", "👩", "👧", "👦"]):
        return "famille"
        
    # 2. Scolaires
    if any(k in words for k in ["scolaire", "scolaires", "ecole", "ecoles", "école", "écoles", "etudiant", "etudiants", "étudiant", "étudiants", "élève", "élèves", "eleve", "eleves", "school", "schools"]) or any(emoji in msg for emoji in ["🏫", "🎓", "✏️"]):
        return "scolaires"
        
    # 3. Entreprise/Groupe
    if any(k in words for k in ["entreprise", "entreprises", "business", "société", "sociétés", "societe", "societes", "collègue", "collègues", "collegue", "collegues", "groupe", "groupes", "group", "groups", "company"]) or any(emoji in msg for emoji in ["🏢", "💼", "👥"]):
        return "entreprise"
        
    # 4. Événement
    if any(k in words for k in ["evenement", "evenements", "événement", "événements", "event", "events", "salon", "salons", "festival", "festivals", "manifestation", "manifestations"]) or any(emoji in msg for emoji in ["🎉", "🎊", "🎈", "🎫"]):
        return "evenement"
        
    # 5. Touriste
    if any(k in words for k in ["touriste", "touristes", "visite", "visites", "visiter", "découverte", "decouverte", "tourist", "tourists"]) or any(emoji in msg for emoji in ["🌍", "✈️", "🗺️"]):
        return "touriste"
        
    # 6. Agenda/Institution
    if any(k in words for k in ["agenda", "institution", "institutions", "culturel", "culturels", "artistique", "artistiques", "mosaïque", "mosaique", "art", "arts"]) or any(emoji in msg for emoji in ["🏛️", "📅", "🎨"]):
        return "agenda"
        
    return None


def detect_filter_location(message: str) -> str | None:
    """Détecte le lieu à partir du message."""
    msg = message.lower().strip()
    if any(k in msg for k in ["carthage", "قرطاج"]):
        return "carthage"
    if any(k in msg for k in ["médina", "medina", "المدينة"]):
        return "medina"
    if any(k in msg for k in ["oudhna", "أوذنة"]):
        return "oudhna"
    return None


def _normalize(s: str) -> str:
    """Normalise la chaîne pour une recherche insensible aux accents et à la casse."""
    s = s.lower()
    s = s.replace("é", "e").replace("è", "e").replace("ê", "e")
    s = s.replace("à", "a").replace("â", "a")
    s = s.replace("ï", "i").replace("î", "i")
    return s


def match_location(pack_lieu: Optional[str], detected_loc: Optional[str]) -> bool:
    """Retourne True si le lieu du pack contient le lieu détecté."""
    if not pack_lieu or not detected_loc:
        return False
    return _normalize(detected_loc) in _normalize(pack_lieu)


# ─────────────────────────────────────────────────────────────────────────────
# 3. REQUÊTE SQL — packs actifs
# ─────────────────────────────────────────────────────────────────────────────

_PACKS_QUERY = """\
SELECT code_pack, nom_pack, categorie, descriptif, duree,
       capacite_personnes, public_cible, partenaires, lieu
FROM packs
WHERE est_actif = TRUE
ORDER BY categorie, id
"""


def get_packs_from_db() -> list[dict]:
    """
    Récupère tous les packs actifs depuis PostgreSQL (psycopg2).
    Nettoie l'encodage des champs textes à la volée.
    Retourne une liste de dicts (vide si erreur ou pas de résultats).
    """
    try:
        conn = psycopg2.connect(**_DB_CONFIG)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(_PACKS_QUERY)
                rows = []
                for r in cur.fetchall():
                    d = dict(r)
                    for k, v in d.items():
                        if isinstance(v, str):
                            d[k] = _clean_encoding(v)
                    rows.append(d)
            log.info(f"[PACKS] {len(rows)} packs actifs récupérés et nettoyés")
            return rows
        finally:
            conn.close()
    except Exception as e:
        log.error(f"[PACKS] Erreur DB : {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 4. FORMATAGE CARTE — multilingue (FR / EN / AR)
# ─────────────────────────────────────────────────────────────────────────────

_LABELS = {
    "FR": {
        "title": "🎒 **Nos packs & expériences disponibles**",
        "description": "📝 ",
        "duration": "⏱ Durée : ",
        "capacity": "👥 Capacité : {n} personne(s)",
        "audience": "🎯 Public cible : ",
        "location": "📍 Lieu : ",
        "empty": "Aucun pack disponible pour cette recherche. Revenez bientôt ! 🌟",
        "footer": "\n💬 Un pack vous intéresse ? Dites-moi lequel et je vous donne tous les détails pour réserver !",
        "filter_question": "Pour qui cherchez-vous une expérience et pour quel lieu ?",
        "filter_options": "👨‍👩‍👧 Famille   🏫 Scolaires   🏢 Entreprise   🎉 Événement   🌍 Touriste\n📍 Carthage   📍 Médina   📍 Oudhna",
    },
    "EN": {
        "title": "🎒 **Our available packs & experiences**",
        "description": "📝 ",
        "duration": "⏱ Duration: ",
        "capacity": "👥 Capacity: {n} person(s)",
        "audience": "🎯 Target audience: ",
        "location": "📍 Location: ",
        "empty": "No packs available for this search. Check back soon! 🌟",
        "footer": "\n💬 Interested in a pack? Tell me which one and I'll give you all the details to book it!",
        "filter_question": "Who are you looking for an experience for and in which location?",
        "filter_options": "👨‍👩‍👧 Family   🏫 Schools   🏢 Corporate   🎉 Event   🌍 Tourist\n📍 Carthage   📍 Medina   📍 Oudhna",
    },
    "AR": {
        "title": "🎒 **باقاتنا وتجاربنا المتاحة**",
        "description": "📝 ",
        "duration": "⏱ Durée : ",
        "capacity": "👥 السعة: {n} شخص/أشخاص",
        "audience": "🎯 الفئة المستهدفة: ",
        "location": "📍 المكان: ",
        "empty": "لا توجد باقات متاحة لهذا البحث حالياً. عودوا قriباً ! 🌟",
        "footer": "\n💬 هل أعجبتك إحدى الباقات؟ أخبرني بها وسأعطيك كل التفاصيل للحجز!",
        "filter_question": "لمن تبحث عن تجربة وفي أي مكان؟",
        "filter_options": "👨‍👩‍👧 عائلة   🏫 مدارس   🏢 شركات  🎉 فعاليات   🌍 سائح\n📍 قرطاج   📍 المدينة العتيقة   📍 أوذنة",
    },
}


def _str_width(s: str) -> int:
    """Estime la largeur d'affichage de la chaîne pour aligner les bordures."""
    w = 0
    for char in s:
        if ord(char) > 0xffff or char in '🏛⏱👥🎯📍🤝🕶🏫👨👩👧🤖🎮🎨🎉📅🎒':
            w += 2
        elif ord(char) == 0xfe0f:
            continue
        else:
            w += 1
    return w


def _pad_line(text: str, width: int) -> str:
    """Complète la ligne de texte avec des espaces pour atteindre la largeur voulue."""
    current_w = _str_width(text)
    padding_needed = width - current_w
    if padding_needed > 0:
        return text + ' ' * padding_needed
    return text


def format_pack_card(p: dict, lang: str = "FR") -> str:
    """Formatte un pack unique sous forme de carte textuelle sans afficher les Partenaires."""
    labels = _LABELS.get(lang, _LABELS["FR"])

    emoji_map = {
        'circuit_patrimonial': '🏛️',
        'atelier_vr_ar': '🕶️',
        'pack_scolaire': '🏫',
        'pack_famille': '👨‍👩‍👧',
        'pack_ia': '🤖',
        'circuit_gamifie': '🎮',
        'atelier_artistique': '🎨',
        'evenementiel': '🎉',
        'agenda_culturel': '📅',
    }
    emoji = emoji_map.get(p.get("categorie", ""), "🎒")
    title = f"{emoji}  {p['nom_pack']}"

    # Largeur fixe interne de la carte
    width = 42

    lines = []
    lines.append('┌' + '─' * width + '┐')

    # Titre du Pack
    title_wrapped = textwrap.wrap(title, width=width)
    for tl in title_wrapped:
        lines.append('│ ' + _pad_line(tl, width) + ' │')

    lines.append('├' + '─' * width + '┤')

    # Description
    desc = p.get('descriptif', '')
    desc_wrapped = textwrap.wrap(desc, width=width)
    for dl in desc_wrapped:
        lines.append('│ ' + _pad_line(dl, width) + ' │')

    # Ligne blanche de séparation
    lines.append('│ ' + _pad_line('', width) + ' │')

    # Infos facultatives (Partenaires retiré !)
    if p.get('duree'):
        duration_str = f"{labels['duration']}{p['duree']}"
        for l in textwrap.wrap(duration_str, width=width):
            lines.append('│ ' + _pad_line(l, width) + ' │')

    if p.get('capacite_personnes'):
        cap_str = labels['capacity'].format(n=p['capacite_personnes'])
        for l in textwrap.wrap(cap_str, width=width):
            lines.append('│ ' + _pad_line(l, width) + ' │')

    if p.get('public_cible'):
        audience_str = f"{labels['audience']}{p['public_cible']}"
        for l in textwrap.wrap(audience_str, width=width):
            lines.append('│ ' + _pad_line(l, width) + ' │')

    if p.get('lieu'):
        lieu_clean = p['lieu'].replace(', ', ' · ')
        lieu_str = f"{labels['location']}{lieu_clean}"
        for l in textwrap.wrap(lieu_str, width=width):
            lines.append('│ ' + _pad_line(l, width) + ' │')

    lines.append('└' + '─' * width + '┘')
    return '\n'.join(lines)


def get_filter_question(lang: str = "FR") -> str:
    """Retourne la question de filtrage multilingue."""
    labels = _LABELS.get(lang, _LABELS["FR"])
    return f"{labels['filter_question']}\n\n{labels['filter_options']}"


def filter_packs(packs: list[dict], category: str | None = None, location: str | None = None) -> list[dict]:
    """Filtre les packs par catégorie et/ou lieu (logique extraite de format_packs_response)."""
    if category:
        filtered_codes = _CATEGORY_MAPPING.get(category, [])
        packs = [p for p in packs if p.get("code_pack") in filtered_codes]
    if location:
        packs = [p for p in packs if match_location(p.get("lieu", ""), location)]
    return packs


_EMOJI_MAP = {
    'circuit_patrimonial': '🏛️', 'atelier_vr_ar': '🕶️', 'pack_scolaire': '🏫',
    'pack_famille': '👨‍👩‍👧', 'pack_ia': '🤖', 'circuit_gamifie': '🎮',
    'atelier_artistique': '🎨', 'evenementiel': '🎉', 'agenda_culturel': '📅',
}


def pack_to_card_dict(p: dict) -> dict:
    """Convertit un pack DB en dict léger prêt pour le frontend (JSON, pas d'ASCII art)."""
    return {
        "code": p.get("code_pack"),
        "title": p.get("nom_pack"),
        "emoji": _EMOJI_MAP.get(p.get("categorie", ""), "🎒"),
        "description": p.get("descriptif"),
        "duration": p.get("duree"),
        "capacity": p.get("capacite_personnes"),
        "audience": p.get("public_cible"),
        "location": p.get("lieu"),
    }


def format_packs_response(
    packs: list[dict],
    lang: str = "FR",
    category: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """
    Formate la liste de packs sous forme de cartes Markdown en appliquant le filtrage par catégorie et/ou lieu.
    """
    labels = _LABELS.get(lang, _LABELS["FR"])

    # 1. Filtrer par public cible (catégorie)
    if category:
        filtered_codes = _CATEGORY_MAPPING.get(category, [])
        packs = [p for p in packs if p.get("code_pack") in filtered_codes]

    # 2. Filtrer par lieu
    if location:
        packs = [p for p in packs if match_location(p.get("lieu", ""), location)]

    if not packs:
        return labels["empty"]

    cards = []
    for p in packs:
        card = format_pack_card(p, lang)
        cards.append(f"```text\n{card}\n```")

    lines = [labels["title"], ""]
    lines.extend(cards)
    lines.append(labels["footer"])

    return "\n".join(lines)
