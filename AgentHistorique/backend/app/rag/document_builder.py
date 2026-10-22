from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.circuit import Circuit
from app.models.circuit_monument import CircuitMonument
from app.models.monument import Monument
from app.rag.chunker import GeneratedDocument

SHORT_VISIT_MAX_MINUTES = 15.0
# Avoid labeling a 30-minute visit as "longue" when the dataset median is low.
LONG_VISIT_ABSOLUTE_MIN_MINUTES = 45.0


def monument_site_id(monument_id: str) -> int:
    """Integer part of id_monument — groups sub-monuments (e.g. 3.9 → site 3)."""
    try:
        return int(float(monument_id))
    except ValueError:
        return 0


def is_site_root_monument(monument_id: str) -> bool:
    """True when the row represents the parent site (e.g. 3.00), not a sub-point (3.9)."""
    try:
        numeric = float(monument_id)
        return numeric == int(numeric)
    except ValueError:
        return True


def monument_source_id(monument_id: str) -> str:
    """Preserve monument ids as strings for RAG chunk source_id storage."""
    return str(monument_id)


def build_site_titles(monuments: list[Monument]) -> dict[int, str]:
    """Map site_id → name of the root monument row for that site."""
    titles: dict[int, str] = {}
    for monument in monuments:
        if is_site_root_monument(monument.id):
            titles[monument_site_id(monument.id)] = monument.name_fr
    return titles


@dataclass(frozen=True)
class VisitDurationContext:
    short_visit_max_minutes: float
    long_visit_min_minutes: float | None
    max_visit_minutes: float | None


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_token(value: str | None) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return ""
    text = unicodedata.normalize("NFKD", cleaned)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def _append_line(lines: list[str], label: str, value: object | None) -> None:
    cleaned = _clean(value)
    if cleaned is not None:
        lines.append(f"{label}: {cleaned}")


def _extract_parenthetical_aliases(name_fr: str | None) -> list[str]:
    if not name_fr:
        return []
    aliases: list[str] = []
    for match in re.finditer(r"\(([^)]+)\)", name_fr):
        alias = _clean(match.group(1))
        if alias:
            aliases.append(alias)
    return aliases


def _collect_name_aliases(monument: Monument) -> list[str]:
    primary = _clean(monument.name_fr)
    aliases: list[str] = []
    seen: set[str] = set()

    for candidate in (
        _clean(monument.name_en),
        _clean(monument.name_ar),
        *_extract_parenthetical_aliases(monument.name_fr),
    ):
        if not candidate:
            continue
        key = _normalize_token(candidate)
        primary_key = _normalize_token(primary)
        if not key or key == primary_key:
            continue
        if key in seen:
            continue
        seen.add(key)
        aliases.append(candidate)
    return aliases


def _is_reduced_accessibility(accessibility: str | None) -> bool:
    normalized = _normalize_token(accessibility)
    return "reduit" in normalized or "reduced" in normalized


def _is_normal_accessibility(accessibility: str | None) -> bool:
    normalized = _normalize_token(accessibility)
    return "normal" in normalized


def _is_difficult_relief(relief: str | None) -> bool:
    normalized = _normalize_token(relief)
    return normalized in {"escalier", "haut"}


def _is_easy_relief(relief: str | None) -> bool:
    return _normalize_token(relief) == "bas"


def build_visit_duration_context(monuments: list[Monument]) -> VisitDurationContext:
    durations = sorted(
        float(monument.visit_duration_minutes)
        for monument in monuments
        if monument.visit_duration_minutes is not None
    )
    if not durations:
        return VisitDurationContext(
            short_visit_max_minutes=SHORT_VISIT_MAX_MINUTES,
            long_visit_min_minutes=None,
            max_visit_minutes=None,
        )

    long_index = int(0.75 * (len(durations) - 1))
    return VisitDurationContext(
        short_visit_max_minutes=SHORT_VISIT_MAX_MINUTES,
        long_visit_min_minutes=durations[long_index],
        max_visit_minutes=durations[-1],
    )


