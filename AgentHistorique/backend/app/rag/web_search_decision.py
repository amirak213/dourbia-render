from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.rag.suggested_action_intent import all_suggested_action_phrases
from app.rag.text_utils import normalize_text

DOMAIN_KEYWORDS = (
    "carthage",
    "tunisie",
    "tunisien",
    "tunisienne",
    "patrimoine",
    "monument",
    "monuments",
    "site historique",
    "archéologie",
    "archeologie",
    "fouille",
    "fouilles",
    "tourisme",
    "culture",
    "circuit",
    "circuits",
    "musée",
    "musee",
    "byrsa",
    "tophet",
    "baal",
    "hammon",
    "tanit",
    "thermes",
    "amphitheatre",
    "amphithéâtre",
    "cothon",
    "punique",
    "romain",
    "romaine",
)

WEB_SEARCH_META_PHRASES = (
    "faites une recherche web",
    "faire une recherche web",
    "faite une recherche web",
    "fait une recherche web",
    "fais une recherche web",
    "fait une recherche web",
    "faire une recherche sur",
    "faite une recherche sur",
    "faites une recherche sur",
    "fais une recherche sur",
    "fait une recherche sur",
    "fais une recherche",
    "fait une recherche",
    "faire une recherche",
    "faite une recherche",
    "cherche en ligne",
    "chercher en ligne",
    "cherche sur le web",
    "chercher sur le web",
    "cherche sur web",
    "chercher sur web",
    "recherche en ligne",
    "recherche sur internet",
    "recherche internet",
    "une recherche web",
    "recherche web",
    "sur internet",
    "sur le web",
    "en ligne",
    # English equivalents
    "search it on the web",
    "search on the web",
    "search on web",
    "search on the internet",
    "search on internet",
    "search the web",
    "search the internet",
    "search online",
    "look it up online",
    "look up online",
    "web search",
    "on the web",
    "on the internet",
    "online search",
)

SUGGESTED_ACTION_PHRASES_TO_STRIP = all_suggested_action_phrases()

NEWS_OR_RECENT_HINTS = (
    "informations récentes",
    "informations recentes",
    "actualités",
    "actualites",
    "dernieres nouvelles",
    "dernières nouvelles",
    "dernieres decouvertes",
    "dernières découvertes",
    "derniere decouverte",
    "dernière découverte",
    "dernieres fouilles",
    "dernières fouilles",
    "fouilles recentes",
    "fouilles récentes",
)

ARCHAEOLOGY_QUERY_MARKERS = (
    "fouill",
    "archeolog",
    "archéolog",
    "excavat",
    "decouverte",
    "découverte",
    "decouvertes",
    "découvertes",
    "chantier",
)

RECENT_TIME_MARKERS = (
    "2024",
    "2025",
    "2026",
    "2027",
    "recent",
    "recente",
    "recentes",
    "actualite",
    "actualites",
    "actualités",
    "dernier",
    "derniere",
    "dernières",
    "dernieres",
    "dernière",
)

GENERIC_SCIENCE_WEB_DOMAINS = (
    "nationalgeographic",
    "sciencesetavenir",
    "science.org",
    "quantamagazine",
    "nature.com",
    "phys.org",
    "futura-sciences.com",
)

EVENT_OR_SCHEDULE_HINTS = (
    "2024",
    "2025",
    "2026",
    "2027",
    "festival",
    "journees cinematographiques",
    "journées cinématographiques",
    "journee cinematographique",
    "journée cinématographique",
    "jcc",
    "cinema",
    "cinematographique",
    "cinématographique",
    "programme",
    "debut",
    "début",
    "dates",
    "calendrier",
)

HISTORICAL_FIGURE_MARKERS = (
    "baal",
    "hammon",
    "tanit",
    "didon",
    "hannibal",
    "hamilcar",
)

LOOKUP_INTENT_PREFIXES = (
    "chercher ",
    "cherche ",
    "rechercher ",
    "recherche ",
    "trouver ",
    "retrouver ",
    "search for ",
    "search ",
    "find ",
    "look up ",
    "lookup ",
)

VAGUE_FOLLOW_UP_PHRASES = (
    "sur ca",
    "ce sujet",
    "cette question",
    "a ce sujet",
    "à ce sujet",
    "la dessus",
    "là dessus",
    "la-dessus",
    "là-dessus",
    "about it",
    "related to it",
    "for it",
    "on it",
)

VAGUE_FOLLOW_UP_TOKENS = frozenset(
    {
        "ca",
        "cela",
        "celui",
        "celle",
        "ceci",
        "sujet",
        "question",
        "it",
        "that",
        "this",
    }
)

DEMONSTRATIVE_MONUMENT_PHRASES = (
    "liées à ce monument",
    "liees a ce monument",
    "liée à ce monument",
    "liee a ce monument",
    "à ce monument",
    "a ce monument",
    "sur ce monument",
    "de ce monument",
    "ce monument",
    "cet monument",
    "cette monument",
    "ce site",
    "cet site",
    "cette site",
    "ce lieu",
    "related to it",
    "about it",
    "for it",
    "on it",
    "this monument",
    "that monument",
    "this site",
    "that site",
)

GENERIC_MONUMENT_PHRASES = (
    "liees au monument",
    "liées au monument",
    "liee au monument",
    "liée au monument",
    "liees a le monument",
    "liées à le monument",
    "sur le monument",
    "du monument",
    "de le monument",
    "au monument",
    "a le monument",
    "le monument",
)

DEMONSTRATIVE_SUBJECTS = frozenset(
    {
        "ce monument",
        "cet monument",
        "cette monument",
        "ce site",
        "cet site",
        "cette site",
        "ce lieu",
        "ca",
        "monument",
        "le monument",
        "it",
        "that",
        "this",
    }
)

