"""Unknown values/dates never become usable balance amounts."""

from decimal import Decimal

import pytest

from app.valuation import balance_bridge as bb

DATE = "2026-06-30:Q2"


def cite(value=1e6, period=DATE, source="SEC"):
    return {"value": value, "period": period, "source_type": source}


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        None,
        "NaN",
        "Infinity",
        Decimal("NaN"),
        Decimal("Infinity"),
        "bad",
        10**400,
    ],
)
def test_invalid_debt_and_sti_values_rejected(value):
    point = {"cash_and_equivalents": cite(), "total_debt": cite(value), "short_term_investments": cite(value)}
    assert bb.financial_debt(point, ifrs=False) == (None, None, False, [])
    assert bb.short_term_investments(point) == (0.0, None, None)


@pytest.mark.parametrize("period", [None, "", "FY2026", "2026-02-30:FY", "20260630", "2026-6-30", "garbage"])
@pytest.mark.parametrize("missing", ["cash", "debt", "both"])
def test_unknown_close_is_not_same_or_usable(period, missing):
    cash = cite(period=period if missing in ("cash", "both") else DATE)
    debt = cite(period=period if missing in ("debt", "both") else DATE)
    point = {"cash_and_equivalents": cash, "total_debt": debt, "short_term_investments": dict(debt)}
    assert bb.same_close(point, "total_debt") is False
    value, used, inside, warnings = bb.financial_debt(point, ifrs=False)
    assert value is None and used is None and inside is False and warnings
    value, used, warning = bb.short_term_investments(point)
    assert value == 0 and used is None and warning


def test_absent_period_keys_and_absent_cash_do_not_match():
    for point in [
        {"total_debt": {"value": 1e6}, "cash_and_equivalents": {"value": 1e6}},
        {"total_debt": cite()},
    ]:
        assert bb.same_close(point, "total_debt") is False
        assert bb.financial_debt(point, ifrs=False)[0] is None


@pytest.mark.parametrize(
    "lease",
    [
        cite(value=float("nan")),
        cite(value=float("inf")),
        cite(value=None),
        cite(period=None),
        cite(period="2026-02-30"),
    ],
)
def test_invalid_lease_cannot_reduce_debt(lease):
    point = {
        "cash_and_equivalents": cite(),
        "total_debt": cite(5e6, source="YAHOO_FUNDAMENTALS"),
        "operating_lease_liabilities": lease,
    }
    value, used, inside, warnings = bb.financial_debt(point, ifrs=False, lease_at=lambda period: lease)
    assert value == 5 and used["source_type"] == "YAHOO_FUNDAMENTALS"
    assert inside is False and warnings


def test_known_different_close_remains_usable_with_warning_and_zero_is_valid():
    point = {"cash_and_equivalents": cite(), "total_debt": cite(0, "2025-12-31:FY")}
    value, used, inside, warnings = bb.financial_debt(point, ifrs=False)
    assert value == 0 and used == point["total_debt"] and not inside
    assert any("2025-12-31" in w and "2026-06-30" in w for w in warnings)
    point["total_debt"] = cite(0)
    assert bb.same_close(point, "total_debt") is True
    assert bb.financial_debt(point, ifrs=False) == (0.0, point["total_debt"], False, [])
