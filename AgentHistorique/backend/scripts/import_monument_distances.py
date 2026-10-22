"""Peuple monument_distances avec des distances/durées réelles via OpenRouteService.

Utilise l'API Matrix d'OpenRouteService (v2/matrix/{profile}) pour calculer les
distances/durées réelles (réseau routier/piéton OSM) entre tous les monuments,
un profil à la fois : foot-walking, cycling-regular, driving-car.

Les points sont traités par lots (batches) pour respecter la limite du tier
gratuit ORS (3500 paires par requête). En cas d'échec ORS pour une paire
(timeout, indisponibilité, point injoignable par la route), on retombe sur un
calcul Haversine + vitesse fixe, comme avant, pour ne jamais laisser de trou.

Idempotent : upsert sur la contrainte unique (from_monument_id, to_monument_id).
"""

from __future__ import annotations

import time
from itertools import combinations_with_replacement

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.database import SessionLocal
from app.circuits.data_loader import haversine_km
from app.models.monument import Monument
from app.models.monument_distance import MonumentDistance

WALK_SPEED_KMH = 4.5
BIKE_SPEED_KMH = 12.0
CAR_SPEED_KMH = 25.0

ORS_PROFILES = {
    "duration_walk_min": "foot-walking",
    "duration_bike_min": "cycling-regular",
    "duration_car_min": "driving-car",
}

ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/{profile}"


def _haversine_fallback(from_lat, from_lon, to_lat, to_lon) -> dict:
    distance_km = haversine_km(from_lat, from_lon, to_lat, to_lon)
    return {
        "distance_km": distance_km,
        "duration_walk_min": (distance_km / WALK_SPEED_KMH) * 60.0,
        "duration_bike_min": (distance_km / BIKE_SPEED_KMH) * 60.0,
        "duration_car_min": (distance_km / CAR_SPEED_KMH) * 60.0,
    }


def _call_ors_matrix(
    profile: str, coords: list[tuple[float, float]], api_key: str
) -> dict | None:
    """coords: list of (lat, lon). Returns the parsed ORS response or None on failure."""
    body = {
        "locations": [[lon, lat] for lat, lon in coords],
        "metrics": ["distance", "duration"],
        "units": "km",
    }
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json; charset=utf-8",
    }

    for attempt in range(3):
        try:
            response = requests.post(
                ORS_MATRIX_URL.format(profile=profile),
                json=body,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            print(f"[ors] Network error on {profile} batch: {exc}")
            return None

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f"[ors] Rate limited on {profile}, retry in {wait}s")
            time.sleep(wait)
            continue

        print(
            f"[ors] {profile} batch failed: {response.status_code} {response.text[:200]}"
        )
        return None

    return None


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def main() -> None:
    settings = get_settings()
    if not settings.ors_api_key:
        raise RuntimeError("ORS_API_KEY manquant dans E:\\claude\\.env")

    with SessionLocal() as session:
        monuments = session.scalars(select(Monument)).all()
        points = [
            (str(m.id_str), m.latitude_float, m.longitude_float)
            for m in monuments
            if m.latitude_float is not None and m.longitude_float is not None
        ]
        print(f"[import] {len(points)} monuments avec coordonnées valides")

        # id -> {distance_km, duration_walk_min, duration_bike_min, duration_car_min}
        results: dict[tuple[str, str], dict] = {}

        # Fallback Haversine pré-rempli pour toutes les paires, ORS viendra écraser
        # les valeurs qu'il arrive à calculer.
        for from_id, from_lat, from_lon in points:
            for to_id, to_lat, to_lon in points:
                if from_id == to_id:
                    continue
                results[(from_id, to_id)] = _haversine_fallback(
                    from_lat, from_lon, to_lat, to_lon
                )

        blocks = _chunk(points, settings.ors_profile_batch_size)
        block_pairs = list(combinations_with_replacement(range(len(blocks)), 2))
        print(
            f"[import] {len(blocks)} lots, {len(block_pairs)} paires de lots à interroger par profil"
        )

        for duration_field, profile in ORS_PROFILES.items():
            print(f"[import] Profil ORS : {profile}")
            for i, j in block_pairs:
                block = blocks[i] if i == j else blocks[i] + blocks[j]
                coords = [(lat, lon) for _, lat, lon in block]
                ids = [pid for pid, _, _ in block]

                data = _call_ors_matrix(profile, coords, settings.ors_api_key)
                time.sleep(settings.ors_request_delay_seconds)

                if data is None:
                    print(
                        f"[import] Fallback Haversine conservé pour le lot ({i},{j}), profil {profile}"
                    )
                    continue

                distances = data.get("distances")
                durations = data.get("durations")
                if not distances or not durations:
                    print(
                        f"[import] Réponse ORS incomplète pour le lot ({i},{j}), profil {profile}"
                    )
                    continue

                for row_idx, from_id in enumerate(ids):
                    for col_idx, to_id in enumerate(ids):
                        if from_id == to_id:
                            continue
                        distance_km = distances[row_idx][col_idx]
                        duration_min = durations[row_idx][col_idx]
                        if distance_km is None or duration_min is None:
                            continue  # paire injoignable par la route -> on garde le fallback

                        entry = results.setdefault(
                            (from_id, to_id),
                            _haversine_fallback(
                                0, 0, 0, 0
                            ),  # ne devrait pas arriver, filet de sécurité
                        )
                        if duration_field == "duration_walk_min":
                            entry["distance_km"] = distance_km
                        entry[duration_field] = duration_min / 60.0

        rows = [
            {
                "from_monument_id": from_id,
                "to_monument_id": to_id,
                "distance_m": entry["distance_km"] * 1000.0,
                "distance_km": entry["distance_km"],
                "duration_walk_min": entry["duration_walk_min"],
                "duration_bike_min": entry["duration_bike_min"],
                "duration_car_min": entry["duration_car_min"],
            }
            for (from_id, to_id), entry in results.items()
        ]

        print(f"[import] {len(rows)} arêtes à insérer/mettre à jour")

        stmt = insert(MonumentDistance)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_monument_distances_from_to",
            set_={
                "distance_m": stmt.excluded.distance_m,
                "distance_km": stmt.excluded.distance_km,
                "duration_walk_min": stmt.excluded.duration_walk_min,
                "duration_bike_min": stmt.excluded.duration_bike_min,
                "duration_car_min": stmt.excluded.duration_car_min,
            },
        )
        session.execute(stmt, rows)
        session.commit()
        print("[import] Terminé.")


if __name__ == "__main__":
    main()
