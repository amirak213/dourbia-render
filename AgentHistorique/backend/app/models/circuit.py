from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.circuit_monument import CircuitMonument


class Circuit(Base, TimestampMixin):
    """Maps to Tab_circuit.xlsx."""

    __tablename__ = "circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # nom_circuit_thematique
    description_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)  # description_ENG
    audio_url_fr: Mapped[str | None] = mapped_column(String(500), nullable=True)  # audio_FR
    audio_url_en: Mapped[str | None] = mapped_column(String(500), nullable=True)  # audio_ENG
    step_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # nbr_etape
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)  # kilometrage
    duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)  # duree_heures
    duration_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)  # duree_minutes
    duration_display: Mapped[str | None] = mapped_column(String(50), nullable=True)  # duree_affichee
    departure_longitude: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)  # depart_longitude_circuit
    departure_latitude: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)  # depart_latitude_circuit
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # img
    video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # video

    monument_links: Mapped[list["CircuitMonument"]] = relationship(
        back_populates="circuit",
        order_by="CircuitMonument.position",
    )