GENERIC_TOPIC_STOPWORDS = frozenset(
    {
        "monument",
        "monuments",
        "site",
        "lieu",
        "lieux",
        "carthage",
        "tunisie",
        "tunisia",
    }
)

EXPLICIT_WEB_SEARCH_HINTS = WEB_SEARCH_META_PHRASES + NEWS_OR_RECENT_HINTS

BLOCKED_WEB_DOMAINS = (
    "pscp.tv",
    "periscope.tv",
    "twitter.com",
    "x.com",
    "facebook.com",
    "tiktok.com",
    "instagram.com",
    "atelierdeschefs.fr",
    "iletaitunefoislapatisserie.com",
    "lacuisinedemamere.fr",
    "marmiton.org",
)

BLOCKED_WEB_TITLE_MARKERS = (
    "periscope",
    "venez parler",
    "live stream",
    "livestream",
)

TOURISM_WEB_DOMAINS = (
    "tripadvisor",
    "routard.com",
    "booking.com",
    "viator.com",
    "petitfute.com",
    "petit-fute.com",
    "lonelyplanet.com",
    "viamichelin",
    "guide-voyage-tunisie",
    "guidevoyage",
    "destination-tunis",
    "destinationtunis",
)

OFFSITE_EXHIBITION_MARKERS = (
    "exposition collective",
    "vernissage",
    "tgm gallery",
    "la marsa",
    "chez tgm",
    "sortir/",
    "/sortir",
    "expos-et-vernissages",
)

ART_CULTURE_QUERY_MARKERS = (
    "oeuvre",
    "oeuvres",
    "artistique",
    "artistiques",
    "artistic",
    "artwork",
    "artworks",
    "sculpture",
    "peinture",
    "exposition",
    "salammbo",
    "salammbô",
    "salambo",
    "flaubert",
    "gussier",
    "gussiere",
    "bastien",
    "baston",
)

WEB_ART_CONTENT_MARKERS = ART_CULTURE_QUERY_MARKERS + (
    "art",
    "arts",
    "museal",
    "museum",
    "galerie",
    "gallery",
    "stele",
    "stèles",
    "steles",
)

STRONG_WEB_ART_CONTENT_MARKERS = (
    "oeuvre",
    "oeuvres",
    "sculpture",
    "sculptures",
    "peinture",
    "exposition",
    "mosaique",
    "mosaïque",
    "mosaiques",
    "fresque",
    "fresques",
    "masque",
    "masques",
    "stele",
    "stèles",
    "steles",
    "galerie",
    "museal",
    "museum",
    "salammbo",
    "salambo",
    "flaubert",
    "gussier",
    "gussiere",
    "bastien",
    "baston",
)

RECIPE_WEB_MARKERS = (
    "recette",
    "patisserie",
    "pâtisserie",
    "dessert",
    "glands",
    "cuisine",
    "chef",
)

CONVERSATIONAL_TOPIC_STOPWORDS = frozenset(
    {
        "parler",
        "parlez",
        "parle",
        "venez",
        "venir",
        "comprends",
        "comprend",
        "maintenant",
        "artistique",
        "artistiques",
        "oeuvre",
        "oeuvres",
        "liee",
        "liees",
        "lies",
        "question",
        "desole",
        "desolé",
    }
)

HISTORICAL_CONTENT_HINTS = (
    "siècle",
    "siecle",
    "époque",
    "epoque",
    "histoire",
    "historique",
    "fouille",
    "archéologie",
    "archeologie",
    "monument",
    "empire",
    "civilisation",
    "civilization",
    "daté",
    "date",
    "construit",
    "ruines",
    "site",
)

MIN_TOTAL_CHUNK_CHARS = 120
MIN_SINGLE_CHUNK_CHARS = 40

WEB_SEARCH_FILLER_TOKENS = frozenset(
    {
        "a",
        "au",
        "aux",
        "de",
        "des",
        "du",
        "en",
        "la",
        "le",
        "les",
        "sur",
        "un",
        "une",
        "donner",
        "donnez",
        "donne",
        "donnes",
        "faites",
        "faite",
        "fait",
        "presentez",
        "presente",
        "presenter",
        "montrez",
        "montrer",
        "moi",
        "svp",
        "stp",
        "search",
        "online",
        "internet",
        "related",
        "about",
        "for",
        "the",
        "it",
    }
)

TOPIC_STOPWORDS = WEB_SEARCH_FILLER_TOKENS | {
    "carthage",
    "tunisie",
    "tunisia",
    "tunis",
    "recherche",
    "web",
    "ligne",
    "internet",
    "question",
    "informations",
    "information",
    "recentes",
    "recente",
    "actualites",
    "actualités",
}


NEWS_RESULT_MARKERS = (
    "2024",
    "2025",
    "2026",
    "2027",
    "news",
    "actualit",
    "recent",
    "aujourd",
    "ce mois",
    "this month",
    "annonce",
    "communique",
    "découverte",
    "decouverte",
    "excavation",
    "fouille",
)

ANCIENT_HISTORY_ONLY_MARKERS = (
    "fondee en",
    "fondée en",
    "founded",
    "814",
    "avant j-c",
    "avant jc",
    "before christ",
    "phoenician",
    "encyclopedia",
    "encyclopedie",
    "wikipedia",
    "britannica",
    "ancient city",
    "ancienne cite",
)


