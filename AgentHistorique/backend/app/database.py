from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _engine_url(url: str) -> str:
    """Render fournit postgres(ql)://... : on force le driver psycopg (v3) utilise en local."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url

engine = create_engine(
    _engine_url(settings.database_url),
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": int(settings.database_connect_timeout_seconds),
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
