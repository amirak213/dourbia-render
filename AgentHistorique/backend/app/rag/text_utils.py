from __future__ import annotations

import re
import unicodedata

FRENCH_STOPWORDS = frozenset(
    {
        "a",
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "d",
        "dans",
        "de",
        "des",
        "du",
        "en",
        "et",
        "est",
        "il",
        "je",
        "la",
        "le",
        "les",
        "leur",
        "lui",
        "mais",
        "me",
        "mon",
        "ne",
        "on",
        "ou",
        "par",
        "pas",
        "pour",
        "que",
        "qui",
        "qu",
        "quels",
        "quelles",
        "quelle",
        "quel",
        "sa",
        "se",
        "son",
        "sur",
        "te",
        "tu",
        "un",
        "une",
        "y",
        "carthage",
        "visiter",
        "visite",
        "peut",
        "peux",
        "faire",
        "existe",
        "existe-t-il",
        "propose",
        "cherche",
        "parle",
        "moi",
        "temps",
        "peu",
        "combien",
        "faut",
        "sont",
        "the",
    }
)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^\w\s']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(value: str | None) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    tokens = [token for token in normalized.split() if len(token) > 2]
    return [token for token in tokens if token not in FRENCH_STOPWORDS]


def title_matches_query(title: str | None, query: str) -> bool:
    title_norm = normalize_text(title)
    query_norm = normalize_text(query)
    if not title_norm or not query_norm:
        return False
    return title_norm == query_norm or title_norm in query_norm or query_norm in title_norm


def token_overlap_score(query: str, title: str | None, chunk_text: str | None) -> float:
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0

    if title_matches_query(title, query):
        return 1.0

    title_tokens = set(tokenize(title))
    text_tokens = set(tokenize(chunk_text))
    searchable_tokens = title_tokens | text_tokens
    if not searchable_tokens:
        return 0.0

    matched = sum(1 for token in query_tokens if token in searchable_tokens)
    overlap_ratio = matched / len(query_tokens)

    title_matches = sum(1 for token in query_tokens if token in title_tokens)
    title_ratio = title_matches / len(query_tokens)

    if title_ratio >= 0.6:
        return min(1.0, 0.75 + overlap_ratio * 0.25)
    if overlap_ratio >= 0.5:
        return min(1.0, 0.45 + overlap_ratio * 0.45)
    return overlap_ratio * 0.6
