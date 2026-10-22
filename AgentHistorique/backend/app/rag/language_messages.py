from __future__ import annotations

from app.rag.language_detection import normalize_supported_language

NOT_FOUND_ANSWERS = {
    "fr": "Je n'ai pas trouvé d'informations fiables sur ce sujet.",
    "en": "I couldn't find reliable information on this topic.",
    "ar": "لم أجد معلومات موثوقة حول هذا الموضوع.",
}

# Kept for evaluation scripts and backward-compatible imports.
INSUFFICIENT_CONTEXT_ANSWERS = NOT_FOUND_ANSWERS

NO_RELEVANT_WEB_RESULTS_ANSWERS = NOT_FOUND_ANSWERS

NO_ART_WEB_RESULTS_ANSWERS = {
    "fr": (
        "Je n'ai pas trouvé d'informations précises sur des œuvres artistiques "
        "liées à ce sujet."
    ),
    "en": (
        "I couldn't find precise information about artworks related to this topic."
    ),
    "ar": "لم أجد معلومات دقيقة عن أعمال فنية مرتبطة بهذا الموضوع.",
}

LOCAL_CONTEXT_NOT_RELEVANT_NOTES = {
    "fr": "Aucune source pertinente pour cette question.",
    "en": "No relevant sources for this question.",
    "ar": "لا توجد مصادر مناسبة لهذا السؤال.",
}

EMPTY_RETRIEVED_CONTEXT = {
    "fr": "Aucune source récupérée.",
    "en": "No retrieved sources.",
    "ar": "لا توجد مصادر مسترجعة.",
}

EMPTY_WEB_CONTEXT = {
    "fr": "Aucun résultat web.",
    "en": "No web results.",
    "ar": "لا توجد نتائج ويب.",
}

SUGGESTED_ACTIONS = {
    "show_hours": {
        "fr": "Afficher les horaires",
        "en": "Show opening hours",
        "ar": "عرض أوقات الزيارة",
    },
    "circuit_detail": {
        "fr": "Voir le détail du circuit",
        "en": "View circuit details",
        "ar": "عرض تفاصيل المسار",
    },
    "roman_circuit": {
        "fr": "Proposer un circuit romain",
        "en": "Suggest a Roman tour",
        "ar": "اقتراح مسار روماني",
    },
    "time_adapted_visit": {
        "fr": "Proposer une visite adaptée à votre temps",
        "en": "Suggest a visit suited to your time",
        "ar": "اقتراح زيارة مناسبة لوقتك",
    },
    "nearby_monuments": {
        "fr": "Voir les monuments proches",
        "en": "View nearby monuments",
        "ar": "عرض الآثار القريبة",
    },
    "ask_another": {
        "fr": "Poser une autre question sur Carthage",
        "en": "Ask another question about Carthage",
        "ar": "اطرح سؤالاً آخر عن قرطاج",
    },
}


def localized_message(catalog: dict[str, str], language: str) -> str:
    normalized = normalize_supported_language(language)
    return catalog.get(normalized, catalog["fr"])


def localized_action(action_key: str, language: str) -> str:
    catalog = SUGGESTED_ACTIONS[action_key]
    return localized_message(catalog, language)
