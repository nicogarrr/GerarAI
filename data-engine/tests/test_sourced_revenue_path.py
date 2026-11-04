from dataclasses import replace
from datetime import date

import pytest

from app.valuation.revenue_path import AnnualRevenue, sourced_revenue_path

BASE = AnnualRevenue(2025, 100, "USD", 1, "consolidated", date(2026, 1, 1),
                     "https://example.com/synthetic", "Synthetic annual revenue fixture")
FORECAST = replace(BASE, fiscal_year=2026, value=103)


def run(**kwargs):
    return sourced_revenue_path(BASE, [FORECAST], as_of=date(2026, 11, 4), **kwargs)


def test_growth_uses_forward_revenue_not_historical_or_eps():
    assert run()["growth_path"] == pytest.approx([.03])


def test_fade_is_explicit_and_reaches_terminal_without_five_year_plateau():
    result = run(terminal_growth=.02, fade_years=2, fade_source="Explicit synthetic scenario")
    assert result["growth_path"] == pytest.approx([.03, .025, .02])
    assert result["revenue_path"] == pytest.approx([103, 103*1.025, 103*1.025*1.02])


@pytest.mark.parametrize("change", [{"metric": "eps"}, {"period": "Q3"}, {"currency": "EUR"},
    {"scale": 1000000}, {"scope": "segment"}, {"fiscal_year": 2027},
    {"published": date(2027, 1, 1)}, {"source_url": ""}, {"citation": ""},
    {"value": float("nan")}, {"value": 0}])
def test_incompatible_forward_data_never_becomes_growth(change):
    result = sourced_revenue_path(BASE, [replace(FORECAST, **change)], as_of=date(2026, 11, 4))
    assert result["growth_path"] is None


def test_missing_forecast_or_partial_fade_is_not_filled():
    assert sourced_revenue_path(BASE, [], as_of=date(2026, 11, 4))["growth_path"] is None
    assert run(fade_years=3)["growth_path"] is None
