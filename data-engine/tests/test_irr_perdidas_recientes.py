"""Regla «pérdidas recientes» del motor de TIR (PREREG bear, 9-nov-2026; caso PHM 2013).

Con una pérdida entre los 3 últimos ejercicios, el bajista (y la base, si la mediana caía en pérdidas) ya no
proyecta esa pérdida como margen permanente valorado a un PER positivo, que daba −100 % por construcción.
"""
from __future__ import annotations

import pytest

from app.services.shareholder_irr_service import run_valuation
from app.valuation import shareholder_irr as E
from app.valuation import shareholder_irr_rules as R


def _sp(ni: float = 600.0) -> E.StartingPoint:
    return E.StartingPoint(price=30.0, shares_diluted=380.0, revenue=5700.0, ebitda=None, net_income=ni,
                           debt=2000.0, basis="pe")


def _hist(earnings: list[float]) -> R.History:
    return R.History(years=[2010, 2011, 2012], revenue=[4500.0, 4100.0, 4800.0], earnings=earnings,
                     operating_cash_flow=[300.0, 200.0, 650.0], capex=[-40.0, -40.0, -50.0])


def test_bajista_con_perdidas_usa_el_peor_margen_positivo():
    s = R.build_scenarios(_sp(), _hist([-1100.0, -210.0, 230.0]))
    mg = {k: d.margin_target for k, d in s.drivers.items()}
    assert mg["bear"] == pytest.approx(230.0 / 4800.0)
    assert mg["base"] == pytest.approx(230.0 / 4800.0)  # mediana de los positivos (uno)
    assert all((m or 0) > 0 for m in mg.values())
    assert any("pérdidas en 2010, 2011" in w for w in s.warnings)
    assert s.trace["margen_perdidas"]["anos"] == [2010, 2011]


def test_sin_ningun_margen_positivo_usa_el_de_partida():
    s = R.build_scenarios(_sp(), _hist([-1100.0, -210.0, -5.0]))
    m0 = 600.0 / 5700.0
    assert all(d.margin_target == pytest.approx(m0) for d in s.drivers.values())
    assert any("ninguno: el de partida" in w for w in s.warnings)


def test_sin_perdidas_no_cambia_nada():
    h = _hist([200.0, 210.0, 230.0])
    s = R.build_scenarios(_sp(), h)
    m = [200.0 / 4500.0, 210.0 / 4100.0, 230.0 / 4800.0]
    assert s.drivers["bear"].margin_target == pytest.approx(min(m))
    assert s.drivers["bull"].margin_target == pytest.approx(max(m))
    assert "margen_perdidas" not in s.trace


def test_regla_desactivada_reproduce_el_menos_cien(monkeypatch):
    monkeypatch.setattr(R, "LOSS_MARGIN_RULE", None)
    out = run_valuation(_sp(), _hist([-1100.0, -210.0, 230.0]))
    assert out["scenarios"]["bear"]["horizons"]["5"]["irr"] == pytest.approx(-1.0)


def test_con_la_regla_el_bajista_ya_no_es_capital_cero():
    out = run_valuation(_sp(), _hist([-1100.0, -210.0, 230.0]))
    irr = {k: out["scenarios"][k]["horizons"]["5"]["irr"] for k in R.SCENARIOS}
    assert irr["bear"] > -0.5
    assert irr["bear"] <= irr["base"] <= irr["bull"]


def test_solo_bajista_deja_base_y_alcista(monkeypatch):
    monkeypatch.setattr(R, "LOSS_MARGIN_RULE", "bear")
    h = _hist([-1100.0, 150.0, 230.0])
    s = R.build_scenarios(_sp(), h)
    m = [-1100.0 / 4500.0, 150.0 / 4100.0, 230.0 / 4800.0]
    assert s.drivers["bear"].margin_target == pytest.approx(150.0 / 4100.0)
    assert s.drivers["base"].margin_target == pytest.approx(sorted(m)[1])


def test_valor_contable_no_cambia():
    sp = E.StartingPoint(price=50.0, shares_diluted=100.0, revenue=4000.0, ebitda=None, net_income=400.0, basis="pb")
    s = R.build_scenarios(sp, R.History(years=[2010, 2011, 2012], revenue=[3600.0, 3800.0, 4000.0],
                                        earnings=[-100.0, 300.0, 400.0]))
    assert "margen_perdidas" not in s.trace
    assert s.drivers["bear"].margin_target == pytest.approx(-100.0 / 3600.0)