def _format_duration_minutes(value: Decimal | float) -> str:
    minutes = float(value)
    if minutes.is_integer():
        return str(int(minutes))
    return str(minutes)


def _reduced_mobility_suitable(monument: Monument) -> bool | None:
    accessibility = monument.accessibility
    relief = monument.relief
    if not _clean(accessibility):
        return None
    if _is_reduced_accessibility(accessibility):
        return False
    if _is_normal_accessibility(accessibility) and _is_easy_relief(relief):
        return True
    return None


def _build_searchable_sentences(
    monument: Monument,
    visit_context: VisitDurationContext | None,
) -> list[str]:
    sentences: list[str] = []

    aliases = _collect_name_aliases(monument)
    if aliases:
        sentences.append(f"Autres noms du monument : {', '.join(aliases)}.")

    dominant_period = _clean(monument.dominant_period)
    if dominant_period:
        sentences.append(f"Époque dominante du monument : {dominant_period}.")

    secondary_period = _clean(monument.secondary_period)
    if secondary_period:
        sentences.append(f"Époque secondaire du monument : {secondary_period}.")

    third_period = _clean(monument.third_period)
    if third_period:
        sentences.append(f"Troisième époque du monument : {third_period}.")

    function = _clean(monument.function)
    if function:
        sentences.append(f"Fonction du monument : {function}.")

    monument_name = _clean(monument.name_fr)
    if monument_name and dominant_period and function:
        sentences.append(
            f"C'est un monument {function.lower()} de l'époque {dominant_period.lower()} : {monument_name}."
        )
    elif monument_name and dominant_period:
        sentences.append(
            f"C'est un monument de l'époque {dominant_period.lower()} : {monument_name}."
        )

    accessibility = _clean(monument.accessibility)
    if accessibility:
        sentences.append(f"Accessibilité du monument : {accessibility}.")

    relief = _clean(monument.relief)
    if relief:
        sentences.append(f"Relief du site : {relief}.")

    if _is_difficult_relief(monument.relief):
        sentences.append("Ce monument peut être difficile d'accès.")

    if _is_reduced_accessibility(monument.accessibility):
        sentences.append("Ce monument n'est pas adapté aux personnes à mobilité réduite.")
    elif _is_normal_accessibility(monument.accessibility) and _is_easy_relief(monument.relief):
        sentences.append("Ce monument est adapté aux personnes à mobilité réduite.")

    duration_minutes: float | None = None
    if monument.visit_duration_minutes is not None:
        duration_minutes = float(monument.visit_duration_minutes)
        sentences.append(
            f"Durée de visite recommandée : {_format_duration_minutes(monument.visit_duration_minutes)} minutes."
        )

    if visit_context is not None and duration_minutes is not None:
        if duration_minutes <= visit_context.short_visit_max_minutes:
            sentences.append(
                "Ce monument se visite en "
                f"{int(visit_context.short_visit_max_minutes)} minutes ou moins."
            )
        long_visit_threshold = visit_context.long_visit_min_minutes
        if long_visit_threshold is not None:
            long_visit_threshold = max(
                long_visit_threshold,
                LONG_VISIT_ABSOLUTE_MIN_MINUTES,
            )
        if (
            long_visit_threshold is not None
            and duration_minutes >= long_visit_threshold
        ):
            sentences.append("Ce monument fait partie des visites longues.")
        if (
            visit_context.max_visit_minutes is not None
            and duration_minutes >= visit_context.max_visit_minutes
        ):
            sentences.append("Ce monument fait partie des visites les plus longues à Carthage.")

    return sentences


