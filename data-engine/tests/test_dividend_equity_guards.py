"""DDM/Gordon: el motor no publica números que no puede defender.

Run from data-engine/:
    pytest tests/test_dividend_equity_guards.py -v
"""

import pytest

from app.valuation.dividend_equity import (
    DdmInputError,
    DdmInputs,
    equity_method_sensitivity,
    gordon_value,
    is_finite,
    run_ddm,
    solve_required_dividend_growth,
)


def _ddm(**over):
    base = dict(dividend_per_share=2.0, cost_of_equity=0.08, stage1_growth=0.05,
                stage1_years=0, stage2_growth=0.03, shares_diluted=10.0)
    base.update(over)
    return DdmInputs(**base)


def test_single_stage_ddm_equals_gordon_on_paper():
    # gordon_value recibe D0 y proyecta D1 = D0*(1+g): 2*1.03/(0.08-0.03) = 41.2
    assert run_ddm(_ddm()).value_per_share == pytest.approx(41.2)
    assert gordon_value(2.0, 0.08, 0.03) == pytest.approx(41.2)


@pytest.mark.parametrize("ke,g", [(0.03, 0.03), (0.02, 0.03)])
def test_gordon_refuses_ke_not_above_g(ke, g):
    with pytest.raises(DdmInputError) as exc:
        gordon_value(1.0, ke, g)
    assert exc.value.missing_input == "cost_of_equity_above_dividend_growth"


def test_negative_stage1_years_and_nonpositive_payout_are_rejected_with_named_input():
    with pytest.raises(DdmInputError) as e1:
        run_ddm(_ddm(stage1_years=-1))
    assert e1.value.missing_input == "non_negative_stage1_years"
    for payout in (0.0, -0.2):
        with pytest.raises(DdmInputError) as e2:
            run_ddm(_ddm(payout_ratio=payout))
        assert e2.value.missing_input == "positive_payout_ratio"


def test_equity_method_sensitivity_marks_impossible_cells_instead_of_clamping():
    out = equity_method_sensitivity(dividend_or_fcfe=2.0, cost_of_equity=0.04, terminal_growth=0.03)
    rows = out["rows"]
    assert len(rows) == 3
    # ke = 3 % (fila 0) con g >= 3 %: ke <= g => None con error explícito
    low_ke = rows[0]["values"]
    assert [c["value_per_share"] for c in low_ke[1:]] == [None, None]
    assert all(c["error"] == "cell_out_of_range" for c in low_ke[1:])
    # fila de ke 5 %: valor finito = D0*(1+g)/(ke-g)
    high_ke = rows[2]["values"]
    g0 = high_ke[0]["terminal_growth"]
    assert high_ke[0]["value_per_share"] == pytest.approx(2.0 * (1 + g0) / (0.05 - g0))
    assert out["trace"]["method"] == "equity_method_gordon_sensitivity"


def test_equity_method_sensitivity_custom_growth_values():
    out = equity_method_sensitivity(dividend_or_fcfe=1.0, cost_of_equity=0.10, terminal_growth=0.02,
                                    growth_values=[0.0, 0.05])
    assert [c["terminal_growth"] for c in out["rows"][1]["values"]] == [0.0, 0.05]
    assert out["rows"][1]["values"][1]["value_per_share"] == pytest.approx(1.0 * 1.05 / 0.05)


def test_reverse_ddm_finds_growth_that_reproduces_price():
    kw = dict(dividend_per_share=2.0, cost_of_equity=0.08, stage2_growth=0.03, stage1_years=5)
    r = solve_required_dividend_growth(market_price=50.0, **kw)
    assert r["status"] == "ok" and r["out_of_bounds"] is False
    back = run_ddm(DdmInputs(dividend_per_share=2.0, cost_of_equity=0.08, stage1_growth=r["required_stage1_growth"],
                             stage1_years=5, stage2_growth=0.03, shares_diluted=1.0)).value_per_share
    assert back == pytest.approx(50.0, rel=1e-6)
    assert r["required_growth_gap_vs_model_growth"] == pytest.approx(r["required_stage1_growth"] - 0.03)


def test_reverse_ddm_saturates_instead_of_reporting_impossible_growth():
    kw = dict(dividend_per_share=2.0, cost_of_equity=0.08, stage2_growth=0.03, stage1_years=5)
    above = solve_required_dividend_growth(market_price=1000.0, **kw)
    below = solve_required_dividend_growth(market_price=1.0, **kw)
    for r in (above, below):
        assert r["status"] == "out_of_bounds" and r["required_stage1_growth"] is None
    assert "ceiling" in above["reason"] and "floor" in below["reason"]


def test_reverse_ddm_not_computable_when_ke_equals_terminal_growth():
    r = solve_required_dividend_growth(market_price=50.0, dividend_per_share=2.0, cost_of_equity=0.03,
                                       stage2_growth=0.03)
    assert r["status"] == "not_computable" and r["required_stage1_growth"] is None


def test_is_finite():
    assert is_finite(1.0) and not is_finite(None) and not is_finite(float("inf")) and not is_finite(float("nan"))
