from __future__ import annotations

from app.circuits.data_loader import MonumentNode, normalize_name


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _period_match(node: MonumentNode, preferred_periods: list[str]) -> float:
    if not preferred_periods:
        return 0.5
    periods = [
        normalize_name(node.dominant_period or ""),
        normalize_name(node.secondary_period or ""),
        normalize_name(node.third_period or ""),
    ]
    best = 0.0
    for pref in preferred_periods:
        pref_norm = normalize_name(pref)
        if not pref_norm:
            continue
        for idx, period in enumerate(periods):
            if not period:
                continue
            if pref_norm in period or period in pref_norm:
                weight = 1.0 if idx == 0 else 0.6 if idx == 1 else 0.3
                best = max(best, weight)
    return best


def _function_match(node: MonumentNode, preferred_functions: list[str]) -> float:
    if not preferred_functions:
        return 0.5
    function = normalize_name(node.function or "")
    if not function:
        return 0.0
    best = 0.0
    for pref in preferred_functions:
        pref_norm = normalize_name(pref)
        if pref_norm and (pref_norm in function or function in pref_norm):
            best = 1.0
            break
    return best


def _priority_score(node: MonumentNode) -> float:
    return _clamp01((node.priority - 1.0) / 4.0)


def _budget_compatibility(node: MonumentNode, budget_max: float) -> float:
    if budget_max <= 0:
        return 0.0
    if node.price is None:
        return 0.5
    if node.price <= budget_max:
        return 1.0
    return _clamp01(budget_max / max(node.price, 1e-6))


def _mobility_compatibility(node: MonumentNode, mobilite: str) -> float:
    mobility = normalize_name(mobilite)
    accessibility = normalize_name(node.accessibility or "")
    relief = normalize_name(node.relief or "")
    if mobility in {"normale", "full", "complete"}:
        return 1.0
    if mobility in {"reduite", "reduced"}:
        if any(token in accessibility or token in relief for token in ("inaccessible", "difficile")):
            return 0.2
        return 0.8
    if any(token in accessibility or token in relief for token in ("inaccessible", "difficile", "escalier")):
        return 0.1
    return 0.6


def score_monument(
    node: MonumentNode,
    *,
    preferred_periods: list[str],
    preferred_functions: list[str],
    budget_max: float,
    mobilite: str,
) -> float:
    score = (
        0.35 * _period_match(node, preferred_periods)
        + 0.25 * _function_match(node, preferred_functions)
        + 0.20 * _priority_score(node)
        + 0.10 * _budget_compatibility(node, budget_max)
        + 0.10 * _mobility_compatibility(node, mobilite)
    )
    return _clamp01(score)


def score_monuments(
    candidates: dict[str, MonumentNode],
    *,
    preferred_periods: list[str],
    preferred_functions: list[str],
    budget_max: float,
    mobilite: str,
) -> dict[str, float]:
    return {
        monument_id: score_monument(
            node,
            preferred_periods=preferred_periods,
            preferred_functions=preferred_functions,
            budget_max=budget_max,
            mobilite=mobilite,
        )
        for monument_id, node in candidates.items()
    }


def preference_reason(
    node: MonumentNode,
    preferred_periods: list[str],
    preferred_functions: list[str],
) -> str:
    period_score = _period_match(node, preferred_periods)
    function_score = _function_match(node, preferred_functions)
    if period_score >= function_score and period_score >= 0.6:
        return "Correspond à votre intérêt pour l'époque historique demandée."
    if function_score >= 0.6:
        return "Correspond à vos préférences de type de monument."
    if node.priority >= 4:
        return "Site prioritaire recommandé à Carthage."
    return "Ajouté pour optimiser la durée et le budget du circuit."