def build_monument_document(
    monument: Monument,
    linked_circuit_names: list[str] | None = None,
    visit_context: VisitDurationContext | None = None,
    site_titles: dict[int, str] | None = None,
) -> GeneratedDocument:
    site_id = monument_site_id(monument.id)
    site_name = (site_titles or {}).get(site_id)
    is_site_root = is_site_root_monument(monument.id)

    lines = ["Type: monument"]
    _append_line(lines, "Monument", monument.name_fr)
    _append_line(lines, "Identifiant site", site_id)
    if site_name and not is_site_root:
        _append_line(lines, "Site parent", site_name)
    _append_line(lines, "Époque dominante", monument.dominant_period)
    _append_line(lines, "Époque secondaire", monument.secondary_period)
    _append_line(lines, "Troisième époque", monument.third_period)
    _append_line(lines, "Fonction", monument.function)
    _append_line(lines, "Statut", monument.status)
    _append_line(lines, "Importance", monument.importance)
    _append_line(lines, "Accessibilité", monument.accessibility)
    _append_line(lines, "Relief", monument.relief)
    _append_line(lines, "Adresse", monument.address)
    _append_line(lines, "Durée de visite (minutes)", monument.visit_duration_minutes)
    _append_line(
        lines,
        "Horaires été",
        " - ".join(
            part
            for part in (_clean(monument.opening_time_summer), _clean(monument.closing_time_summer))
            if part
        )
        or None,
    )
    _append_line(
        lines,
        "Horaires hiver",
        " - ".join(
            part
            for part in (_clean(monument.opening_time_winter), _clean(monument.closing_time_winter))
            if part
        )
        or None,
    )
    _append_line(lines, "Téléphone", monument.phone)
    _append_line(lines, "Tarif résident", monument.price_resident)
    _append_line(lines, "Tarif étudiant", monument.price_student)
    _append_line(lines, "Tarif étranger", monument.price_foreign)
    _append_line(lines, "Tarif enseignant", monument.price_teacher)
    _append_line(lines, "Tarif retraité", monument.price_senior)
    _append_line(lines, "Tarif enfant", monument.price_child)

    if linked_circuit_names:
        _append_line(lines, "Circuits associés", ", ".join(linked_circuit_names))

    searchable_sentences = _build_searchable_sentences(monument, visit_context)
    if searchable_sentences:
        lines.extend(["", "Résumé pour la recherche:"])
        lines.extend(searchable_sentences)

    if monument.description_fr and monument.description_fr.strip():
        lines.extend(["", "Description:", monument.description_fr.strip()])

    visit_duration_minutes = (
        float(monument.visit_duration_minutes)
        if monument.visit_duration_minutes is not None
        else None
    )
    is_short_visit = (
        visit_duration_minutes is not None
        and visit_duration_minutes <= SHORT_VISIT_MAX_MINUTES
    )
    is_long_visit = (
        visit_context is not None
        and visit_duration_minutes is not None
        and visit_context.long_visit_min_minutes is not None
        and visit_duration_minutes >= visit_context.long_visit_min_minutes
    )

    metadata: dict[str, Any] = {
        "site_id": site_id,
        "site_name": site_name,
        "is_site_root": is_site_root,
        "dominant_period": _clean(monument.dominant_period),
        "secondary_period": _clean(monument.secondary_period),
        "third_period": _clean(monument.third_period),
        "function": _clean(monument.function),
        "status": _clean(monument.status),
        "accessibility": _clean(monument.accessibility),
        "relief": _clean(monument.relief),
        "importance": _clean(monument.importance),
        "visit_duration_minutes": visit_duration_minutes,
        "is_short_visit": is_short_visit,
        "is_long_visit": is_long_visit,
        "reduced_mobility_suitable": _reduced_mobility_suitable(monument),
        "name_aliases": _collect_name_aliases(monument),
        "has_description": bool(monument.description_fr and monument.description_fr.strip()),
        "linked_circuit_names": linked_circuit_names or [],
        "destination_name": "Carthage",
    }

    return GeneratedDocument(
        source_type="monument",
        source_id=monument_source_id(monument.id),
        title=monument.name_fr,
        language="fr",
        text="\n".join(lines),
        metadata=metadata,
    )


