from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.circuit import Circuit
    from app.models.monument import Monument


class CircuitMonument(Base, TimestampMixin):
    """Maps to the live tab_circuit_monument table using normalized monument IDs."""

    __tablename__ = "circuit_monuments"
    __table_args__ = (
        UniqueConstraint("circuit_id", "monument_id", name="uq_circuit_monument"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    circuit_id: Mapped[int] = mapped_column(
        ForeignKey("circuits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    monument_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("monuments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # Ordre

    circuit: Mapped["Circuit"] = relationship(back_populates="monument_links")
    monument: Mapped["Monument"] = relationship(back_populates="circuit_links")

    @property
    def normalized_monument_id(self) -> str:
        """Convert the live double-valued monument id to the text form used by monuments.id."""
        if self.monument_id is None:
            return ""

        try:
            decimal_value = Decimal(str(self.monument_id))
        except (InvalidOperation, ValueError):
            return str(self.monument_id)

        if decimal_value == decimal_value.to_integral():
            return str(int(decimal_value))

        normalized = format(decimal_value.normalize(), "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized
