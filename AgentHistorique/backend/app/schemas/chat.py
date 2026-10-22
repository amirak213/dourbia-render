from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=2000)
    language: str = Field(
        default="auto",
        min_length=2,
        max_length=10,
        description="Response language hint: auto, fr, en, or ar.",
    )

    @field_validator("session_id", "message")
    @classmethod
    def strip_required_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            return "auto"
        return cleaned


class SourceRefSchema(BaseModel):
    source_type: Literal["monument", "circuit", "web"]
    source_id: float | None = Field(
        default=None,
        description="Dataset identifier; may be fractional (e.g. 3.9 for a sub-monument).",
    )
    title: str | None = None
    score: float | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validate_source_fields(self) -> SourceRefSchema:
        if self.source_type == "web":
            if self.url is None and not self.title:
                raise ValueError("web sources require a title or url")
            return self

        if self.source_id is None:
            raise ValueError(f"{self.source_type} sources require source_id")
        if self.score is None:
            raise ValueError(f"{self.source_type} sources require score")
        return self


class MemoryContextSchema(BaseModel):
    preferred_language: str = "fr"
    interests: list[str] = Field(default_factory=list)
    available_time_minutes: int | None = None
    mobility_mode: str | None = None
    last_mentioned_monuments: list[str] = Field(default_factory=list)
    primary_site_id: int | None = None
    primary_site_name: str | None = None
    last_substantive_user_message: str | None = None


class LatencyDebugSchema(BaseModel):
    memory_retrieval_ms: float | None = None
    retrieval_ms: float | None = None
    prompt_construction_ms: float | None = None
    llm_generation_ms: float | None = None
    memory_update_ms: float | None = None
    web_search_ms: float | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[SourceRefSchema]
    memory_context: MemoryContextSchema
    suggested_actions: list[str]
    latency_ms: float | None = None
    latency_debug: LatencyDebugSchema | None = None
