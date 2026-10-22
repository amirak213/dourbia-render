from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.routes_chat import _database_error_detail
from app.database import get_db
from app.schemas.monument import MonumentsListResponse
from app.services.monument_service import list_monuments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["monuments"])


@router.get("/monuments", response_model=MonumentsListResponse)
def get_monuments(
    city: str | None = Query(
        default=None,
        description="Filter by computed city: 'carthage' or 'la_marsa'",
    ),
    db: Session = Depends(get_db),
) -> MonumentsListResponse:
    normalized_city = city.lower().strip() if city else None
    if normalized_city is not None and normalized_city not in {"carthage", "la_marsa"}:
        raise HTTPException(
            status_code=422,
            detail="Invalid city. Allowed values: carthage, la_marsa",
        )
    try:
        return list_monuments(db, city=normalized_city)
    except OperationalError as exc:
        logger.exception("Database connection error while listing monuments")
        raise HTTPException(status_code=503, detail=_database_error_detail()) from exc
