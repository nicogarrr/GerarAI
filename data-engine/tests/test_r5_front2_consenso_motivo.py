"""Consenso propio: el motivo de un N/D se lee en castellano normal (r5-front2).

Antes: «ninguna fuente disponible pasa las puertas» (jerga interna) en cada celda sin estimación.
"""
from __future__ import annotations

from tests.test_own_consensus_eps_model import _cells


def test_sin_estimacion_motivo_legible() -> None:
    eps, _ = _cells({"2024-12-31:FY": -1.0, "2025-12-31:FY": -0.5})
    cell = eps["fy2026"]
    assert cell.status == "sin_estimacion"
    reason = cell.reason
    assert "puertas" not in reason
    assert reason == ("ninguna fuente (guía de la empresa, analistas citados, modelo propio o tasa base) "
                      "cumple los requisitos para este periodo")
