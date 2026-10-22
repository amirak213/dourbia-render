"""
ToolRegistry — Registre dynamique des outils.
Les tools s'enregistrent eux-mêmes. Le planner découvre les tools disponibles.
Extensible sans modifier le core agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class ToolSpec:
    """Spécification complète d'un outil."""
    name:        str
    description: str
    parameters:  dict
    handler:     Callable
    category:    str = "weather"
    version:     str = "1.0"


class ToolRegistry:
    """
    Registre centralisé des tools.
    Pattern : decorator @registry.register(...)
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name:        str,
        description: str,
        parameters:  dict,
        category:    str = "weather",
    ) -> Callable:
        """Décorateur d'enregistrement."""
        def decorator(fn: Callable) -> Callable:
            self._tools[name] = ToolSpec(
                name        = name,
                description = description,
                parameters  = parameters,
                handler     = fn,
                category    = category,
            )
            return fn
        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def describe_all(self) -> str:
        """Description textuelle de tous les tools pour le planner."""
        lines = []
        for spec in self._tools.values():
            params = json.dumps(spec.parameters, ensure_ascii=False)
            lines.append(f"- {spec.name}: {spec.description}\n  Params: {params}")
        return "\n".join(lines)

    def to_openai_format(self) -> list[dict]:
        """Format OpenAI function-calling pour le LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name":        spec.name,
                    "description": spec.description,
                    "parameters":  spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]