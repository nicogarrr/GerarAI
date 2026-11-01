"""Equipo de expertos con coordinador (detrás de EXPERT_TEAM_ENABLED, defecto apagado).

Diseño: un coordinador planifica qué expertos llamar, cada experto recoge datos
SOLO con sus herramientas de lectura (lista blanca), razona con UNA llamada LLM
con su prompt versionado y devuelve afirmaciones con citas a la evidencia de
ESTA corrida. Las afirmaciones sin cita válida se descartan.

Con el flag apagado nada de esto se ejecuta: tesis y chat siguen por su camino.
"""

from __future__ import annotations

from app.services.expert_team.coordinator import ExpertTeam
from app.services.expert_team.experts import ExpertSpec, Reasoner
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import (
    Claim,
    Evidence,
    ExpertReport,
    RunContext,
    TeamResult,
    ToolOutput,
    ToolSpec,
)


def expert_team_enabled() -> bool:
    """Interruptor maestro (env EXPERT_TEAM_ENABLED). Defecto: False."""
    from app.core.config import get_settings

    return bool(getattr(get_settings(), "expert_team_enabled", False))


__all__ = [
    "Claim",
    "Evidence",
    "EvidenceLedger",
    "ExpertReport",
    "ExpertSpec",
    "ExpertTeam",
    "Reasoner",
    "RunContext",
    "TeamResult",
    "ToolOutput",
    "ToolSpec",
    "expert_team_enabled",
]