def _strip_web_meta_phrases(user_query: str) -> str:
    working = normalize_text(user_query)
    for hint in sorted(
        WEB_SEARCH_META_PHRASES + SUGGESTED_ACTION_PHRASES_TO_STRIP,
        key=len,
        reverse=True,
    ):
        hint_norm = normalize_text(hint)
        if hint_norm:
            working = working.replace(hint_norm, " ")
    return re.sub(r"\s+", " ", working).strip()


def _looks_like_recent_news_result(blob: str) -> bool:
    if any(marker in blob for marker in NEWS_RESULT_MARKERS):
        return True
    if any(marker in blob for marker in ANCIENT_HISTORY_ONLY_MARKERS):
        return False
    return False


def requests_news_or_recent(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(hint in normalized for hint in NEWS_OR_RECENT_HINTS)


def _combined_query_text(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> str:
    parts = [user_query]
    context = memory_context or {}
    last_message = context.get("last_substantive_user_message")
    if last_message:
        parts.append(str(last_message))
    return normalize_text(" ".join(parts))


def requests_archaeology_news(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> bool:
    combined = _combined_query_text(user_query, memory_context)
    if not any(marker in combined for marker in ARCHAEOLOGY_QUERY_MARKERS):
        return False
    return "carthage" in combined or "tunisie" in combined


def is_incomplete_lookup_follow_up(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> bool:
    if not user_requests_lookup(user_query):
        return False
    context = memory_context or {}
    last_message = context.get("last_substantive_user_message")
    if not last_message:
        return False
    current = normalize_text(_strip_lookup_prefix(user_query))
    if not current or len(current) > 55:
        return False
    if "carthage" in normalize_text(user_query):
        return False
    last_norm = normalize_text(str(last_message))
    return "carthage" in last_norm or any(
        marker in last_norm for marker in ARCHAEOLOGY_QUERY_MARKERS
    )


def is_archaeology_lookup_follow_up(user_query: str) -> bool:
    if not user_requests_lookup(user_query):
        return False
    current = normalize_text(_strip_lookup_prefix(user_query))
    if not current:
        return False
    return any(marker in current for marker in ARCHAEOLOGY_QUERY_MARKERS)


def requests_event_or_schedule(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    if "journ" in normalized and "cinematograph" in normalized:
        return True
    has_year = any(year in normalized for year in ("2024", "2025", "2026", "2027"))
    has_event = any(hint in normalized for hint in EVENT_OR_SCHEDULE_HINTS)
    return has_year and has_event


def user_requests_lookup(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(normalized.startswith(prefix) for prefix in LOOKUP_INTENT_PREFIXES)


def uses_demonstrative_reference(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(phrase in normalized for phrase in DEMONSTRATIVE_MONUMENT_PHRASES)


def references_session_monument(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> bool:
    """True when the user refers to the monument already in session memory."""
    if not _resolve_demonstrative_monument(memory_context):
        return False
    if uses_demonstrative_reference(user_query):
        return True
    normalized = normalize_text(user_query)
    return any(phrase in normalized for phrase in GENERIC_MONUMENT_PHRASES)


def _resolve_generic_subject_to_monument(
    subject_norm: str,
    memory_context: dict[str, Any] | None,
) -> str | None:
    if subject_norm not in GENERIC_TOPIC_STOPWORDS and subject_norm not in DEMONSTRATIVE_SUBJECTS:
        return None
    monument = _resolve_demonstrative_monument(memory_context)
    if monument:
        return normalize_text(monument)
    return None


def _resolve_demonstrative_monument(memory_context: dict[str, Any] | None) -> str | None:
    context = memory_context or {}
    monuments = context.get("last_mentioned_monuments") or []
    if monuments:
        return str(monuments[0]).strip()
    primary_site = context.get("primary_site_name")
    if primary_site:
        return str(primary_site).strip()
    return None


def _strip_lookup_prefix(user_query: str) -> str:
    normalized = normalize_text(user_query)
    for prefix in LOOKUP_INTENT_PREFIXES:
        if normalized.startswith(prefix):
            return user_query[len(prefix) :].strip()
    return user_query.strip()


def _monument_matches_blob(monument: str, blob: str) -> bool:
    monument_norm = normalize_text(monument)
    if not monument_norm:
        return False
    if monument_norm in blob:
        return True
    tokens = [token for token in monument_norm.split() if len(token) > 3]
    return bool(tokens) and all(_term_matches_blob(token, blob) for token in tokens)


def _resolve_art_monument_anchor(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> str | None:
    if references_session_monument(user_query, memory_context):
        return _resolve_demonstrative_monument(memory_context)
    if not is_art_or_culture_query(user_query, memory_context):
        return None
    user_norm = normalize_text(user_query)
    context = memory_context or {}
    for monument in context.get("last_mentioned_monuments") or []:
        if _monument_matches_blob(str(monument), user_norm):
            return str(monument).strip()
    subject = _extract_subject_from_query(user_query, memory_context)
    subject_norm = normalize_text(subject)
    if subject and subject_norm not in GENERIC_TOPIC_STOPWORDS:
        return subject
    return None


def _is_offsite_exhibition_result(content_blob: str, url: str) -> bool:
    blob = normalize_text(f"{content_blob} {url}")
    return any(marker in blob for marker in OFFSITE_EXHIBITION_MARKERS)


def _should_enforce_monument_web_match(
    monument_anchor: str,
    user_query: str,
    memory_context: dict[str, Any] | None,
) -> bool:
    if references_session_monument(user_query, memory_context):
        return True
    anchor_norm = normalize_text(monument_anchor)
    user_norm = normalize_text(user_query)
    if anchor_norm in user_norm:
        return True
    tokens = [
        token
        for token in anchor_norm.split()
        if len(token) > 3 and token not in GENERIC_TOPIC_STOPWORDS
    ]
    if len(tokens) == 1 and _is_salammbo_related(anchor_norm):
        return False
    return len(tokens) >= 2


def _content_has_archaeology_news(content_blob: str) -> bool:
    has_archaeology = any(marker in content_blob for marker in LOCAL_TOPIC_HINTS) or any(
        marker in content_blob for marker in ("archeolog", "excavat", "fouill", "decouverte")
    )
    if not has_archaeology:
        return False
    tourism_only = any(
        marker in content_blob
        for marker in (
            "visitez les sites",
            "planifier votre visite",
            "circuit tourist",
            "destination tunis",
            "sites touristiques",
        )
    )
    if tourism_only and not any(
        marker in content_blob for marker in NEWS_RESULT_MARKERS
    ):
        return False
    return True


def is_vague_web_follow_up(user_query: str) -> bool:
    if not user_requests_web_search(user_query):
        return False
    normalized = normalize_text(user_query)
    if any(phrase in normalized for phrase in VAGUE_FOLLOW_UP_PHRASES):
        return True
    stripped = _strip_web_meta_phrases(user_query)
    tokens = [
        token
        for token in stripped.split()
        if token and token not in WEB_SEARCH_FILLER_TOKENS
    ]
    if not tokens:
        return True
    return len(tokens) <= 2 and all(token in VAGUE_FOLLOW_UP_TOKENS for token in tokens)


def is_substantive_user_message(user_query: str) -> bool:
    if is_vague_web_follow_up(user_query):
        return False
    normalized = normalize_text(user_query)
    if len(normalized) < 10:
        return False
    stripped = _strip_web_meta_phrases(user_query)
    tokens = [
        token
        for token in stripped.split()
        if token and token not in TOPIC_STOPWORDS and len(token) > 2
    ]
    if len(tokens) >= 2:
        return True
    return any(keyword in normalized for keyword in DOMAIN_KEYWORDS)


def _query_mentions_art(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(marker in normalized for marker in ART_CULTURE_QUERY_MARKERS)


def resolve_query_for_context(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> str:
    """Resolve vague web follow-ups and demonstrative monument references."""
    context = memory_context or {}
    if is_vague_web_follow_up(user_query):
        last_message = context.get("last_substantive_user_message")
        if last_message:
            return str(last_message).strip()

    if is_archaeology_lookup_follow_up(user_query):
        resolved = "dernieres fouilles et decouvertes archeologiques a Carthage Tunisie"
        last_message = context.get("last_substantive_user_message")
        if last_message:
            last_norm = normalize_text(str(last_message))
            for year in ("2026", "2025", "2024", "2027"):
                if year in last_norm:
                    return f"{resolved} {year}"
        return resolved

    if is_incomplete_lookup_follow_up(user_query, context):
        return str(context["last_substantive_user_message"]).strip()

    if references_session_monument(user_query, context):
        monument = _resolve_demonstrative_monument(context)
        if monument:
            if _query_mentions_art(user_query):
                return f"oeuvres artistiques liees au {monument} Carthage"
            last_message = context.get("last_substantive_user_message")
            if last_message and _monument_matches_blob(
                monument,
                normalize_text(str(last_message)),
            ):
                return str(last_message).strip()
            stripped = _strip_lookup_prefix(user_query)
            monument_norm = normalize_text(monument)
            if monument_norm not in normalize_text(stripped):
                return f"{stripped} {monument}".strip()
            return stripped

    return user_query.strip()


def is_historical_figure_query(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(marker in normalized for marker in HISTORICAL_FIGURE_MARKERS)


def _requests_news_or_recent(user_query: str) -> bool:
    return requests_news_or_recent(user_query)


def _extract_topic_terms(user_query: str) -> tuple[str, ...]:
    working = _strip_web_meta_phrases(user_query)
    tokens = [token for token in working.split() if token and token not in TOPIC_STOPWORDS]
    return tuple(tokens[:6])


def _extract_subject_from_query(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> str:
    context = memory_context or {}
    effective_query = resolve_query_for_context(user_query, context)
    working = _strip_web_meta_phrases(effective_query)
    match = re.search(
        r"\b(?:sur|du|de la|de l|des|d|about|related to|for|"
        r"liees au|liées au|liee au|liée au|"
        r"liees a|liées à|liee a|liée à)\s+(.+)$",
        working,
        flags=re.IGNORECASE,
    )
    if match:
        subject = re.sub(r"\s+", " ", match.group(1)).strip()
        if subject:
            subject_norm = normalize_text(subject)
            resolved = _resolve_generic_subject_to_monument(subject_norm, context)
            if resolved:
                return resolved
            if subject_norm in DEMONSTRATIVE_SUBJECTS or uses_demonstrative_reference(
                subject
            ):
                monument = _resolve_demonstrative_monument(context)
                if monument:
                    return normalize_text(monument)
            return subject

    if references_session_monument(user_query, context):
        monument = _resolve_demonstrative_monument(context)
        if monument:
            return normalize_text(monument)

    last_monuments = context.get("last_mentioned_monuments") or []
    if last_monuments and is_vague_web_follow_up(user_query):
        monument = normalize_text(str(last_monuments[0]))
        if monument:
            return monument

    terms = _extract_topic_terms(effective_query)
    return " ".join(terms)


def is_art_or_culture_query(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> bool:
    return _query_mentions_art(user_query)


def is_salammbo_query(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(token in normalized for token in ("salamm", "salambo"))


def _is_blocked_web_url(url: str) -> bool:
    normalized = normalize_text(url)
    return any(domain in normalized for domain in BLOCKED_WEB_DOMAINS)


def _is_blocked_web_result(title: str, url: str, snippet: str) -> bool:
    if _is_blocked_web_url(url):
        return True
    blob = normalize_text(f"{title} {snippet}")
    return any(marker in blob for marker in BLOCKED_WEB_TITLE_MARKERS)


def _is_salammbo_related(text: str) -> bool:
    return "salamm" in text or "salambo" in text


def _term_matches_blob(term: str, blob: str) -> bool:
    if term in blob:
        return True
    if _is_salammbo_related(term) and _is_salammbo_related(blob):
        return True
    return False


def _focus_topic_terms(topic_terms: tuple[str, ...]) -> tuple[str, ...]:
    focused = tuple(
        term
        for term in topic_terms
        if term not in CONVERSATIONAL_TOPIC_STOPWORDS
        and term not in GENERIC_TOPIC_STOPWORDS
        and len(term) > 3
    )
    if focused:
        return focused
    return tuple(term for term in topic_terms if len(term) > 3)


def _is_recipe_or_cooking_result(blob: str) -> bool:
    return any(marker in blob for marker in RECIPE_WEB_MARKERS)


def _content_has_art_markers(content_blob: str) -> bool:
    """Detect art-related content without matching 'art' inside unrelated words."""
    if any(marker in content_blob for marker in STRONG_WEB_ART_CONTENT_MARKERS):
        return True
    return bool(re.search(r"\barts?\b", content_blob))


def _content_matches_art_topic(
    content_blob: str,
    topic_terms: tuple[str, ...],
) -> bool:
    focused_terms = _focus_topic_terms(topic_terms)
    if not focused_terms:
        return True
    return any(_term_matches_blob(term, content_blob) for term in focused_terms)


def _build_salammbo_web_queries(user_query: str) -> list[str]:
    normalized = normalize_text(user_query)
    queries = [
        "Salammbo Flaubert Carthage roman",
        "Salammbo art Carthage Tunisie",
    ]
    if any(name in normalized for name in ("gussier", "gussiere", "bastien", "baston")):
        queries.insert(0, "Bastien Gussier artiste Salammbo")
    return queries


def _requires_strict_topic_match(topic_terms: tuple[str, ...]) -> bool:
    if not topic_terms:
        return False
    archaeology_markers = ("fouill", "archeolog", "excavat")
    return not all(
        any(marker in term for marker in archaeology_markers) for term in topic_terms
    )


def build_web_search_query(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> str:
    """Build a focused DuckDuckGo query by removing online-search meta phrasing."""
    context = memory_context or {}
    effective_query = resolve_query_for_context(user_query, context)
    normalized_query = normalize_text(effective_query)

    working = _strip_web_meta_phrases(effective_query)
    tokens = working.split()
    while tokens and tokens[0] in WEB_SEARCH_FILLER_TOKENS:
        tokens.pop(0)
    working = " ".join(tokens).strip()

    if not working:
        working = _extract_subject_from_query(user_query, context) or normalized_query
    if "carthage" in normalized_query and (
        "fouill" in normalized_query or "archeolog" in normalized_query
    ):
        parts = ["fouilles archeologiques Carthage Tunisie"]
        if any(
            token in normalized_query
            for token in ("recent", "recente", "recentes", "actualite", "actualites")
        ):
            parts.append("actualites")
        for year in ("2026", "2025", "2024", "2027"):
            if year in normalized_query:
                parts.append(year)
                break
        return " ".join(parts)

    if is_salammbo_query(user_query):
        salammbo_queries = _build_salammbo_web_queries(user_query)
        return salammbo_queries[0]

    if requests_event_or_schedule(user_query):
        if "cinematograph" in normalized_query or "jcc" in normalized_query:
            return "Journees Cinematographiques Carthage 2026 dates"
        return f"{working or 'evenements Carthage'} Carthage Tunisie 2026"

    if _requests_news_or_recent(user_query) or requests_archaeology_news(
        user_query, context
    ):
        if "carthage" in normalized_query or requests_archaeology_news(
            user_query, context
        ):
            query = "fouilles archeologiques Carthage Tunisie actualites"
            if any(year in normalized_query for year in ("2024", "2025", "2026", "2027")):
                for year in ("2026", "2025", "2024", "2027"):
                    if year in normalized_query:
                        return f"{query} {year}"
            return query
        subject = _extract_subject_from_query(user_query, context)
        if subject:
            return f"{subject} Carthage actualites recentes"

    if is_art_or_culture_query(user_query, context):
        subject = _extract_subject_from_query(user_query, context) or working
        if subject:
            return f"{subject} art Carthage Tunisie"

    parts = [working]
    last_monuments = context.get("last_mentioned_monuments") or []
    if last_monuments:
        monument = normalize_text(str(last_monuments[0]))
        if monument and monument not in working:
            parts.append(monument)

    return " ".join(part for part in parts if part).strip()


def build_web_search_queries(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> list[str]:
    """Return ordered DuckDuckGo queries, with optional English fallback."""
    queries: list[str] = []
    primary = build_web_search_query(user_query, memory_context)
    if primary:
        queries.append(primary)

    normalized_query = normalize_text(user_query)
    effective_norm = normalize_text(
        resolve_query_for_context(user_query, memory_context)
    )
    if "carthage" in effective_norm and (
        "fouill" in effective_norm or "archeolog" in effective_norm
    ):
        queries.append("Carthage archaeological excavation Tunisia")
        if any(
            token in effective_norm
            for token in ("recent", "recente", "recentes", "actualite", "actualites")
        ):
            queries.append("Carthage archaeology news excavation")

    if _requests_news_or_recent(user_query) or requests_archaeology_news(
        user_query, memory_context
    ):
        queries.append("Carthage Tunisia archaeology news")
        queries.append("Carthage Tunisie actualites patrimoine")
        if "2026" in effective_norm:
            queries.append("Carthage archaeological discovery 2026")
    if is_salammbo_query(user_query):
        queries.extend(_build_salammbo_web_queries(user_query))
    if is_art_or_culture_query(user_query, memory_context):
        subject = _extract_subject_from_query(user_query, memory_context)
        subject_norm = normalize_text(subject)
        if subject and subject_norm not in GENERIC_TOPIC_STOPWORDS:
            queries.append(f"{subject} mosaïques sculpture Carthage")
            queries.append(f"{subject} art roman Tunisie")
        if subject and "tophet" in subject_norm:
            queries.append("Tophet Carthage art stèles sculpture")
            queries.append("Tophet Carthage Salammbo Flaubert art")
    if "tophet" in normalized_query:
        queries.append("Tophet Carthage Tunisia sanctuary")
    if user_requests_web_search(user_query) and "carthage" not in normalized_query:
        subject = _strip_web_meta_phrases(user_query)
        primary_key = normalize_text(primary)
        subject_key = normalize_text(subject)
        if (
            subject_key
            and subject_key != primary_key
            and subject_key not in primary_key
            and primary_key not in subject_key
        ):
            queries.append(subject)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = normalize_text(query)
        if not key or key in seen:
            continue
        seen.add(key)
        deduplicated.append(query)
    return deduplicated


def build_emergency_web_queries(user_query: str) -> list[str]:
    normalized_query = normalize_text(user_query)
    if "carthage" not in normalized_query:
        return []

    queries = [
        "Carthage Tunisia archaeology excavation news",
        "Carthage fouilles archeologiques actualites",
    ]
    if any(
        token in normalized_query
        for token in ("recent", "recente", "recentes", "actualite", "actualites")
    ):
        queries.insert(0, "Carthage archaeological discovery recent news")

    deduplicated: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = normalize_text(query)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(query)
    return deduplicated


def region_for_web_query(query: str, default_region: str) -> str:
    normalized_query = normalize_text(query)
    english_markers = (
        "archaeological",
        "archaeology",
        "excavation",
        "discovery",
        "news",
        "recent",
    )
    if any(marker in normalized_query for marker in english_markers):
        return "wt-wt"
    return default_region


def _extract_web_relevance_anchors(query_norm: str) -> tuple[str, ...]:
    if "carthage" in query_norm:
        return ("carthage", "tunisie", "tunisia", "tunis")
    if any(token in query_norm for token in ("tunisie", "tunisien", "tunisienne")):
        return ("tunisie", "tunisia", "carthage", "tunis")
    if any(marker in query_norm for marker in ARCHAEOLOGY_QUERY_MARKERS):
        return ("carthage", "tunisie", "tunisia", "tunis")
    if any(keyword in query_norm for keyword in DOMAIN_KEYWORDS):
        return ("carthage", "tunisie", "tunisia", "tunis")
    return ()


def _ensure_carthage_anchors(
    anchors: tuple[str, ...],
    *,
    user_query: str,
    memory_context: dict[str, Any] | None = None,
    explicit_request: bool = False,
) -> tuple[str, ...]:
    if anchors:
        return anchors
    if (
        explicit_request
        or is_domain_related_query(user_query, memory_context)
        or requests_archaeology_news(user_query, memory_context)
    ):
        return ("carthage", "tunisie", "tunisia", "tunis")
    return anchors


def _is_off_topic_science_result(
    url: str,
    content_blob: str,
    *,
    require_local_anchor: bool,
) -> bool:
    if not require_local_anchor:
        return False
    url_norm = normalize_text(url)
    if not any(domain in url_norm for domain in GENERIC_SCIENCE_WEB_DOMAINS):
        return False
    return not any(
        anchor in content_blob for anchor in ("carthage", "tunisie", "tunisia", "tunis")
    )


def _collect_topic_terms(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    effective_query = resolve_query_for_context(user_query, memory_context)
    terms: list[str] = list(_extract_topic_terms(effective_query))
    subject = _extract_subject_from_query(user_query, memory_context)
    if subject:
        terms.extend(token for token in subject.split() if token not in TOPIC_STOPWORDS)

    context = memory_context or {}
    if not requests_archaeology_news(user_query, memory_context):
        for monument in context.get("last_mentioned_monuments") or []:
            terms.extend(
                token
                for token in normalize_text(str(monument)).split()
                if token not in TOPIC_STOPWORDS
            )

    deduplicated: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if not term or term in seen:
            continue
        seen.add(term)
        deduplicated.append(term)
    return tuple(deduplicated[:8])


def filter_relevant_web_results(
    results: list[Any],
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> list[Any]:
    """Keep only web results that mention Carthage/Tunisia and the requested topic."""
    if not results:
        return []

    explicit_request = user_requests_web_search(user_query)
    effective_query = resolve_query_for_context(user_query, memory_context)
    normalized_query = normalize_text(effective_query)
    anchors = _ensure_carthage_anchors(
        _extract_web_relevance_anchors(normalized_query),
        user_query=user_query,
        memory_context=memory_context,
        explicit_request=explicit_request,
    )
    require_local_anchor = (
        requests_archaeology_news(user_query, memory_context)
        or explicit_request
        or is_domain_related_query(user_query, memory_context)
    )
    topic_terms = _focus_topic_terms(_collect_topic_terms(user_query, memory_context))
    art_query = is_art_or_culture_query(user_query, memory_context)
    monument_anchor: str | None = None
    if art_query:
        monument_anchor = _resolve_art_monument_anchor(user_query, memory_context)
    archaeology_query = requests_archaeology_news(user_query, memory_context)
    filtered: list[Any] = []
    for result in results:
        title = getattr(result, "title", "") or ""
        snippet = getattr(result, "snippet", "") or ""
        url = getattr(result, "url", "") or ""
        if _is_blocked_web_result(title, url, snippet):
            continue

        blob = normalize_text(f"{title} {snippet} {url}")
        content_blob = normalize_text(f"{title} {snippet}")
        if _is_off_topic_science_result(
            url,
            content_blob,
            require_local_anchor=require_local_anchor,
        ):
            continue
        if art_query and _is_recipe_or_cooking_result(blob):
            continue
        if art_query:
            if any(domain in normalize_text(url) for domain in TOURISM_WEB_DOMAINS):
                continue
            if _is_offsite_exhibition_result(content_blob, url):
                continue
            if not _content_has_art_markers(content_blob):
                continue
            if not _content_matches_art_topic(content_blob, topic_terms):
                continue
            if monument_anchor and _should_enforce_monument_web_match(
                monument_anchor, user_query, memory_context
            ) and not _monument_matches_blob(monument_anchor, content_blob):
                continue
        if archaeology_query:
            if any(domain in normalize_text(url) for domain in TOURISM_WEB_DOMAINS):
                continue
            query_mentions_digs = any(
                marker in normalized_query for marker in ARCHAEOLOGY_QUERY_MARKERS
            )
            has_carthage_focus = query_mentions_digs and "carthage" in content_blob
            if not _content_has_archaeology_news(content_blob) and not has_carthage_focus:
                continue
            if has_carthage_focus and not _content_has_archaeology_news(content_blob):
                tourism_only = any(
                    marker in content_blob
                    for marker in (
                        "visitez les sites",
                        "planifier votre visite",
                        "sites touristiques",
                        "destination tunis",
                    )
                )
                if tourism_only:
                    continue
        if anchors:
            if not any(anchor in blob for anchor in anchors):
                continue
        else:
            continue
        if (
            _requires_strict_topic_match(topic_terms)
            and not _requests_news_or_recent(user_query)
            and not archaeology_query
            and not any(_term_matches_blob(term, blob) for term in topic_terms)
        ):
            continue
        if (
            _requests_news_or_recent(user_query)
            and not archaeology_query
            and not _looks_like_recent_news_result(blob)
        ):
            continue
        filtered.append(result)
    return filtered


LOCAL_TOPIC_HINTS = (
    "fouill",
    "excavation",
    "chantier",
    "decouverte",
    "découverte",
    "recent",
    "recente",
    "actualite",
    "actualités",
)


def local_chunks_relevant_to_query(
    user_query: str,
    retrieved_chunks: list[dict[str, Any]],
    memory_context: dict[str, Any] | None = None,
) -> bool:
    effective_query = resolve_query_for_context(user_query, memory_context)
    query_norm = normalize_text(effective_query)
    if not retrieved_chunks:
        return False

    if requests_archaeology_news(user_query, memory_context):
        for chunk in retrieved_chunks:
            blob = normalize_text(
                f"{chunk.get('title', '')} {chunk.get('chunk_text', '')}"
            )
            if not any(hint in blob for hint in LOCAL_TOPIC_HINTS):
                continue
            if any(
                anchor in blob for anchor in ("carthage", "tunisie", "tunisia", "tunis")
            ):
                return True
        return False

    if is_art_or_culture_query(user_query, memory_context):
        art_terms = tuple(
            marker
            for marker in ART_CULTURE_QUERY_MARKERS
            if marker in query_norm
        )
        topic_terms = tuple(
            term
            for term in _collect_topic_terms(user_query, memory_context)
            if len(term) > 3
            and term not in {"circuit", "circuits", "romain", "romaine"}
            and term not in GENERIC_TOPIC_STOPWORDS
        )
        monument_anchor = (
            _resolve_demonstrative_monument(memory_context)
            if references_session_monument(user_query, memory_context)
            else None
        )
        for chunk in retrieved_chunks:
            blob = normalize_text(
                f"{chunk.get('title', '')} {chunk.get('chunk_text', '')}"
            )
            if monument_anchor and not _monument_matches_blob(monument_anchor, blob):
                continue
            has_art_content = any(marker in blob for marker in ART_CULTURE_QUERY_MARKERS)
            has_topic = not topic_terms or any(term in blob for term in topic_terms)
            if has_art_content and has_topic:
                return True
            if art_terms and has_topic and any(term in blob for term in art_terms):
                return True
        return False

    query_terms = tuple(
        term
        for term in _collect_topic_terms(user_query, None)
        if len(term) > 3 and term not in {"circuit", "circuits", "romain", "romaine"}
    )
    if query_terms:
        for chunk in retrieved_chunks:
            blob = normalize_text(
                f"{chunk.get('title', '')} {chunk.get('chunk_text', '')}"
            )
            if any(term in blob for term in query_terms):
                return True
        return False

    asks_specific_topic = any(hint in query_norm for hint in LOCAL_TOPIC_HINTS)
    if not asks_specific_topic:
        return True

    for chunk in retrieved_chunks:
        blob = normalize_text(
            f"{chunk.get('title', '')} {chunk.get('chunk_text', '')}"
        )
        if any(hint in blob for hint in LOCAL_TOPIC_HINTS):
            return True
    return False


def user_requests_web_search(user_query: str) -> bool:
    normalized = normalize_text(user_query)
    return any(hint in normalized for hint in WEB_SEARCH_META_PHRASES) or any(
        hint in normalized for hint in NEWS_OR_RECENT_HINTS
    )


def user_requests_art_web_lookup(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> bool:
    """English/French art lookup follow-ups that imply an online search."""
    if not user_requests_lookup(user_query):
        return False
    if not is_art_or_culture_query(user_query, memory_context):
        return False
    context = memory_context or {}
    return references_session_monument(user_query, context) or is_incomplete_lookup_follow_up(
        user_query, context
    )


def is_domain_related_query(
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> bool:
    context = memory_context or {}
    parts = [user_query]
    if context.get("last_substantive_user_message"):
        parts.append(str(context["last_substantive_user_message"]))
    parts.extend(str(item) for item in (context.get("last_mentioned_monuments") or []))
    parts.extend(str(item) for item in (context.get("interests") or []))
    if context.get("primary_site_name"):
        parts.append(str(context["primary_site_name"]))

    normalized_blob = normalize_text(" ".join(parts))
    return any(keyword in normalized_blob for keyword in DOMAIN_KEYWORDS)


def _chunks_are_too_short(retrieved_chunks: list[dict[str, Any]]) -> bool:
    if not retrieved_chunks:
        return True

    total_chars = sum(len(str(chunk.get("chunk_text") or "")) for chunk in retrieved_chunks)
    if total_chars < MIN_TOTAL_CHUNK_CHARS:
        return True

    return any(
        len(str(chunk.get("chunk_text") or "")) < MIN_SINGLE_CHUNK_CHARS
        for chunk in retrieved_chunks
    )


def _chunks_have_weak_descriptive_content(retrieved_chunks: list[dict[str, Any]]) -> bool:
    if not retrieved_chunks:
        return True

    for chunk in retrieved_chunks:
        normalized_text = normalize_text(str(chunk.get("chunk_text") or ""))
        if not normalized_text:
            return True
        if any(hint in normalized_text for hint in HISTORICAL_CONTENT_HINTS):
            return False
    return True


def is_local_context_insufficient(
    retrieved_chunks: list[dict[str, Any]],
    best_score: float | None,
    *,
    min_relevance_score: float,
) -> bool:
    if not retrieved_chunks:
        return True
    if best_score is None or best_score < min_relevance_score:
        return True
    if _chunks_are_too_short(retrieved_chunks):
        return True
    if _chunks_have_weak_descriptive_content(retrieved_chunks):
        return True
    return False


def filter_sources_for_query(
    sources: list[Any],
    user_query: str,
    memory_context: dict[str, Any] | None = None,
) -> list[Any]:
    """Drop unrelated monument sources when the question targets a specific topic."""
    if not sources:
        return sources

    needs_filter = is_art_or_culture_query(
        user_query, memory_context
    ) or user_requests_web_search(user_query)
    if not needs_filter:
        return sources

    topic_terms = _focus_topic_terms(_collect_topic_terms(user_query, memory_context))
    monument_anchor = (
        _resolve_demonstrative_monument(memory_context)
        if references_session_monument(user_query, memory_context)
        else None
    )
    if monument_anchor:
        topic_terms = tuple(
            token
            for token in normalize_text(monument_anchor).split()
            if len(token) > 3 and token not in GENERIC_TOPIC_STOPWORDS
        ) or topic_terms
    if not topic_terms:
        return sources

    filtered: list[Any] = []
    art_query = is_art_or_culture_query(user_query, memory_context)
    for source in sources:
        source_type = getattr(source, "source_type", None) or source.get("source_type")
        if source_type == "web":
            if art_query:
                url = getattr(source, "url", None) or source.get("url") or ""
                title = getattr(source, "title", None) or source.get("title") or ""
                url_norm = normalize_text(str(url))
                if any(domain in url_norm for domain in TOURISM_WEB_DOMAINS):
                    continue
                content_blob = normalize_text(str(title))
                if content_blob and not _content_has_art_markers(content_blob):
                    continue
            filtered.append(source)
            continue
        title = getattr(source, "title", None) or source.get("title") or ""
        title_norm = normalize_text(str(title))
        if monument_anchor and _monument_matches_blob(monument_anchor, title_norm):
            filtered.append(source)
            continue
        if any(term in title_norm for term in topic_terms):
            filtered.append(source)

    return filtered if filtered else list(sources)


def should_use_web_search(
    user_query: str,
    retrieved_chunks: list[dict[str, Any]],
    best_score: float | None,
    memory_context: dict[str, Any],
    *,
    settings: Settings,
) -> bool:
    explicit_request = user_requests_web_search(user_query) or user_requests_art_web_lookup(
        user_query, memory_context
    )
    if explicit_request:
        return True

    if not is_domain_related_query(user_query, memory_context):
        return False

    local_irrelevant = not local_chunks_relevant_to_query(
        user_query, retrieved_chunks, memory_context
    )
    insufficient = is_local_context_insufficient(
        retrieved_chunks,
        best_score,
        min_relevance_score=settings.rag_min_score,
    )
    if insufficient or local_irrelevant:
        return True

    if not settings.web_search_enabled:
        return False

    if requests_archaeology_news(user_query, memory_context):
        return True

    if is_art_or_culture_query(user_query, memory_context) and not local_chunks_relevant_to_query(
        user_query, retrieved_chunks, memory_context
    ):
        return True

    if is_historical_figure_query(user_query) and not local_chunks_relevant_to_query(
        user_query, retrieved_chunks, memory_context
    ):
        return True

    if requests_event_or_schedule(user_query) or (
        user_requests_lookup(user_query) and is_domain_related_query(user_query, memory_context)
    ):
        return True

    return False
