"""
prompts.py — Construction des prompts RAG pour l'Agent Historique Dourbia

Adapté depuis langchain_prompt.py de l'agent externe.
Sans dépendance à langchain (utilise le format Groq natif directement).
"""
from __future__ import annotations

from typing import Any

# ─── Messages de fallback multilingues ───────────────────────────────────────
INSUFFICIENT_CONTEXT: dict[str, str] = {
    "fr": (
        "Je ne dispose pas d'informations suffisantes dans ma base documentaire "
        "pour répondre à cette question avec certitude."
    ),
    "en": (
        "I do not have enough information in the local knowledge base "
        "to answer this question with confidence."
    ),
    "ar": (
        "لا أملك معلومات كافية في قاعدة المعرفة المحلية "
        "للإجابة على هذا السؤال بثقة."
    ),
}

SYSTEM_PROMPT = """Tu es un guide historique spécialisé dans Carthage et le patrimoine tunisien.

INSTRUCTIONS :
- Réponds dans la langue indiquée (français, English, ou العربية).
- Utilise uniquement les sources locales fournies dans le contexte.
- Si des résultats web sont fournis, utilise-les comme complément.
- Si une information n'est pas dans les sources, dis-le clairement.
- Ne jamais inventer de dates, horaires, tarifs ou faits historiques.
- N'inclus jamais d'URLs dans ta réponse.
- Réponds comme un guide historique, pas comme un rapport technique.
- Par défaut : 5 à 8 lignes maximum, sauf si plus de détails sont demandés."""

LANGUAGE_LABELS = {
    "fr": "Français",
    "en": "English",
    "ar": "العربية",
}


def build_rag_prompt(
    *,
    query: str,
    chunks: list[dict[str, Any]],
    language: str,
    session_context: dict[str, Any] | None = None,
    web_context: str | None = None,
) -> list[dict[str, str]]:
    """
    Construit la liste de messages pour l'appel Groq.

    Returns:
        Liste de dicts {"role": ..., "content": ...} compatible Groq/OpenAI.
    """
    lang_label = LANGUAGE_LABELS.get(language, "Français")

    # Formater les chunks récupérés
    if chunks:
        sources_text = "\n\n".join(
            f"[Source {i+1} — {c.get('source_type', '?')} — score {c['score']:.2f}]\n"
            f"Titre : {c.get('title') or 'Sans titre'}\n"
            f"{c.get('chunk_text', '')}"
            for i, c in enumerate(chunks)
        )
    else:
        sources_text = "Aucune source locale disponible."

    web_section = f"\n\nRésultats web complémentaires :\n{web_context}" if web_context else ""

    # Contexte session (last monument visité etc.)
    ctx = session_context or {}
    context_lines = []
    if ctx.get("last_mentioned_monuments"):
        context_lines.append(f"Monument récemment mentionné : {ctx['last_mentioned_monuments']}")
    if ctx.get("primary_site_name"):
        context_lines.append(f"Site principal de la session : {ctx['primary_site_name']}")
    memory_section = (
        "\n\nContexte de session :\n" + "\n".join(context_lines)
        if context_lines else ""
    )

    user_content = (
        f"Langue de réponse : {lang_label} ({language})\n\n"
        f"Sources locales :\n{sources_text}"
        f"{web_section}"
        f"{memory_section}\n\n"
        f"Question du visiteur : {query}"
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
