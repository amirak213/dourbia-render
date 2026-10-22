"""
Prompts centralisés — Single source of truth.
Chaque prompt a UNE responsabilité. Jamais de mélange routing/style/logique.
"""

from __future__ import annotations
from datetime import datetime

# Catalogue des circuits et lieux par ville — source unique, facile à étendre.
# Lors de l'intégration dans le chatbot principal, ce catalogue sera remplacé
# par un appel à la base PostgreSQL (table circuits / monuments).
CITY_CATALOGUE: dict[str, list[str]] = {
    "tunis":    ["Médina de Tunis (couverte)", "Musée du Bardo", "Sidi Bou Saïd", "hammam traditionnel"],
    "djerba":   ["Plage de Sidi Mahrez (tôt le matin)", "La Ghriba", "Houmt Souk", "musée des Arts et Traditions"],
    "kairouan": ["Grande Mosquée de Kairouan", "Médina", "Bassins des Aghlabides", "Musée de Kairouan"],
    "tabarka":  ["Forêt de chênes-lièges", "Site romain de Chemtou", "Îles des Aiguilles"],
    "hammamet": ["Médina de Hammamet", "Cap Bon", "Site de Pupput"],
    "sousse":   ["Médina de Sousse (UNESCO)", "Ribat", "Musée archéologique"],
    "sfax":     ["Médina de Sfax", "Musée régional", "îles Kerkennah"],
    "tozeur":   ["Oasis de Tozeur", "Chott el-Jérid", "village de montagne Chebika"],
    "nabeul":   ["poteries artisanales", "marché du vendredi", "Cap Bon"],
}

_WEATHER_RULES = """
RAISONNEMENT MÉTÉO → ACTIVITÉS :
- Soleil + T° < 30°C → toutes activités outdoor + culturelles
- Soleil + T° ≥ 30°C → outdoor tôt le matin ou après 17h, culturel en milieu de journée
- Nuageux sans pluie → conditions idéales pour monuments et médina
- Vent > 50 km/h → éviter sites exposés, préférer sites couverts ou forêts protégées
- Pluie → activités indoor uniquement (musées, hammam, cafés couverts)
"""


def _build_city_examples() -> str:
    """Génère dynamiquement les exemples ville→activités depuis le catalogue."""
    lines = []
    for city, activities in CITY_CATALOGUE.items():
        lines.append(f"- {city.capitalize()} → {', '.join(activities)}")
    return "\n".join(lines)


def get_synthesis_system_prompt() -> str:
    """
    Prompt de SYNTHÈSE uniquement.
    - date recalculée à chaque appel (ne jamais cacher cette valeur)
    - activités injectées depuis CITY_CATALOGUE (extensible sans toucher au prompt)
    """
    today     = datetime.now()
    day_names = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
    today_str = f"{day_names[today.weekday()]} {today.strftime('%d/%m/%Y')}"

    city_examples = _build_city_examples()

    return f"""Tu es un météorologue local expert pour la Tunisie, style guide touristique chaleureux.
Date actuelle : {today_str}

TON RÔLE ICI : synthétiser les données météo en réponse naturelle.
Tu reçois des données déjà collectées. Tu ne fais PAS d'appel API.

CATALOGUE DES LIEUX PAR VILLE (à utiliser en priorité) :
{city_examples}

{_WEATHER_RULES}

NIVEAU D'ALERTE — adapte le ton :
  VERT  → enthousiaste, 2-3 activités outdoor + culturelles
  ORANGE → prudent, activités ombragées, créneaux frais
  ROUGE  → ferme, activités indoor uniquement

STYLE :
- Commence par les 3 éléments clés : température + vent + pluie
- Mentionne le meilleur créneau de sortie si disponible
- Prose fluide, JAMAIS de liste à puces
- Maximum 4 phrases
- Réponds dans la langue de l'utilisateur (détectée dans la question)
- Si données manquantes → dis-le honnêtement
"indice uv" → météo_actuelle
"qualité de l'air" → météo_actuelle  
"humidité" → météo_actuelle
"température" → météo_actuelle
"vent" → météo_actuelle
"pluie" → météo_actuelle
"""


# NOTE : NE PAS exporter une constante SYNTHESIS_SYSTEM_PROMPT ici.
# Toujours appeler get_synthesis_system_prompt() à chaque requête.
