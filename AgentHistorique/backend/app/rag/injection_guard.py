"""Sanitisation du contenu externe (résultats de recherche web) avant injection
dans un prompt LLM.

Le contenu retourné par un moteur de recherche (titre, extrait, URL) provient
de pages tierces non fiables. Une page peut contenir du texte formulé comme
une instruction ("Ignore les consignes précédentes...", "SYSTEM:", "Tu es
maintenant...") dans l'espoir qu'un LLM qui lit ce texte comme contexte
l'exécute. Ce module ne "comprend" pas le sens du texte (ce n'est pas un
classifieur) : il neutralise la *forme* la plus courante de ces tentatives et
tronque la taille, en défense en profondeur — la vraie barrière reste
l'instruction explicite donnée au LLM dans le system prompt (voir
langchain_prompt.py) de traiter ce contenu comme des données, jamais comme
des ordres.
"""

from __future__ import annotations

import re

# Longueur max d'un extrait/titre web avant troncature. Un extrait de moteur
# de recherche légitime ne dépasse jamais ça ; au-delà, c'est un signal que
# le contenu a été gonflé pour transporter un payload plus long.
MAX_SNIPPET_LENGTH = 600
MAX_TITLE_LENGTH = 200

# Formulations impératives typiques d'une tentative d'injection de prompt.
# Non exhaustif par nature (c'est justement pour ça que la défense principale
# est l'instruction au system prompt, pas cette liste) — ceci casse juste les
# formulations les plus directes pour réduire la surface d'attaque.
_INJECTION_PATTERNS = [
    re.compile(r"ignor[ea]s?\s+(les\s+)?instructions?", re.IGNORECASE),
    re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE
    ),
    re.compile(r"nouvelles?\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\btu\s+es\s+maintenant\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(if\s+you\s+are\s+)?", re.IGNORECASE),
    re.compile(r"agis\s+(désormais\s+)?comme\s+si", re.IGNORECASE),
    re.compile(r"\[/?INST\]|<<SYS>>|<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
    re.compile(r"end\s+of\s+(the\s+)?(system\s+)?prompt", re.IGNORECASE),
]

_NEUTRALIZED_MARKER = "[contenu neutralisé]"


def sanitize_external_text(
    text: str | None, *, max_length: int = MAX_SNIPPET_LENGTH
) -> str:
    """Neutralise les tentatives d'injection et tronque un texte externe.

    À appliquer à toute chaîne provenant d'une source non fiable (résultat de
    recherche web) avant qu'elle n'entre dans un prompt LLM.
    """
    if not text:
        return ""

    cleaned = text.strip()

    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub(_NEUTRALIZED_MARKER, cleaned)

    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "…"

    return cleaned


def wrap_untrusted_block(label: str, content: str) -> str:
    """Entoure un bloc de contenu externe de délimiteurs explicites.

    Les délimiteurs seuls ne suffisent pas à empêcher une injection, mais ils
    donnent au modèle un signal structurel clair (en plus de l'instruction du
    system prompt) pour distinguer "donnée à lire" de "instruction à suivre".
    """
    return (
        f'<web_snippet source="{label}" trust="untrusted">\n{content}\n</web_snippet>'
    )
