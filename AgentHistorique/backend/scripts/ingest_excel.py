"""Import Excel datasets into PostgreSQL.

Run from backend/:
    python scripts/ingest_excel.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

# Allow imports from backend/app when the script is run from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.circuit import Circuit
from app.models.circuit_monument import CircuitMonument
from app.models.destination import Destination
from app.models.monument import Monument

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

EXCEL_FILES = {
    "destinations": "Tab_destination.xlsx",
    "monuments": "Monuments.xlsx",
    "circuits": "Tab_circuit.xlsx",
    "circuit_monuments": "Tab_circuit_monument.xlsx",
}


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


def resolve_excel_path(filename: str) -> Path:
    for candidate in (RAW_DIR / filename, RAW_DIR / "excel" / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find {filename} in {RAW_DIR} or {RAW_DIR / 'excel'}"
    )


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    return normalized


def is_missing(value: object) -> bool:
    return value is None or pd.isna(value)


def as_str(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def as_int(value: object) -> int | None:
    if is_missing(value):
        return None
    return int(float(value))


def as_decimal(value: object) -> Decimal | None:
    if is_missing(value):
        return None
    return Decimal(str(value))


def load_excel(filename: str) -> pd.DataFrame:
    path = resolve_excel_path(filename)
    return normalize_columns(pd.read_excel(path))


def upsert_destination(
    session: Session,
    row: pd.Series,
    summary: ImportSummary,
    cache: dict[int, Destination],
) -> None:
    destination_id = as_int(row.get("id"))
    name = as_str(row.get("nom_site"))
    if destination_id is None or not name:
        summary.record_skip(f"Destination row skipped: invalid id or name ({name!r})")
        return

    destination = cache.get(destination_id)
    if destination is None:
        destination = session.get(Destination, destination_id)

    is_new = destination is None
    if is_new:
        destination = Destination(id=destination_id, name=name)
        session.add(destination)

    cache[destination_id] = destination

    destination.name = name
    destination.description = as_str(row.get("description_site"))
    destination.address = as_str(row.get("adresse_site"))
    destination.postal_code = as_int(row.get("code_postal_site"))
    destination.city = as_str(row.get("ville_site"))
    destination.phone = as_str(row.get("telephone_site"))
    destination.email = as_str(row.get("email_site"))
    destination.website = as_str(row.get("site_web_site"))
    destination.image_url = as_str(row.get("image_site"))

    if is_new:
        summary.record_import()
    else:
        summary.record_update()


def upsert_monument(
    session: Session,
    row: pd.Series,
    summary: ImportSummary,
    cache: dict[Decimal, Monument],
) -> None:
    monument_id = as_decimal(row.get("ID_monument"))
    name_fr = as_str(row.get("nom_monument_FR"))
    if monument_id is None or not name_fr:
        summary.record_skip(
            f"Monument row skipped: invalid id or French name ({name_fr!r})"
        )
        return

    if monument_id in cache:
        monument = cache[monument_id]
        is_new = False
        summary.notes.append(
            f"Duplicate ID_monument {monument_id}: keeping last row ({name_fr!r})"
        )
    else:
        monument = session.get(Monument, monument_id)
        is_new = monument is None
        if is_new:
            monument = Monument(id=monument_id, name_fr=name_fr)
            session.add(monument)
        cache[monument_id] = monument

    monument.name_fr = name_fr
    monument.name_en = as_str(row.get("nom_monument_EN"))
    monument.name_ar = as_str(row.get("nom_monument_AR"))
    monument.priority = as_decimal(row.get("priorité"))
    monument.latitude = as_decimal(row.get("latitude_monument"))
    monument.longitude = as_decimal(row.get("longitude_monument"))
    monument.status = as_str(row.get("statut_monument"))
    monument.importance = as_str(row.get("importance_monument"))
    monument.accessibility = as_str(row.get("accessibilite_monument"))
    monument.relief = as_str(row.get("relief"))
    monument.address = as_str(row.get("adresse_monument"))
    monument.description_fr = as_str(row.get("description_FR"))
    monument.description_en = as_str(row.get("description_EN"))
    monument.description_ar = as_str(row.get("description_AR"))
    monument.affectation = as_str(row.get("Affectation"))
    monument.conservation_state = as_decimal(row.get("etat_conservation"))
    monument.visit_duration_minutes = as_decimal(row.get("duree_visite(en min)"))
    monument.opening_time_summer = as_str(row.get("horaire_ouverture_ete"))
    monument.closing_time_summer = as_str(row.get("horaire_fermeture_ete"))
    monument.opening_time_winter = as_str(row.get("horaire_ouverture_hiver"))
    monument.closing_time_winter = as_str(row.get("horaire_fermeture_hiver"))
    monument.phone = as_str(row.get("telephone_site"))
    monument.dominant_period = as_str(row.get("epoque_dominante"))
    monument.secondary_period = as_str(row.get("epoque_secondaire"))
    monument.third_period = as_str(row.get("troisieme_epoque"))
    monument.function = as_str(row.get("fonction_monument"))
    monument.price_resident = as_decimal(row.get("Tarif_resident"))
    monument.price_student = as_decimal(row.get("Tarif_Étudiant"))
    monument.price_foreign = as_decimal(row.get("Tarif_Étranger"))
    monument.price_teacher = as_decimal(row.get("Tarif_enseingant"))
    monument.price_senior = as_decimal(row.get("Tarif_retraitee"))
    monument.price_child = as_decimal(row.get("Tarif_enfant"))
    monument.panoramic_image_url = as_str(row.get("image_panoramique"))
    monument.model_object_url = as_str(row.get("modele_obj"))
    monument.video_url_fr = as_str(row.get("url_video_FR"))
    monument.video_url_en = as_str(row.get("uri_video_EN"))
    monument.video_url_ar = as_str(row.get("uri_video_AR"))
    monument.video_360_url = as_str(row.get("lien_video_360"))
    monument.video_3d_url = as_str(row.get("lien_video_3D"))
    monument.audio_url_fr = as_str(row.get("enregistrement_audio_FR"))
    monument.audio_url_en = as_str(row.get("enregistrement_audio_EN"))
    monument.audio_url_ar = as_str(row.get("enregistrement_audio_AR"))

    if is_new:
        summary.record_import()
    else:
        summary.record_update()


def upsert_circuit(
    session: Session,
    row: pd.Series,
    summary: ImportSummary,
    cache: dict[int, Circuit],
) -> None:
    circuit_id = as_int(row.get("id"))
    name = as_str(row.get("nom_circuit_thematique"))
    if circuit_id is None or not name:
        summary.record_skip(f"Circuit row skipped: invalid id or name ({name!r})")
        return

    circuit = cache.get(circuit_id)
    if circuit is None:
        circuit = session.get(Circuit, circuit_id)

    is_new = circuit is None
    if is_new:
        circuit = Circuit(id=circuit_id, name=name)
        session.add(circuit)

    cache[circuit_id] = circuit

    circuit.name = name
    circuit.description_fr = as_str(row.get("description_FR"))
    circuit.description_en = as_str(row.get("description_ENG"))
    circuit.audio_url_fr = as_str(row.get("audio_FR"))
    circuit.audio_url_en = as_str(row.get("audio_ENG"))
    circuit.step_count = as_int(row.get("nbr_etape"))
    circuit.distance_km = as_decimal(row.get("kilometrage"))
    circuit.duration_hours = as_decimal(row.get("duree_heures"))
    circuit.duration_minutes = as_decimal(row.get("duree_minutes"))
    circuit.duration_display = as_str(row.get("duree_affichee"))
    circuit.departure_longitude = as_decimal(row.get("depart_longitude_circuit"))
    circuit.departure_latitude = as_decimal(row.get("depart_latitude_circuit"))
    circuit.image_url = as_str(row.get("img"))
    circuit.video_url = as_str(row.get("video"))

    if is_new:
        summary.record_import()
    else:
        summary.record_update()


def upsert_circuit_monument(
    session: Session,
    row: pd.Series,
    summary: ImportSummary,
    monument_cache: dict[Decimal, Monument],
    relation_cache: dict[tuple[int, Decimal], CircuitMonument],
) -> None:
    circuit_id = as_int(row.get("ID_circuit"))
    monument_id = as_decimal(row.get("ID_monument"))
    position = as_int(row.get("Ordre"))

    if circuit_id is None or monument_id is None or position is None:
        summary.record_skip(
            "Circuit-monument row skipped: missing circuit id, monument id, or order"
        )
        return

    if session.get(Circuit, circuit_id) is None:
        summary.record_skip(
            f"Circuit-monument row skipped: unknown circuit id {circuit_id}"
        )
        return

    if monument_cache.get(monument_id) is None and session.get(Monument, monument_id) is None:
        summary.record_skip(
            f"Circuit-monument row skipped: unknown monument id {monument_id}"
        )
        return

    relation_key = (circuit_id, monument_id)
    existing = relation_cache.get(relation_key)
    if existing is None:
        existing = (
            session.query(CircuitMonument)
            .filter_by(circuit_id=circuit_id, monument_id=monument_id)
            .one_or_none()
        )

    if existing is not None:
        existing.position = position
        relation_cache[relation_key] = existing
        summary.record_update()
        return

    relation = CircuitMonument(
        circuit_id=circuit_id,
        monument_id=monument_id,
        position=position,
    )
    session.add(relation)
    relation_cache[relation_key] = relation
    summary.record_import()


def print_summary(label: str, summary: ImportSummary) -> None:
    print(f"{label}: {summary.imported} imported, {summary.updated} updated, {summary.skipped} skipped")
    for note in summary.notes[:5]:
        print(f"  - {note}")
    if len(summary.notes) > 5:
        print(f"  - ... and {len(summary.notes) - 5} more skipped rows")


def ingest_all() -> None:
    destination_summary = ImportSummary()
    monument_summary = ImportSummary()
    circuit_summary = ImportSummary()
    relation_summary = ImportSummary()

    destinations_df = load_excel(EXCEL_FILES["destinations"])
    monuments_df = load_excel(EXCEL_FILES["monuments"])
    circuits_df = load_excel(EXCEL_FILES["circuits"])
    relations_df = load_excel(EXCEL_FILES["circuit_monuments"])

    session = SessionLocal()
    destination_cache: dict[int, Destination] = {}
    monument_cache: dict[Decimal, Monument] = {}
    circuit_cache: dict[int, Circuit] = {}
    relation_cache: dict[tuple[int, Decimal], CircuitMonument] = {}
    try:
        for _, row in destinations_df.iterrows():
            upsert_destination(session, row, destination_summary, destination_cache)

        for _, row in monuments_df.iterrows():
            upsert_monument(session, row, monument_summary, monument_cache)

        for _, row in circuits_df.iterrows():
            upsert_circuit(session, row, circuit_summary, circuit_cache)

        session.flush()

        for _, row in relations_df.iterrows():
            upsert_circuit_monument(
                session,
                row,
                relation_summary,
                monument_cache,
                relation_cache,
            )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print("Import summary")
    print("-" * 40)
    print_summary("Destinations", destination_summary)
    print_summary("Monuments", monument_summary)
    print_summary("Circuits", circuit_summary)
    print_summary("Circuit-monument relations", relation_summary)


if __name__ == "__main__":
    ingest_all()
