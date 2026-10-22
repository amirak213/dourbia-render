from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.monument import Monument


class MonumentDistance(Base, TimestampMixin):
    """Directed edge between two monuments (from distances.csv)."""

    __tablename__ = "monument_distances"
    __table_args__ = (
        UniqueConstraint(
            "from_monument_id",
            "to_monument_id",
            name="uq_monument_distances_from_to",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_monument_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("monuments.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_monument_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("monuments.id", ondelete="CASCADE"),
        nullable=False,
    )
    distance_m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    duration_walk_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    duration_bike_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    duration_car_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    from_monument: Mapped["Monument"] = relationship(
        foreign_keys=[from_monument_id],
        back_populates="outgoing_distances",
    )
    to_monument: Mapped["Monument"] = relationship(
        foreign_keys=[to_monument_id],
        back_populates="incoming_distances",
    )
