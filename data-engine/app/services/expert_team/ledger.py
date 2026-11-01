"""Registro de evidencia POR CORRIDA: lo único que se puede citar."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.expert_team.models import Evidence


class EvidenceLedger:
    """Cada resultado de herramienta recibe un id ``ev-N`` único en la corrida.

    No hay estado compartido entre corridas: un ledger nuevo por ``run``.
    """

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def add(self, *, expert: str, tool: str, source: Mapping[str, str], data: Any) -> Evidence:
        evidence = Evidence(
            id=f"ev-{len(self._items) + 1}",
            tool=tool,
            expert=expert,
            source={str(k): str(v) for k, v in dict(source).items()},
            data=data,
        )
        self._items[evidence.id] = evidence
        return evidence

    def get(self, evidence_id: str) -> Evidence | None:
        return self._items.get(evidence_id)

    def items(self) -> list[Evidence]:
        return list(self._items.values())
