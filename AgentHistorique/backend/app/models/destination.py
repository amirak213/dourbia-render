from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class Destination(Base, TimestampMixin):
    """Maps to Tab_destination.xlsx."""

    __tablename__ = "destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # nom_site
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # description_site
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)  # adresse_site
    postal_code: Mapped[int | None] = mapped_column(Integer, nullable=True)  # code_postal_site
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)  # ville_site
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)  # telephone_site
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # email_site
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)  # site_web_site
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # image_site
