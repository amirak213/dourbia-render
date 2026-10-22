from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(TypedDict):
    role: ChatRole
    content: str


class ToolParameterSchema(TypedDict, total=False):
    type: str
    properties: dict[str, Any]
    required: list[str]


class ToolDefinition(TypedDict):
    """JSON-schema tool description, format OpenAI-compatible (valide pour Groq)."""

    name: str
    description: str
    parameters: ToolParameterSchema


ToolChoice = Literal["auto", "required", "none"]


@dataclass(frozen=True)
class ToolCall:
    """Un appel de tool demandé par le modèle, arguments déjà parsés en dict."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMToolResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class LLMClient(Protocol):
    """Abstraction for text completion backends used by HistoricalAgent."""

    @property
    def model_name(self) -> str: ...

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str: ...

    def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        tool_choice: ToolChoice = "auto",
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> LLMToolResponse: ...


class LLMClientError(Exception):
    """Raised when the LLM provider fails or is misconfigured."""


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OLLAMA_BASE_URL = "http://localhost:11434"


class MockLLMClient:
    """Deterministic LLM for tests and offline development."""

    def __init__(
        self,
        response: str = "Réponse de test.",
        model_name: str = "mock",
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        self._response = response
        self._model_name = model_name
        self._tool_calls = tool_calls or []

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        return self._response

    def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        tool_choice: ToolChoice = "auto",
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> LLMToolResponse:
        if self._tool_calls:
            return LLMToolResponse(
                content=None,
                tool_calls=self._tool_calls,
                finish_reason="tool_calls",
            )
        return LLMToolResponse(
            content=self._response,
            tool_calls=[],
            finish_reason="stop",
        )


class OpenAICompatibleLLMClient:
    """HTTP client for OpenAI-compatible chat completion APIs (OpenAI, Groq, etc.)."""

    def __init__(
        self,
        model_name: str,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        reasoning_effort: str | None = None,
        include_reasoning: bool | None = None,
    ) -> None:
        if not api_key.strip():
            raise LLMClientError("LLM API key is required for this provider.")
        self._model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = _build_timeout(timeout_seconds)
        self._reasoning_effort = reasoning_effort
        self._include_reasoning = include_reasoning

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        if self._include_reasoning is not None:
            payload["include_reasoning"] = self._include_reasoning
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise _http_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"].strip()

        except (KeyError, IndexError, AttributeError) as exc:
            raise LLMClientError("Unexpected LLM response format.") from exc
        
        usage = data.get("usage") or {}
        logger.info(
            "[LLM] finish_reason=%s completion_tokens=%s reasoning_tokens=%s max_tokens=%s",
            choice.get("finish_reason"),
            usage.get("completion_tokens"),
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            max_tokens,
        )
        return content
    
    def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        tool_choice: ToolChoice = "auto",
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> LLMToolResponse:
        url = f"{self._base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": _build_openai_tools_payload(tools),
            "tool_choice": tool_choice,
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        if self._include_reasoning is not None:
            payload["include_reasoning"] = self._include_reasoning
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise _http_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, AttributeError) as exc:
            raise LLMClientError("Unexpected LLM response format.") from exc

        content = message.get("content")
        if isinstance(content, str):
            content = content.strip() or None

        tool_calls = _parse_openai_tool_calls(message.get("tool_calls"))
        finish_reason = choice.get("finish_reason") or (
            "tool_calls" if tool_calls else "stop"
        )
        return LLMToolResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )


class OllamaLLMClient:
    """HTTP client for local Ollama chat API."""

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._timeout = _build_timeout(timeout_seconds)

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise _http_status_error(exc, provider_label="Ollama") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Ollama request failed: {exc}") from exc

        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("Unexpected Ollama response format.")
        return content.strip()

    def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        *,
        tool_choice: ToolChoice = "auto",
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> LLMToolResponse:
        # Ollama ignore tool_choice: le modèle décide seul d'appeler ou non un tool
        # (support dépendant du modèle, ex. llama3.1+). Non utilisé en prod chez Didi.
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "tools": _build_openai_tools_payload(tools),
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise _http_status_error(exc, provider_label="Ollama") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Ollama request failed: {exc}") from exc

        message = data.get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            content = content.strip() or None

        tool_calls = _parse_ollama_tool_calls(message.get("tool_calls"))
        finish_reason = "tool_calls" if tool_calls else "stop"
        return LLMToolResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )


def validate_llm_settings(settings: Settings | None = None) -> list[str]:
    """Return human-readable configuration warnings."""
    settings = settings or get_settings()
    provider = settings.llm_provider.strip().lower()
    warnings: list[str] = []

    if provider in {"openai", "groq"} and not settings.llm_api_key.strip():
        warnings.append(
            f"LLM_API_KEY is missing for provider '{provider}'. "
            "Set it in your .env file before calling POST /api/chat."
        )
    return warnings


def create_llm_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    provider = settings.llm_provider.strip().lower()

    if provider == "mock":
        logger.info("Using mock LLM provider (model=%s)", settings.llm_model_name)
        return MockLLMClient(model_name=settings.llm_model_name)

    if provider in {"openai", "groq"}:
        base_url = settings.llm_base_url.strip()
        if not base_url:
            base_url = GROQ_BASE_URL if provider == "groq" else OPENAI_BASE_URL
        logger.info(
            "Using %s LLM provider (model=%s, base_url=%s)",
            provider,
            settings.llm_model_name,
            base_url,
        )
        return OpenAICompatibleLLMClient(
            settings.llm_model_name,
            api_key=settings.llm_api_key,
            base_url=base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            reasoning_effort=settings.llm_reasoning_effort or None,
            include_reasoning=settings.llm_include_reasoning,
        )

    if provider == "ollama":
        base_url = settings.llm_base_url.strip() or OLLAMA_BASE_URL
        logger.info(
            "Using Ollama LLM provider (model=%s, base_url=%s)",
            settings.llm_model_name,
            base_url,
        )
        return OllamaLLMClient(
            settings.llm_model_name,
            base_url=base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    raise LLMClientError(
        f"Unsupported LLM provider: {settings.llm_provider!r}. "
        "Expected 'openai', 'groq', 'ollama', or 'mock'."
    )


def _build_timeout(timeout_seconds: float) -> httpx.Timeout:
    total = max(timeout_seconds, 5.0)
    connect = min(5.0, total)
    read = max(total - connect, 1.0)
    return httpx.Timeout(connect=connect, read=read, write=5.0, pool=5.0)


def _http_status_error(
    exc: httpx.HTTPStatusError,
    *,
    provider_label: str = "LLM",
) -> LLMClientError:
    status = exc.response.status_code
    if status == 401:
        return LLMClientError(
            f"{provider_label} authentication failed. Check LLM_API_KEY in your .env file."
        )
    if status == 429:
        return LLMClientError(
            f"{provider_label} rate limit reached. Try again shortly."
        )
    return LLMClientError(f"{provider_label} request failed with status {status}.")


def _build_openai_tools_payload(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convertit les ToolDefinition internes au format attendu par l'API OpenAI/Groq."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            },
        }
        for tool in tools
    ]


def _parse_openai_tool_calls(
    raw_tool_calls: list[dict[str, Any]] | None,
) -> list[ToolCall]:
    """Parse les tool_calls au format OpenAI/Groq (arguments = string JSON)."""
    if not raw_tool_calls:
        return []

    parsed: list[ToolCall] = []
    for raw in raw_tool_calls:
        try:
            function = raw["function"]
            name = function["name"]
            raw_arguments = function.get("arguments") or "{}"
        except (KeyError, TypeError) as exc:
            raise LLMClientError(
                "Unexpected tool_call format in LLM response."
            ) from exc

        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                f"LLM returned invalid JSON arguments for tool '{name}': {raw_arguments!r}"
            ) from exc

        parsed.append(
            ToolCall(
                id=raw.get("id") or str(uuid.uuid4()),
                name=name,
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    return parsed


def _parse_ollama_tool_calls(
    raw_tool_calls: list[dict[str, Any]] | None,
) -> list[ToolCall]:
    """Parse les tool_calls au format Ollama (arguments = dict déjà parsé, pas de id)."""
    if not raw_tool_calls:
        return []

    parsed: list[ToolCall] = []
    for raw in raw_tool_calls:
        try:
            function = raw["function"]
            name = function["name"]
            arguments = function.get("arguments") or {}
        except (KeyError, TypeError) as exc:
            raise LLMClientError(
                "Unexpected tool_call format in Ollama response."
            ) from exc

        parsed.append(
            ToolCall(
                id=str(uuid.uuid4()),
                name=name,
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    return parsed
