from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.agents.circuit_agent import CircuitAgent, CircuitAgentError
from app.api.routes_chat import _database_error_detail
from app.database import get_db
from app.schemas.circuit_agent import (
    CircuitRecommendationRequest,
    CircuitRecommendationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/circuits", tags=["circuits"])


@router.post("/recommend", response_model=CircuitRecommendationResponse)
def recommend_circuit(
    request: CircuitRecommendationRequest,
    db: Session = Depends(get_db),
) -> CircuitRecommendationResponse:
    logger.info(
        "Circuit recommend session=%s transport=%s budget=%s",
        request.session_id,
        request.transport,
        request.budget_max,
    )
    try:
        agent = CircuitAgent(db)
        result = agent.recommend(request)
        return result.response
    except CircuitAgentError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OperationalError as exc:
        db.rollback()
        logger.exception("Database connection error during circuit recommendation")
        raise HTTPException(
            status_code=503,
            detail=_database_error_detail(exc),
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected circuit recommendation error")
        raise HTTPException(
            status_code=500,
            detail="Une erreur interne est survenue lors de la recommandation de circuit.",
        ) from exc
