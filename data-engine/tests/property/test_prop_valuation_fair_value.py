"""Propiedades de valoración derivadas a mano (lane test-gaps).

- El valor razonable con entradas positivas nunca es negativo.
- El potencial V/P - 1 nunca baja de -100 % cuando hay margen publicable.
- Entradas negativas o no finitas dan N/D (None) o error explícito, nunca una cifra.
"""

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.dividend_equity import DdmInputError, gordon_value
from app.valuation.engines.base import (
    margin_of_safety,
    margin_of_safety_from_upside,
    upside_from_margin_of_safety,
)
from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth
from app.valuation.scenario_model import Scenario, probability_weighted_value

S = settings(max_examples=300, deadline=None, derandomize=True)
pos = st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False)


@S
@given(pos, pos)
def test_margin_and_upside_are_bounded_for_positive_value_and_price(value, price):
    assume(1e-4 <= value / price <= 1e4)  # fuera de ahí 1/(1-m) pierde precisión float
    m = margin_of_safety(value, price)
    assert m is not None and m < 1
    upside = upside_from_margin_of_safety(m)
    assert upside > -1
    assert math.isclose(upside, value / price - 1, rel_tol=1e-6, abs_tol=1e-9)
    assert math.isclose(margin_of_safety_from_upside(upside), m, rel_tol=1e-9, abs_tol=1e-9)


@pytest.mark.parametrize(
    "value,price",
    [(0, 10), (-5, 10), (10, 0), (10, -1), (float("nan"), 10), (10, float("inf")), (None, 10)],
)
def test_margin_is_nd_for_non_positive_or_non_finite_inputs(value, price):
    assert margin_of_safety(value, price) is None


def test_margin_hand_derived():
    # V=130, P=100: margen (130-100)/130 = 0,230769; potencial 30 %.
    m = margin_of_safety(130.0, 100.0)
    assert math.isclose(m, 30 / 130)
    assert math.isclose(upside_from_margin_of_safety(m), 0.30)


dcf_in = st.fixed_dictionaries(
    {
        "revenue": pos,
        "revenue_growth": st.floats(-0.15, 0.45),
        "fcf_margin": st.floats(0.01, 0.6),
        "wacc": st.floats(0.05, 0.2),
        "terminal_growth": st.floats(0.0, 0.03),
        "shares_outstanding": pos,
    }
)


@S
@given(dcf_in)
def test_dcf_value_is_positive_with_positive_cash_flows_and_no_debt(d):
    r = run_dcf(DCFInputs(net_debt=0.0, **d))
    assert math.isfinite(r.value_per_share) and r.value_per_share > 0
    # doble de acciones -> mitad de valor por acción
    r2 = run_dcf(DCFInputs(net_debt=0.0, **{**d, "shares_outstanding": d["shares_outstanding"] * 2}))
    assert math.isclose(r2.value_per_share * 2, r.value_per_share, rel_tol=1e-9)
    # más WACC -> menos valor; más margen -> más valor
    r3 = run_dcf(DCFInputs(net_debt=0.0, **{**d, "wacc": d["wacc"] + 0.01}))
    assert r3.value_per_share < r.value_per_share
    r4 = run_dcf(DCFInputs(net_debt=0.0, **{**d, "fcf_margin": d["fcf_margin"] * 1.1}))
    assert r4.value_per_share > r.value_per_share


def test_dcf_hand_derived_one_year():
    # Ingresos 100, +10 % -> 110; FCF 10 % = 11; WACC 10 %, g 0:
    # PV FCF = 10; TV = 11/0.10 = 110 -> PV 100; EV 110; deuda 10 -> 100 / 10 acc = 10.
    r = run_dcf(
        DCFInputs(
            revenue=100,
            revenue_growth=0.10,
            fcf_margin=0.10,
            wacc=0.10,
            terminal_growth=0.0,
            net_debt=10,
            shares_outstanding=10,
            years=1,
        )
    )
    assert math.isclose(r.enterprise_value, 110.0)
    assert math.isclose(r.value_per_share, 10.0)


@pytest.mark.parametrize(
    "override",
    [
        {"shares_outstanding": 0},
        {"shares_outstanding": -1},
        {"wacc": 0.02, "terminal_growth": 0.03},
        {"years": 0},
        {"wacc": -1.5, "terminal_growth": -2.0},
    ],
)
def test_dcf_rejects_invalid_inputs(override):
    base = dict(
        revenue=100,
        revenue_growth=0.05,
        fcf_margin=0.1,
        wacc=0.1,
        terminal_growth=0.02,
        net_debt=0,
        shares_outstanding=10,
    )
    with pytest.raises(ValueError):
        run_dcf(DCFInputs(**{**base, **override}))


@S
@given(dcf_in, st.floats(0.5, 2.0))
def test_reverse_dcf_growth_reproduces_the_price(d, k):
    d = {**d}
    d.pop("revenue_growth")
    price = run_dcf(DCFInputs(revenue_growth=0.05, net_debt=0.0, **d)).value_per_share * k
    assume(math.isfinite(price) and price > 0)
    out = solve_required_growth(ReverseDCFInputs(market_price=price, net_debt=0.0, **d))
    if out.get("out_of_bounds"):
        return
    g = out["required_revenue_growth"]
    v = run_dcf(DCFInputs(revenue_growth=g, net_debt=0.0, **d)).value_per_share
    assert math.isclose(v, price, rel_tol=1e-6)


@S
@given(st.floats(0.01, 100), st.floats(0.0, 0.2), st.floats(-0.05, 0.19))
def test_gordon_positive_or_explicit_error(dividend, ke, g):
    if ke <= g:
        with pytest.raises(DdmInputError):
            gordon_value(dividend, ke, g)
        return
    v = gordon_value(dividend, ke, g)
    assert v > 0
    assert math.isclose(v, dividend * (1 + g) / (ke - g))


@S
@given(st.lists(st.tuples(st.floats(0.01, 1), st.floats(0.01, 1e4)), min_size=1, max_size=5))
def test_probability_weighted_value_is_a_convex_mix(items):
    scenarios = [Scenario(f"s{i}", p, v) for i, (p, v) in enumerate(items)]
    ev = probability_weighted_value(scenarios)["expected_value"]
    vals = [v for _, v in items]
    assert min(vals) - 1e-9 <= ev <= max(vals) + 1e-9
