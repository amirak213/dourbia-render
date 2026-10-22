"""Import circuit optimization CSV datasets into PostgreSQL.

Reuses the existing ``monuments`` table: enriches rows by French name match
or creates new rows from monuments.csv when no Excel import exists.

Run from backend/:
    python scripts/import_circuit_datasets.py
"""

from __future__ import annotations

import ast
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.monument import Monument
from app.models.monument_distance import MonumentDistance
from app.models.reference_circuit import ReferenceCircuit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = PROJECT_ROOT / "data" / "raw" / "csv"

MONUMENTS_CSV = CSV_DIR / "monuments.csv.csv"
DISTANCES_CSV = CSV_DIR / "distances.csv"
CIRCUITS_CSV = CSV_DIR / "circuits_optimises.csv"
PROFILES_CSV = CSV_DIR / "Profile_clients.csv"


@dataclass
class ImportSummary:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def record_import(self) -> None:
        self.imported += 1

    def record_update(self) -> None:
        self.updated += 1

    def record_skip(self, reason: str) -> None:
        self.skipped += 1
        self.notes.append(reason)


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value)


def as_decimal(value: object) -> Decimal | None:
    if is_missing(value):
        return None
    if isinstance(value, str):
        value = value.replace(",", ".")
    try:
        return Decimal(str(value))
    except Exception:
        return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip().lstrip("\ufeff") for c in out.columns]
    return out


def build_name_lookup(monuments: list[Monument]) -> dict[str, Monument]:
    lookup: dict[str, Monument] = {}
    for monument in monuments:
        for candidate in (monument.name_fr, monument.name_en, monument.name_ar):
            if candidate:
                lookup[normalize_name(candidate)] = monument
    return lookup


def name_tokens(value: str) -> set[str]:
    return {token for token in normalize_name(value).split() if token}


def resolve_monument_by_name(
    name: str,
    lookup: dict[str, Monument],
    *,
    index_map: dict[int, Monument],
    csv_index: int | None = None,
) -> Monument | None:
    if csv_index is not None and csv_index in index_map:
        return index_map[csv_index]

    normalized = normalize_name(name)
    if normalized in lookup:
        return lookup[normalized]

    for key, monument in lookup.items():
        if normalized in key or key in normalized:
            return monument

    query_tokens = name_tokens(name)
    if not query_tokens:
        return None

    best: Monument | None = None
    best_score = 0.0
    for key, monument in lookup.items():
        key_tokens = set(key.split())
        if not key_tokens:
            continue
        overlap = len(query_tokens & key_tokens) / len(query_tokens | key_tokens)
        if overlap > best_score and overlap >= 0.55:
            best_score = overlap
            best = monument
    return best


def allocate_monument_id(
    csv_index: int,
    used_ids: set[Decimal],
    *,
    excel_data_present: bool,
) -> Decimal:
    """Pick a primary key that does not collide with Excel fractional IDs."""
    if not excel_data_present:
        candidate = Decimal(csv_index + 1)
    else:
        # Keep CSV-only rows in a dedicated numeric range.
        candidate = Decimal(9000 + csv_index)

    while candidate in used_ids:
        candidate += Decimal("0.01")
    used_ids.add(candidate)
    return candidate


def import_monuments_from_csv(session: Session) -> tuple[ImportSummary, dict[str, Monument], dict[int, Monument]]:
    summary = ImportSummary()
    if not MONUMENTS_CSV.exists():
        summary.record_skip(f"Missing file: {MONUMENTS_CSV}")
        return summary, {}, {}

    df = normalize_columns(pd.read_csv(MONUMENTS_CSV, sep=";", decimal=","))
    existing = list(session.scalars(select(Monument)).all())
    lookup = build_name_lookup(existing)
    used_ids = {monument.id for monument in existing}
    excel_data_present = len(existing) > 0
    index_map: dict[int, Monument] = {}

    # Assign circuit_index from CSV row order (0-based).
    for csv_index, row in df.iterrows():
        name = str(row.get("nom", "")).strip()
        if not name:
            summary.record_skip(f"Row {csv_index}: empty name")
            continue

        monument = resolve_monument_by_name(name, lookup, index_map=index_map)
        lat = as_decimal(row.get("latitude"))
        lng = as_decimal(row.get("longitude"))
        visit = as_decimal(row.get("duree_visite_min"))
        popularity = as_decimal(row.get("popularite"))

        if monument is None:
            monument_id = allocate_monument_id(
                int(csv_index),
                used_ids,
                excel_data_present=excel_data_present,
            )
            monument = Monument(id=monument_id, name_fr=name)
            session.add(monument)
            summary.record_import()
            lookup[normalize_name(name)] = monument
        else:
            summary.record_update()

        monument.circuit_index = int(csv_index)
        if lat is not None:
            monument.latitude = lat
        if lng is not None:
            monument.longitude = lng
        if visit is not None:
            monument.visit_duration_minutes = visit
        if popularity is not None:
            monument.popularity = popularity

        monument.price_resident = as_decimal(row.get("Tarif_resident"))
        monument.price_student = as_decimal(row.get("Tarif_etudiant"))
        monument.price_foreign = as_decimal(row.get("Tarif_etranger"))
        monument.price_teacher = as_decimal(row.get("Tarif_enseignant"))
        monument.price_senior = as_decimal(row.get("Tarif_retraite"))
        monument.price_child = as_decimal(row.get("Tarif_enfant"))

        lookup[normalize_name(monument.name_fr)] = monument
        lookup[normalize_name(name)] = monument

        index_map[int(csv_index)] = monument

    session.flush()
    return summary, lookup, index_map


