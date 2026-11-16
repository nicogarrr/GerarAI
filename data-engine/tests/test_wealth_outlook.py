"""Propiedades de la ilustracion pura; ningun precio o rentabilidad real."""
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.savings_projection import project_savings
from app.services.wealth_outlook import project_wealth


def _project(**overrides):
    args = dict(initial_capital=10_000, monthly=500, years=30,
                annual_return=0.05, inflation=0.02)
    args.update(overrides)
    return project_wealth(**args)


@pytest.mark.parametrize("rate", [0, 0.03, 0.05, 0.07, -0.1])
def test_sin_capital_ni_costes_coincide_con_savings(rate):
    old = project_savings(monthly=1000, years=30, annual_return=rate, inflation=.02)
    result = _project(initial_capital=0, monthly=1000, annual_return=rate)
    assert result["terminal_gross"] == old["terminal_value"]
    assert result["terminal_after_costs_before_tax"] == old["terminal_value"]
    assert result["terminal_gross_today_money"] == old["terminal_value_today_money"]
    assert result["future_contributions"] == old["contributed"]


def test_cero_retorno_suma_capital_y_aportaciones():
    result = _project(annual_return=0, inflation=0)
    assert result["terminal_gross"] == 10_000 + 500 * 360
    assert result["terminal_after_costs_before_tax"] == result["terminal_gross"]
    assert result["total_capital_supplied"] == result["terminal_gross"]
    assert result["terminal_net_after_tax"] is None
    assert result["tax_status"] == "not_modelled"
    assert any("Puedes perder capital" in text for text in result["assumptions"])


def test_costes_entrada_se_restan_de_la_cuota_y_capital_no_paga_otra_vez():
    result = _project(annual_return=0, inflation=0, years=1,
                      contribution_fee=2, contribution_spread=.01)
    assert result["monthly_invested_after_entry_costs"] == 493.02
    assert result["terminal_after_costs_before_tax"] == 10_000 + 493.02 * 12
    assert result["terminal_gross"] == 16_000
    assert _project(monthly=0)["terminal_gross"] == round(10_000 * 1.05**30, 2)


def test_capital_y_aportaciones_tienen_tiempos_distintos():
    result = _project(years=1, annual_return=.12, annual_cost=.02,
                      contribution_fee=3, contribution_spread=.01)
    gross, net = 10_000.0, 10_000.0
    for _ in range(12):
        gross = gross * 1.12**(1/12) + 500
        net = net * (1.12*.98)**(1/12) + 497*.99
    assert result["terminal_gross"] == round(gross, 2)
    assert result["terminal_after_costs_before_tax"] == round(net, 2)


def test_coste_total_y_aportacion_consumida():
    result = _project(annual_cost=1)
    assert result["terminal_after_costs_before_tax"] == 500
    assert _project(contribution_fee=500, initial_capital=0)["terminal_after_costs_before_tax"] == 0
    assert _project(contribution_spread=1, initial_capital=0)["terminal_after_costs_before_tax"] == 0
    assert _project(annual_return=-.5)["terminal_gross"] < 190_000
    assert _project(initial_capital=0, monthly=0)["terminal_gross"] == 0


@pytest.mark.parametrize("field", ["initial_capital", "monthly", "annual_return", "inflation",
                                  "contribution_fee", "contribution_spread", "annual_cost"])
@pytest.mark.parametrize("bad", [True, None, "1", float("nan"), float("inf"), float("-inf")])
def test_rechaza_numeros_no_validos(field, bad):
    with pytest.raises(ValueError):
        _project(**{field: bad})


@pytest.mark.parametrize("overrides", [
    {"years": True}, {"years": 0}, {"years": 81}, {"years": 1.5},
    {"initial_capital": -1}, {"initial_capital": 1e13}, {"monthly": -1},
    {"monthly": 1_000_001}, {"annual_return": -1}, {"annual_return": 1.01},
    {"inflation": -1}, {"inflation": 1.01}, {"contribution_fee": -1},
    {"contribution_fee": 501}, {"contribution_spread": -.01},
    {"contribution_spread": 1.01}, {"annual_cost": -.01}, {"annual_cost": 1.01},
])
def test_rechaza_rangos_y_comision_superior_a_aportacion(overrides):
    with pytest.raises(ValueError):
        _project(**overrides)


@settings(max_examples=80, deadline=None)
@given(capital=st.integers(0, 1_000_000), monthly=st.integers(0, 10_000),
       years=st.integers(1, 80), rate=st.floats(-.9, .3, allow_nan=False),
       cost=st.floats(0, .1, allow_nan=False))
def test_costes_no_suben_el_saldo_y_no_cambian_bruto(capital, monthly, years, rate, cost):
    base = _project(initial_capital=capital, monthly=monthly, years=years, annual_return=rate)
    charged = _project(initial_capital=capital, monthly=monthly, years=years,
                       annual_return=rate, annual_cost=cost,
                       contribution_fee=monthly*.01, contribution_spread=cost)
    assert charged["terminal_gross"] == base["terminal_gross"]
    assert 0 <= charged["terminal_after_costs_before_tax"] <= base["terminal_gross"] + .01


@settings(max_examples=50, deadline=None)
@given(capital=st.integers(0, 1_000_000), monthly=st.integers(0, 10_000),
       years=st.integers(1, 80), inflation=st.floats(0, .1, allow_nan=False))
def test_inflacion_no_altera_nominal_y_baja_dinero_de_hoy(capital, monthly, years, inflation):
    base = _project(initial_capital=capital, monthly=monthly, years=years, inflation=0)
    result = _project(initial_capital=capital, monthly=monthly, years=years, inflation=inflation)
    assert result["terminal_gross"] == base["terminal_gross"]
    assert result["terminal_gross_today_money"] <= base["terminal_gross"]


def test_extremos_soportados_siguen_finitos():
    for rate in (-.99, 1):
        result = _project(initial_capital=1e12, monthly=1e6, years=80,
                          annual_return=rate, inflation=-.99)
        assert all(math.isfinite(result[k]) for k in (
            "terminal_gross", "terminal_after_costs_before_tax", "terminal_gross_today_money"))
