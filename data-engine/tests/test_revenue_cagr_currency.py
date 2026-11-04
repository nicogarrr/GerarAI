"""El CAGR no compara ingresos denominados en monedas diferentes."""
from types import SimpleNamespace

from app.valuation.normalized_fcf import revenue_cagr


def test_cagr_refuses_mixed_reporting_currencies():
    history = {
        2022: {"revenue": SimpleNamespace(value=100, unit="EUR", id=1)},
        2025: {"revenue": SimpleNamespace(value=200, unit="USD", id=2)},
    }
    assert revenue_cagr(history) is None


def test_cagr_same_currency_preserves_growth():
    history = {
        2022: {"revenue": SimpleNamespace(value=100, unit="USD", id=1)},
        2025: {"revenue": SimpleNamespace(value=133.1, unit="USD", id=2)},
    }
    assert abs(revenue_cagr(history)["value"] - .1) < 1e-12
