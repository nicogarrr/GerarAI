"""Estimación propia de ingresos por fase e industria (fase-industria-v1, PREREG bear 9-nov-2026)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.pre_revenue_valuation import own_estimate_anchor
from app.valuation import pre_revenue_irr as rules
from app.valuation import revenue_phase_rates as R


def test_fases_y_tabla():
    assert R.phase_for(0.5) is None and R.phase_for(5) == "F1" and R.phase_for(30) == "F2" and R.phase_for(60) == "F3"
    assert R.phase_for(300) is None
    for cell in R.RATES.values():
        assert cell["p25"] <= cell["p50"] <= cell["p75"] and cell["n"] >= R.MIN_N


def test_estimacion_con_su_cifra_y_fuente():
    est, label = R.estimate(2836, 60.0, 5)
    cell = R.RATES[("283", "F3", 5)]
    assert est is not None
    assert est["base"] == pytest.approx(60.0 * cell["p50"])
    assert est["low"] == pytest.approx(60.0 * cell["p25"]) and est["high"] == pytest.approx(60.0 * cell["p75"])
    assert "estimación propia" in label and "SIC 283x" in label and f"n = {cell['n']}" in label


@pytest.mark.parametrize(("sic", "rev", "why"), [
    (None, 60.0, "sin SIC"), (2836, 0.0, "sin ingresos"), (2836, 0.4, "< 1 M"), (2836, 900.0, "≥ 250 M"),
    (3663, 60.0, "sin tasa base para SIC 366x"),
])
def test_sin_tabla_es_nd_con_motivo(sic, rev, why):
    est, label = R.estimate(sic, rev, 5)
    assert est is None and why in label


def test_ancla_solo_si_no_hay_otra():
    own = rules.RevenueAnchor(2029, 75.0, 36.0, 152.0, "estimacion_propia", "estimación propia")
    backlog = rules.RevenueAnchor(2027, 20.0, None, None, "backlog", "cartera")
    guide = rules.RevenueAnchor(2028, 90.0, None, None, "guia", "guía")
    assert rules.choose_anchor([own, backlog], 2024)[0] is backlog
    assert rules.choose_anchor([own, guide], 2024)[0] is guide
    assert rules.choose_anchor([own], 2024)[0] is own


def test_ancla_desde_la_ficha():
    co = SimpleNamespace(factor_tags=["sic:2836"], industry=None)
    a = own_estimate_anchor(co, last_fy=2025, last_revenue=60.0)  # type: ignore[arg-type]
    assert a is not None and a.year == 2030 and a.source == "estimacion_propia"
    assert a.cite["n"] == R.RATES[("283", "F3", 5)]["n"] and a.cite["sic_group"] == "283"
    assert own_estimate_anchor(co, last_fy=2025, last_revenue=None) is None  # type: ignore[arg-type]
