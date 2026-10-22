from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import engine

router = APIRouter(tags=["health"])


def _database_status() -> tuple[str, str | None]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok", None
    except OperationalError as exc:
        message = str(exc).lower()
        if "connection timeout" in message or "connection refused" in message:
            return (
                "unavailable",
                "PostgreSQL est injoignable. Lancez Docker puis: docker compose up -d",
            )
        return "unavailable", "La base de données est temporairement indisponible."


@router.get("/health")
def health_check() -> dict[str, str]:
    db_status, db_detail = _database_status()
    payload: dict[str, str] = {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
    }
    if db_detail:
        payload["database_detail"] = db_detail
    return payload
