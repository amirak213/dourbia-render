from __future__ import annotations

from dataclasses import dataclass

from app.circuits.data_loader import MonumentNode, normalize_name


@dataclass(frozen=True)
class ConstraintContext:
    budget_max: float
    duration_minutes: float
    mobilite: str
    required_ids: frozenset[str]
    excluded_ids: frozenset[str]
    max_stops: int = 12


def filter_monuments(
    nodes: dict[str, MonumentNode],
    context: ConstraintContext,
) -> tuple[dict[str, MonumentNode], list[str]]:
    warnings: list[str] = []
    candidates: dict[str, MonumentNode] = {}

    for monument_id, node in nodes.items():
        if monument_id in context.excluded_ids:
            continue
        if node.latitude == 0 and node.longitude == 0:
            warnings.append(f"Monument sans coordonnées exclu: {node.name}")
            continue
        if not _mobility_ok(node, context.mobilite):
            if monument_id in context.required_ids:
                warnings.append(
                    f"Mobilité limitée mais monument requis conservé: {node.name}"
                )
            else:
                continue
        if (
            node.price is not None
            and node.price > context.budget_max
            and monument_id not in context.required_ids
        ):
            continue
        candidates[monument_id] = node

    for required_id in context.required_ids:
        if required_id not in candidates:
            if required_id in nodes:
                candidates[required_id] = nodes[required_id]
                warnings.append(f"Monument requis ajouté malgré les filtres: {nodes[required_id].name}")
            else:
                warnings.append(f"Monument requis introuvable: id={required_id}")

    if not candidates:
        warnings.append("Aucun monument candidat après filtrage.")

    return candidates, warnings


def _mobility_ok(node: MonumentNode, mobilite: str) -> bool:
    mobility = normalize_name(mobilite)
    accessibility = normalize_name(node.accessibility or "")
    relief = normalize_name(node.relief or "")

    if mobility in {"normale", "full", "complete"}:
        return True
    if mobility in {"reduite", "reduced", "reduite"}:
        blocked = ("inaccessible", "difficile", "escalier", "pente forte")
        return not any(token in accessibility or token in relief for token in blocked)
    if mobility in {"limitee", "limited", "limitee"}:
        blocked = ("inaccessible", "difficile", "escalier", "pente", "non accessible")
        return not any(token in accessibility or token in relief for token in blocked)
    return True


def check_constraints_status(
    *,
    total_cost: float,
    total_duration: float,
    context: ConstraintContext,
    candidates: dict[str, MonumentNode],
    chromosome: list[str],
) -> dict[str, bool]:
    mobility_ok = True
    for monument_id in chromosome:
        node = candidates.get(monument_id)
        if node is not None and not _mobility_ok(node, context.mobilite):
            mobility_ok = False
            break

    return {
        "budget_ok": total_cost <= context.budget_max + 1e-6,
        "duration_ok": total_duration <= context.duration_minutes + 1e-6,
        "mobility_ok": mobility_ok,
    }
