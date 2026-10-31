"""«Crecimiento implícito» en el Reverse DCF (idea Jera Value): g = WACC − FCF/EV,
reparto del valor por años y rejilla de sensibilidad WACC × margen FCF."""

from __future__ import annotations

import pytest

from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.reverse_dcf import (
    ReverseDCFInputs,
    growth_sensitivity,
    implied_perpetual_growth,
    value_split,
)


def test_implied_perpetual_growth_is_wacc_minus_fcf_yield():
    # FCF 50, EV 1.000, WACC 9 % -> 9 % - 5 % = 4 %
    assert implied_perpetual_growth(fcf=50.0, enterprise_value=1000.0, wacc=0.09) == pytest.approx(0.04)
    assert implied_perpetual_growth(fcf=50.0, enterprise_value=0.0, wacc=0.09) is None


@pytest.mark.parametrize("years", [5, 10])
def test_value_split_adds_up_to_the_model_value(years):
    split = value_split(revenue=1000.0, growth=0.08, fcf_margin=0.2, wacc=0.09, terminal_growth=0.025, years=years)
    assert split is not None
    assert sum(split.values()) == pytest.approx(1.0, abs=1e-3)
    # El terminal es la mayor parte con un crecimiento moderado y WACC 9 %.
    assert split["years_11_plus"] > split["years_6_10"] > 0
    # Con años = horizonte del modelo, el trozo 11+ coincide con el peso del terminal en run_dcf.
    if years == 10:
        dcf = run_dcf(DCFInputs(revenue=1000.0, revenue_growth=0.08, fcf_margin=0.2, wacc=0.09, terminal_growth=0.025,
                                net_debt=0.0, shares_outstanding=1.0, years=10))
        explicit = sum(1000.0 * 1.08 ** t * 0.2 / 1.09 ** t for t in range(1, 11))
        assert split["years_11_plus"] == pytest.approx(1 - explicit / dcf.value_per_share, abs=1e-3)


def test_value_split_refuses_unusable_inputs():
    assert value_split(revenue=1000.0, growth=0.05, fcf_margin=-0.1, wacc=0.09, terminal_growth=0.02, years=5) is None
    assert value_split(revenue=1000.0, growth=0.05, fcf_margin=0.1, wacc=0.02, terminal_growth=0.03, years=5) is None


def test_sensitivity_grid_is_3x3_and_moves_the_right_way():
    base = ReverseDCFInputs(market_price=40.0, revenue=1000.0, fcf_margin=0.15, wacc=0.09, terminal_growth=0.025,
                            net_debt=0.0, shares_outstanding=100.0, years=5)
    grid = growth_sensitivity(base)
    assert grid["wacc"] == [0.08, 0.09, 0.1] and grid["fcf_margin"] == [0.13, 0.15, 0.17]
    rows = grid["required_growth"]
    assert len(rows) == 3 and all(len(r) == 3 for r in rows)
    middle = rows[1][1]
    assert middle is not None
    # Más WACC exige más crecimiento; más margen exige menos.
    assert rows[2][1] > middle > rows[0][1]
    assert rows[1][0] > middle > rows[1][2]
