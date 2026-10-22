from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

_INTERNAL_LABEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bsur le\s+LOCAL_KNOWLEDGE_BASE_CONTEXT\b", re.IGNORECASE),
        "sur notre base documentaire",
    ),
    (
        re.compile(r"\ble\s+LOCAL_KNOWLEDGE_BASE_CONTEXT\b", re.IGNORECASE),
        "notre base documentaire",
    ),
    (
        re.compile(r"\bLOCAL_KNOWLEDGE_BASE_CONTEXT\b", re.IGNORECASE),
        "notre base documentaire",
    ),
    (
        re.compile(r"\ble\s+WEB_SEARCH_CONTEXT\b", re.IGNORECASE),
        "les résultats web",
    ),
    (re.compile(r"\bWEB_SEARCH_CONTEXT\b", re.IGNORECASE), "les résultats web"),
    (re.compile(r"\bMEMORY_CONTEXT\b", re.IGNORECASE), "le contexte de session"),
    (re.compile(r"\bOUTPUT RULES\b", re.IGNORECASE), "les consignes de réponse"),
    (re.compile(r"\bUSER_QUESTION\b", re.IGNORECASE), "votre question"),
)

STRUCTURED_OUTPUT_GUIDELINE = (
    '- Réponds en JSON strict avec le format: {"answer": "ta réponse ici"}.'
)


class StructuredAnswer(BaseModel):
    answer: str


def build_structured_output_guideline(enabled: bool) -> str | None:
    if not enabled:
        return None
    return STRUCTURED_OUTPUT_GUIDELINE


def sanitize_answer_text(answer: str) -> str:
    """Remove internal prompt labels that the LLM may leak into user-facing text."""
    sanitized = answer.strip()
    for pattern, replacement in _INTERNAL_LABEL_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return re.sub(r"\n{3,}", "\n\n", sanitized).strip()


def parse_llm_answer(raw_answer: str, *, structured: bool = False) -> str:
    """Return the plain-text answer, optionally parsing JSON structured output."""
    cleaned = raw_answer.strip()
    if not structured:
        return sanitize_answer_text(cleaned)

    parsed = _try_parse_structured_answer(cleaned)
    if parsed is not None:
        return sanitize_answer_text(parsed)

    logger.warning("Structured LLM output parsing failed; falling back to plain text.")
    return sanitize_answer_text(cleaned)


def _try_parse_structured_answer(raw_answer: str) -> str | None:
    candidates = [raw_answer]
    fenced = _extract_json_fence(raw_answer)
    if fenced:
        candidates.insert(0, fenced)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        try:
            model = StructuredAnswer.model_validate(payload)
        except ValidationError:
            continue

        answer = model.answer.strip()
        if answer:
            return answer

    return None


def _extract_json_fence(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()
