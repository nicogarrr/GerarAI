from datetime import date
from decimal import Decimal

from app.valuation.public_inputs.wacc import MarketInput, calculate_wacc

DAY = date(2026, 11, 4)


def item(value, unit="decimal"):
    return MarketInput(Decimal(str(value)), unit, DAY, DAY, "https://example.org/source", "synthetic-test")


def inputs():
    return {"risk_free_rate": item(.04), "beta": item(1.5, "ratio"), "equity_risk_premium": item(.05),
            "market_equity": item(800, "USD"), "debt": item(200, "USD"),
            "cost_of_debt": item(.06), "tax_rate": item(.25)}


def test_wacc_independent_arithmetic():
    result = calculate_wacc(inputs(), as_of=DAY)
    assert result["cost_of_equity"] == Decimal(".115")
    assert result["wacc"] == Decimal(".101")  # .115*.8 + .06*.75*.2
    assert result["sources"]["beta"]["reference"] == "synthetic-test"


def test_explicit_debt_zero_allows_wacc_equal_equity_cost():
    rows = inputs()
    rows["debt"] = item(0, "USD")
    del rows["cost_of_debt"], rows["tax_rate"]
    assert calculate_wacc(rows, as_of=DAY)["wacc"] == Decimal(".115")


def test_absent_debt_or_erp_is_never_filled():
    for key in ("debt", "equity_risk_premium", "cost_of_debt"):
        rows = inputs()
        del rows[key]
        assert calculate_wacc(rows, as_of=DAY)["wacc"] is None


def test_future_invalid_and_percentage_units_fail_closed():
    rows = inputs()
    assert calculate_wacc(rows, as_of=date(2020, 1, 1))["wacc"] is None
    for bad in (item("NaN"), item(5, "%"), item(9, "ratio")):
        rows["beta"] = bad
        assert calculate_wacc(rows, as_of=DAY)["wacc"] is None