def import_distances(
    session: Session,
    lookup: dict[str, Monument],
    index_map: dict[int, Monument],
) -> ImportSummary:
    summary = ImportSummary()
    if not DISTANCES_CSV.exists():
        summary.record_skip(f"Missing file: {DISTANCES_CSV}")
        return summary

    existing_edges = {
        (row.from_monument_id, row.to_monument_id)
        for row in session.scalars(select(MonumentDistance)).all()
    }

    df = normalize_columns(pd.read_csv(DISTANCES_CSV))
    for _, row in df.iterrows():
        from_name = as_str(row.get("from"))
        to_name = as_str(row.get("to"))
        if not from_name or not to_name:
            summary.record_skip("Distance row missing from/to name")
            continue

        from_monument = resolve_monument_by_name(from_name, lookup, index_map=index_map)
        to_monument = resolve_monument_by_name(to_name, lookup, index_map=index_map)
        if from_monument is None or to_monument is None:
            summary.record_skip(
                f"Unresolved edge: {from_name!r} -> {to_name!r}"
            )
            continue

        key = (from_monument.id, to_monument.id)
        if key in existing_edges:
            edge = session.scalar(
                select(MonumentDistance).where(
                    MonumentDistance.from_monument_id == from_monument.id,
                    MonumentDistance.to_monument_id == to_monument.id,
                )
            )
            if edge is None:
                continue
            summary.record_update()
        else:
            edge = MonumentDistance(
                from_monument_id=from_monument.id,
                to_monument_id=to_monument.id,
            )
            session.add(edge)
            existing_edges.add(key)
            summary.record_import()

        edge.distance_m = as_decimal(row.get("distance_m"))
        edge.distance_km = as_decimal(row.get("distance_km"))
        edge.duration_walk_min = as_decimal(row.get("duree_pied_min"))
        edge.duration_bike_min = as_decimal(row.get("duree_velo_min"))
        edge.duration_car_min = as_decimal(row.get("duree_voiture_min"))

    return summary


def as_str(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def parse_list_field(value: object) -> list:
    if is_missing(value):
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []


def import_reference_circuits(
    session: Session,
    index_map: dict[int, Monument],
) -> ImportSummary:
    summary = ImportSummary()
    if not CIRCUITS_CSV.exists():
        summary.record_skip(f"Missing file: {CIRCUITS_CSV}")
        return summary

    df = normalize_columns(pd.read_csv(CIRCUITS_CSV))
    for _, row in df.iterrows():
        external_id = as_str(row.get("id"))
        if not external_id:
            summary.record_skip("Reference circuit missing id")
            continue

        indices = parse_list_field(row.get("indices"))
        names = parse_list_field(row.get("noms"))
        monument_ids: list[float] = []
        for idx in indices:
            monument = index_map.get(int(idx))
            if monument is not None:
                monument_ids.append(float(monument.id))

        existing = session.get(ReferenceCircuit, external_id)
        if existing is None:
            ref = ReferenceCircuit(
                external_id=external_id,
                monument_indices=indices,
                monument_ids=monument_ids or None,
                monument_names=names,
            )
            session.add(ref)
            summary.record_import()
        else:
            ref = existing
            summary.record_update()

        ref.monument_indices = indices
        ref.monument_ids = monument_ids or None
        ref.monument_names = names
        ref.stop_count = int(row["nb_monuments"]) if not is_missing(row.get("nb_monuments")) else None
        ref.duration_min = float(row["duree"]) if not is_missing(row.get("duree")) else None
        ref.score = float(row["score"]) if not is_missing(row.get("score")) else None
        ref.tariff_totals = {
            "resident": float(row["tarif_resident"]) if not is_missing(row.get("tarif_resident")) else None,
            "etudiant": float(row["tarif_etudiant"]) if not is_missing(row.get("tarif_etudiant")) else None,
            "etranger": float(row["tarif_etranger"]) if not is_missing(row.get("tarif_etranger")) else None,
            "enseignant": float(row["tarif_enseignant"]) if not is_missing(row.get("tarif_enseignant")) else None,
            "retraite": float(row["tarif_retraite"]) if not is_missing(row.get("tarif_retraite")) else None,
            "enfant": float(row["tarif_enfant"]) if not is_missing(row.get("tarif_enfant")) else None,
        }

    return summary


def validate_profiles_csv() -> ImportSummary:
    summary = ImportSummary()
    if not PROFILES_CSV.exists():
        summary.record_skip(f"Missing file: {PROFILES_CSV}")
        return summary

    df = normalize_columns(pd.read_csv(PROFILES_CSV, sep=";"))
    summary.imported = len(df)
    summary.notes.append(
        f"Profile_clients.csv validated: {len(df)} rows (test fixtures only, not stored in DB)"
    )
    return summary


def print_summary(label: str, summary: ImportSummary) -> None:
    print(f"\n{label}")
    print(f"  imported: {summary.imported}")
    print(f"  updated:  {summary.updated}")
    print(f"  skipped:  {summary.skipped}")
    if summary.notes:
        print("  notes:")
        for note in summary.notes[:10]:
            print(f"    - {note}")
        if len(summary.notes) > 10:
            print(f"    ... and {len(summary.notes) - 10} more")


def main() -> None:
    session = SessionLocal()
    try:
        monuments_summary, lookup, index_map = import_monuments_from_csv(session)
        distances_summary = import_distances(session, lookup, index_map)
        circuits_summary = import_reference_circuits(session, index_map)
        profiles_summary = validate_profiles_csv()
        session.commit()

        print("=== Circuit dataset import complete ===")
        print_summary("Monuments (reused monuments table)", monuments_summary)
        print_summary("Monument distances", distances_summary)
        print_summary("Reference circuits", circuits_summary)
        print_summary("Profile clients (validation only)", profiles_summary)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
