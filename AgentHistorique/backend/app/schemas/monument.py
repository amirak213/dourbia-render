from __future__ import annotations

from pydantic import BaseModel, Field


class MonumentSummaryResponse(BaseModel):
    id: float = Field(..., description="Monument identifier (may be fractional)")
    name_fr: str
    name_en: str | None = None
    name_ar: str | None = None
    latitude: float
    longitude: float
    visit_duration_min: float | None = None
    dominant_period: str | None = None
    function: str | None = None
    popularity: float | None = None
    image_url: str | None = None


class MonumentsListResponse(BaseModel):
    monuments: list[MonumentSummaryResponse]
