from sqlalchemy import Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class ReferenceCircuit(Base, TimestampMixin):
    """Pre-computed optimized circuits from circuits_optimises.csv (GA warm-start)."""

    __tablename__ = "reference_circuits"

    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    monument_indices: Mapped[list] = mapped_column(JSONB, nullable=False)
    monument_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    monument_names: Mapped[list] = mapped_column(JSONB, nullable=False)
    stop_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    tariff_totals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
