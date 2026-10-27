"""Puente EV -> equity con minoritarios y preferentes (calculo a mano)."""

import pytest

from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth


def _inputs(**overrides):
    base = {
        "revenue": 100.0, "revenue_growth": 0.0, "fcf_margin": 0.10, "wacc": 0.10,
        "terminal_growth": 0.0, "net_debt": 20.0, "shares_outstanding": 10.0, "years": 1,
    }
    base.update(overrides)
    return DCFInputs(**base)


def test_equity_bridge_subtracts_minorities_and_preferred_hand_computed():
    """FCF 10 constante, WACC 10 %, g 0, 1 año:
    PV(FCF1) = 10/1,1 = 9,0909; VT = 10/0,10 = 100; PV(VT) = 100/1,1 = 90,909;
    EV = 100. Equity = 100 - 20 (deuda neta) - 5 (minoritarios) - 15
    (preferentes) = 60 -> 6,0 por accion (antes 80 -> 8,0)."""
    result = run_dcf(_inputs(minority_interest=5.0, preferred_stock=15.0))
    assert result.enterprise_value == pytest.approx(100.0)
    assert result.equity_value == pytest.approx(60.0)
    assert result.value_per_share == pytest.approx(6.0)
    assert result.trace["equity_bridge"] == {
        "enterprise_value": pytest.approx(100.0),
        "net_debt": 20.0,
        "minority_interest": 5.0,
        "preferred_stock": 15.0,
        "equity_value": pytest.approx(60.0),
    }


def test_equity_bridge_defaults_keep_previous_result():
    assert run_dcf(_inputs()).value_per_share == pytest.approx(8.0)


def test_reverse_dcf_uses_the_same_bridge():
    """Con g = 0 el valor por accion es 6,0 (ver arriba): un precio de 6,0
    exige crecimiento ~0 solo si el inverso resta los mismos derechos."""
    out = solve_required_growth(
        ReverseDCFInputs(
            market_price=6.0, revenue=100.0, fcf_margin=0.10, wacc=0.10,
            terminal_growth=0.0, net_debt=20.0, shares_outstanding=10.0, years=1,
            minority_interest=5.0, preferred_stock=15.0,
        )
    )
    assert out["required_revenue_growth"] == pytest.approx(0.0, abs=1e-6)
