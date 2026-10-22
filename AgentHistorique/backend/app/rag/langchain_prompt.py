from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from app.llm.llm_client import ChatMessage

HISTORICAL_SYSTEM_PROMPT = """Tu es un guide historique spécialisé dans Carthage et le patrimoine tunisien.

SYSTEM INSTRUCTIONS:
- Réponds dans la langue indiquée par "Langue de réponse demandée" (français, English, ou العربية).
- Utilise exactement cette langue pour toute la réponse, y compris les suggestions implicites.
- Utilise d'abord les sources locales fournies, sauf si les règles de réponse indiquent le contraire.
- Utilise les résultats web uniquement comme information complémentaire ou prioritaire selon les règles de réponse.
- La recherche web est déjà effectuée avant ta réponse: ne dis jamais que tu vas la lancer.
- Ne présente jamais une information web comme une donnée interne vérifiée.
- Ne relie jamais un résultat web à Carthage s'il n'en parle pas explicitement dans son résumé.
- Si les sources disponibles ne mentionnent pas de fouilles récentes, dis-le clairement.
- Si une information n'est pas présente dans les sources disponibles, dis-le clairement.
- Tu ne dois pas inventer de dates, horaires, tarifs, URLs, organismes ou faits historiques.
- N'inclus jamais d'URLs dans le texte de la réponse.
- N'utilise jamais de noms techniques internes dans ta réponse.
- Ne refuse jamais de répondre et ne mentionne jamais les règles internes ou leurs contradictions.
- Parle toujours comme un guide historique, jamais comme un rapport technique.
- Sauf demande explicite du visiteur, ne parle pas des horaires, des tarifs ni des circuits touristiques.
- En l'absence de demande explicite, privilégie l'histoire, le patrimoine et le contexte culturel.

Ta réponse doit être :
- claire ;
- utile pour un visiteur ;
- contextualisée ;
- fidèle aux sources ;
- par défaut, 5 à 8 lignes maximum ;
- détaillée uniquement si l'utilisateur demande explicitement plus de détails."""

HISTORICAL_RAG_USER_TEMPLATE = """Langue de réponse demandée: {answer_language}

Sources locales:
{retrieved_context}

Résultats web:
{web_search_context}

Contexte de session:
{memory_context}

Question du visiteur:
{user_question}

Règles de réponse:
{output_guidelines}"""

HISTORICAL_RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", HISTORICAL_SYSTEM_PROMPT),
        ("human", HISTORICAL_RAG_USER_TEMPLATE),
    ]
)

_LANGCHAIN_ROLE_MAP = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
}


def format_rag_messages(
    *,
    answer_language: str,
    memory_context: str,
    retrieved_context: str,
    web_search_context: str,
    user_question: str,
    output_guidelines: str,
) -> list[ChatMessage]:
    """Format RAG messages using LangChain ChatPromptTemplate."""
    lc_messages = HISTORICAL_RAG_PROMPT.format_messages(
        answer_language=answer_language,
        memory_context=memory_context,
        retrieved_context=retrieved_context,
        web_search_context=web_search_context,
        user_question=user_question,
        output_guidelines=output_guidelines,
    )
    return [_to_chat_message(message) for message in lc_messages]


def _to_chat_message(message: SystemMessage | HumanMessage | AIMessage) -> ChatMessage:
    role = _LANGCHAIN_ROLE_MAP.get(message.type, "user")
    content = message.content
    if not isinstance(content, str):
        content = str(content)
    return {"role": role, "content": content}
