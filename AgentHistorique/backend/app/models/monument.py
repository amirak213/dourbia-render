from typing import TYPE_CHECKING

from sqlalchemy import String, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.circuit_monument import CircuitMonument
    from app.models.monument_distance import MonumentDistance


class Monument(Base):
    """Maps to the existing sig_dourbia.monuments table."""

    __tablename__ = "monuments"

    id: Mapped[float] = mapped_column("id", Numeric, primary_key=True)
    name_fr: Mapped[str] = mapped_column("name_fr", String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column("name_en", String(255), nullable=True)
    name_ar: Mapped[str | None] = mapped_column("name_ar", String(255), nullable=True)
    priority: Mapped[float | None] = mapped_column("priority", Numeric, nullable=True)
    latitude: Mapped[float | None] = mapped_column("latitude", Numeric, nullable=True)
    longitude: Mapped[float | None] = mapped_column("longitude", Numeric, nullable=True)

    status: Mapped[str | None] = mapped_column("status", String(100), nullable=True)
    importance: Mapped[str | None] = mapped_column("importance", String(100), nullable=True)
    accessibility: Mapped[str | None] = mapped_column("accessibility", String(100), nullable=True)
    relief: Mapped[str | None] = mapped_column("relief", String(100), nullable=True)
    address: Mapped[str | None] = mapped_column("address", String(500), nullable=True)

    description_fr: Mapped[str | None] = mapped_column("description_fr", Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column("description_en", Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column("description_ar", Text, nullable=True)

    affectation: Mapped[str | None] = mapped_column("affectation", String(100), nullable=True)

    conservation_state: Mapped[float | None] = mapped_column("conservation_state", Numeric, nullable=True)
    visit_duration_minutes: Mapped[float | None] = mapped_column("visit_duration_minutes", Numeric, nullable=True)

    opening_time_summer: Mapped[str | None] = mapped_column("opening_time_summer", String(50), nullable=True)
    closing_time_summer: Mapped[str | None] = mapped_column("closing_time_summer", String(50), nullable=True)
    opening_time_winter: Mapped[str | None] = mapped_column("opening_time_winter", String(50), nullable=True)
    closing_time_winter: Mapped[str | None] = mapped_column("closing_time_winter", String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column("phone", String(50), nullable=True)

    dominant_period: Mapped[str | None] = mapped_column("dominant_period", String(100), nullable=True)
    secondary_period: Mapped[str | None] = mapped_column("secondary_period", String(100), nullable=True)
    third_period: Mapped[str | None] = mapped_column("third_period", String(100), nullable=True)
    function: Mapped[str | None] = mapped_column("function", String(100), nullable=True)

    price_resident: Mapped[float | None] = mapped_column("price_resident", Numeric, nullable=True)
    price_student: Mapped[float | None] = mapped_column("price_student", Numeric, nullable=True)
    price_foreign: Mapped[float | None] = mapped_column("price_foreign", Numeric, nullable=True)
    price_teacher: Mapped[float | None] = mapped_column("price_teacher", Numeric, nullable=True)
    price_senior: Mapped[float | None] = mapped_column("price_senior", Numeric, nullable=True)
    price_child: Mapped[float | None] = mapped_column("price_child", Numeric, nullable=True)

    panoramic_image_url: Mapped[str | None] = mapped_column("panoramic_image_url", String(500), nullable=True)
    model_object_url: Mapped[str | None] = mapped_column("model_object_url", String(500), nullable=True)
    video_url_fr: Mapped[str | None] = mapped_column("video_url_fr", String(500), nullable=True)
    video_url_en: Mapped[str | None] = mapped_column("video_url_en", String(500), nullable=True)
    video_url_ar: Mapped[str | None] = mapped_column("video_url_ar", String(500), nullable=True)
    video_360_url: Mapped[str | None] = mapped_column("video_360_url", String(500), nullable=True)
    video_3d_url: Mapped[str | None] = mapped_column("video_3d_url", String(500), nullable=True)
    audio_url_fr: Mapped[str | None] = mapped_column("audio_url_fr", String(500), nullable=True)
    audio_url_en: Mapped[str | None] = mapped_column("audio_url_en", String(500), nullable=True)
    audio_url_ar: Mapped[str | None] = mapped_column("audio_url_ar", String(500), nullable=True)
    @property
    def id_str(self) -> str:
        """ID normalise sans decimales inutiles (ex: '1' au lieu de '1.00')."""
        if self.id is None:
            return ""
        return str(int(self.id))

    @property
    def latitude_float(self) -> float | None:
        if self.latitude is None:
            return None
        return float(self.latitude)

    @property
    def longitude_float(self) -> float | None:
        if self.longitude is None:
            return None
        return float(self.longitude)

    circuit_links: Mapped[list["CircuitMonument"]] = relationship(
        back_populates="monument",
    )
    outgoing_distances: Mapped[list["MonumentDistance"]] = relationship(
        foreign_keys="MonumentDistance.from_monument_id",
        back_populates="from_monument",
    )
    incoming_distances: Mapped[list["MonumentDistance"]] = relationship(
        foreign_keys="MonumentDistance.to_monument_id",
        back_populates="to_monument",
    )