def build_circuit_document(circuit: Circuit) -> GeneratedDocument:
    lines = ["Type: circuit"]
    _append_line(lines, "Circuit", circuit.name)
    _append_line(lines, "Nombre d'étapes", circuit.step_count)
    _append_line(lines, "Distance (km)", circuit.distance_km)
    _append_line(lines, "Durée", circuit.duration_display)

    monument_names: list[str] = []
    monument_ids: list[float] = []
    site_ids: set[int] = set()
    dominant_periods: set[str] = set()

    if circuit.monument_links:
        lines.extend(["", "Étapes du circuit:"])
        for link in circuit.monument_links:
            monument = link.monument
            monument_names.append(monument.name_fr)
            monument_ids.append(monument.id)
            site_ids.add(monument_site_id(monument.id))
            period = _clean(monument.dominant_period)
            if period:
                dominant_periods.add(period)
            lines.append(f"{link.position}. {monument.name_fr}")

    if circuit.description_fr and circuit.description_fr.strip():
        lines.extend(["", "Description:", circuit.description_fr.strip()])

    metadata: dict[str, Any] = {
        "step_count": circuit.step_count,
        "distance_km": float(circuit.distance_km) if circuit.distance_km is not None else None,
        "duration_display": _clean(circuit.duration_display),
        "duration_minutes": float(circuit.duration_minutes)
        if circuit.duration_minutes is not None
        else None,
        "monument_ids": monument_ids,
        "monument_names": monument_names,
        "site_ids": sorted(site_ids),
        "dominant_periods": sorted(dominant_periods),
        "has_description": bool(circuit.description_fr and circuit.description_fr.strip()),
        "destination_name": "Carthage",
    }

    return GeneratedDocument(
        source_type="circuit",
        source_id=str(circuit.id),
        title=circuit.name,
        language="fr",
        text="\n".join(lines),
        metadata=metadata,
    )


def build_all_documents(session: Session) -> list[GeneratedDocument]:
    monuments = session.scalars(select(Monument).order_by(Monument.id)).all()
    circuits = session.scalars(
        select(Circuit)
        .options(
            selectinload(Circuit.monument_links).selectinload(CircuitMonument.monument),
        )
        .order_by(Circuit.id)
    ).all()

    visit_context = build_visit_duration_context(monuments)
    site_titles = build_site_titles(monuments)

    circuit_names_by_monument: dict[str, list[str]] = {}
    for circuit in circuits:
        for link in circuit.monument_links:
            circuit_names_by_monument.setdefault(link.monument_id, []).append(circuit.name)

    documents: list[GeneratedDocument] = []
    for monument in monuments:
        documents.append(
            build_monument_document(
                monument,
                linked_circuit_names=circuit_names_by_monument.get(monument.id, []),
                visit_context=visit_context,
                site_titles=site_titles,
            )
        )
    for circuit in circuits:
        documents.append(build_circuit_document(circuit))

    return documents


def load_documents_from_json(path: Path) -> list[GeneratedDocument]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of generated documents")

    documents: list[GeneratedDocument] = []
    for item in payload:
        documents.append(
            GeneratedDocument(
                source_type=str(item["source_type"]),
                source_id=str(item["source_id"]),
                title=str(item["title"]),
                language=str(item.get("language", "fr")),
                text=str(item["text"]),
                metadata=dict(item.get("metadata", {})),
            )
        )
    return documents


def save_documents_to_json(documents: list[GeneratedDocument], path: Path) -> None:
    payload = [
        {
            "source_type": document.source_type,
            "source_id": document.source_id,
            "title": document.title,
            "language": document.language,
            "text": document.text,
            "metadata": document.metadata,
        }
        for document in documents
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
