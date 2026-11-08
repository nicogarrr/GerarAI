"""Acierto de estimaciones: nada se aparta en silencio (hallazgo del auditor sobre #4759).

Antes: un BPA real de −0,50 frente a +1,00 estimado (pérdida cuando se esperaba beneficio) o un
real 4 veces la estimación se apartaban como «lectura inverosímil» y el resumen no decía cuántos.
Ahora solo se aparta lo que no puede estar en la misma unidad (×1.000, ×1.000.000) y el resumen
cuenta lo apartado y los errores extremos."""
from __future__ import annotations

from datetime import date

from app.services import estimate_accuracy as ea
from app.services.own_consensus import Actual


def _acts(value: float, metric: str = "eps") -> dict[str, dict[str, Actual]]:
    return {metric: {"fy2025": Actual("fy2025", date(2025, 12, 31), value, date(2026, 2, 1), None),
                     "fy2024": Actual("fy2024", date(2024, 12, 31), 1.0, date(2025, 2, 1), None)}}


def _est(mid: float, metric: str = "eps") -> ea.Estimate:
    return ea.Estimate("guia", metric, "fy2025", None, mid, None, date(2025, 3, 1))


def test_cambio_de_signo_cuenta_como_fallo() -> None:
    [case] = ea.cases([_est(1.0)], _acts(-0.5))
    assert case["excluded"] is None
    assert case["error"] == -1.5
    assert any(f.startswith("signo_contrario") for f in case["flags"])
    assert ea.measured_errors([case]) == {("guia", case["horizon"]): [-1.5]}


def test_error_grande_cuenta_y_se_marca() -> None:
    [case] = ea.cases([_est(0.10)], _acts(0.40))
    assert case["excluded"] is None
    assert any(f.startswith("error_extremo") for f in case["flags"])
    [row] = ea.summarize([case])
    assert row["n"] == 1 and row["n_extreme"] == 1 and row["n_excluded"] == 0


def test_escala_distinta_se_aparta_con_motivo_y_se_cuenta() -> None:
    [case] = ea.cases([_est(125.0, "revenue")], _acts(125_400.0, "revenue"))
    assert case["excluded"] and case["excluded"].startswith("escala_distinta")
    [row] = ea.summarize([case])
    assert row["n"] == 0 and row["n_excluded"] == 1 and row["excluded_reasons"] == ["escala_distinta"]
    assert ea.measured_errors([case]) == {}


def test_error_normal_sin_marcas() -> None:
    [case] = ea.cases([_est(1.0)], _acts(1.1))
    assert case["excluded"] is None and case["flags"] == []
