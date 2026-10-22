from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monument import Monument
from app.schemas.monument import MonumentSummaryResponse, MonumentsListResponse

CARTHAGE_LAT, CARTHAGE_LON = 36.8531, 10.3236
LA_MARSA_LAT, LA_MARSA_LON = 36.8781, 10.3247


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def classify_monument_city(lat: float, lng: float) -> str:
    """Assign a monument to Carthage or La Marsa by nearest city center."""
    dist_carthage = _haversine_km(lat, lng, CARTHAGE_LAT, CARTHAGE_LON)
    dist_la_marsa = _haversine_km(lat, lng, LA_MARSA_LAT, LA_MARSA_LON)
    return "carthage" if dist_carthage <= dist_la_marsa else "la_marsa"


def list_monuments(db: Session, *, city: str | None = None) -> MonumentsListResponse:
    rows = db.scalars(
        select(Monument)
        .where(Monument.latitude.is_not(None), Monument.longitude.is_not(None))
        .order_by(Monument.priority.desc().nullslast(), Monument.name_fr)
    ).all()

    monuments: list[MonumentSummaryResponse] = []
    for monument in rows:
        if monument.latitude is None or monument.longitude is None:
            continue
        lat = monument.latitude_float
        lng = monument.longitude_float
        if lat is None or lng is None:
            continue
        if lat == 0 and lng == 0:
            continue
        monument_city = classify_monument_city(lat, lng)
        if city is not None and monument_city != city.lower().strip():
            continue

        monuments.append(
            MonumentSummaryResponse(
                id=float(monument.id),
                name_fr=monument.name_fr,
                name_en=monument.name_en,
                name_ar=monument.name_ar,
                latitude=lat,
                longitude=lng,
                visit_duration_min=monument.visit_duration_minutes,
                dominant_period=monument.dominant_period,
                function=monument.function,
                popularity=monument.priority,
                image_url=monument.panoramic_image_url,
            )
        )

    return MonumentsListResponse(monuments=monuments)
