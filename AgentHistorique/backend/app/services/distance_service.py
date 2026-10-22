from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def normalize_monument_reference_id(value: object | None) -> str:
    """Normalize a monument identifier from DB values to the string form used by the app."""
    if value is None:
        return ""

    raw_text = str(value).strip()
    if not raw_text:
        return ""

    try:
        decimal_value = Decimal(raw_text)
    except InvalidOperation:
        return raw_text

    if decimal_value == decimal_value.to_integral():
        return str(int(decimal_value))

    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def normalize_monument_name(value: object | None) -> str:
    """Compare monument names in a normalized form that ignores accents and spacing."""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKD", str(value).strip())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def resolve_monument_name(session: Session, monument_id: object | None) -> str | None:
    """Resolve a monument identifier to its French name via monuments.nom_monument_fr."""
    if monument_id is None:
        return None

    normalized_id = normalize_monument_reference_id(monument_id)
    if not normalized_id:
        return None

    result = session.execute(
        text("SELECT name_fr FROM monuments WHERE CAST(id AS TEXT) = :id_monument"),
        {"id_monument": normalized_id},
    ).scalar_one_or_none()
    if result is not None:
        return str(result)

    rows = session.execute(text("SELECT id, name_fr FROM monuments")).mappings().all()
    for row in rows:
        if normalize_monument_reference_id(row.get("id")) == normalized_id:
            return str(row.get("name_fr"))

    return None


def build_distance_lookup(
    session: Session,
    *,
    monument_ids: list[str],
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[tuple[str, str]]]:
    """Build a lookup of distance rows using monument_distances, keyed by monument ids."""
    normalized_ids = {
        str(monument_id): normalize_monument_reference_id(monument_id)
        for monument_id in monument_ids
    }

    try:
        rows = session.execute(
            text(
                "SELECT from_monument_id, to_monument_id, distance_km, "
                "duration_walk_min, duration_bike_min, duration_car_min FROM monument_distances"
            )
            
        ).mappings().all()
    except Exception as exc:  # pragma: no cover - depends on DB availability
        print(f"[circuits] Unable to read distance table: {exc}")
        return {}, []

    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    unresolved: list[tuple[str, str]] = []

    normalized_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        from_id = normalize_monument_reference_id(row.get("from_monument_id"))
        to_id = normalize_monument_reference_id(row.get("to_monument_id"))
        if not from_id or not to_id:
            continue
        normalized_rows[(from_id, to_id)] = {
            "distance_km": float(row.get("distance_km") or 0.0),
            "duration_walk_min": float(row.get("duration_walk_min") or 0.0),
            "duration_bike_min": float(row.get("duration_bike_min") or 0.0),
            "duration_car_min": float(row.get("duration_car_min") or 0.0),
        }

    for monument_id in monument_ids:
        from_key = normalized_ids[str(monument_id)]
        if not from_key:
            continue

        for target_id in monument_ids:
            if monument_id == target_id:
                continue
            to_key = normalized_ids[str(target_id)]
            if not to_key:
                continue

            if from_key == to_key:
                lookup[(str(monument_id), str(target_id))] = {
                    "distance_km": 0.0,
                    "duration_walk_min": 0.0,
                    "duration_bike_min": 0.0,
                    "duration_car_min": 0.0,
                }
                continue

            row = normalized_rows.get((from_key, to_key))
            if row is None:
                unresolved.append((from_key, to_key))
                continue

            lookup[(str(monument_id), str(target_id))] = row

    if unresolved:
        unique_unresolved = list(dict.fromkeys(unresolved))
        for from_id, to_id in unique_unresolved:
            print(
                f"[circuits] No distance match for monument pair: {from_id} -> {to_id}"
            )
        return lookup, unique_unresolved

    return lookup, []
