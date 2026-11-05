from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.valuation.depreciation_components import ExpenseComponent, depreciation_components


def rows():
    base = ExpenseComponent("ppe_depreciation", Decimal("216.1"), date(2025, 1, 1), date(2025, 12, 31), "EUR",
                            1000000, "consolidated", date(2026, 3, 11),
                            "https://example.com/synthetic", "Synthetic disjoint component fixture")
    return [base, replace(base, kind="rou_depreciation", value=Decimal("256.4")),
            replace(base, kind="intangible_amortization", value=Decimal("13.7"))]


def calc(items):
    return depreciation_components(items, as_of=date(2026, 11, 4))


def test_lease_depreciation_never_becomes_maintenance_capex():
    result = calc(rows())
    assert result["da_ex_rou"] == Decimal("229800000")
    assert result["da_including_rou"] == Decimal("486200000")
    assert result["total_noncash"] is None  # absence is not zero impairment


def test_explicit_impairment_stays_separate():
    r = rows()
    r.append(replace(r[0], kind="impairment", value=Decimal("8")))
    result = calc(r)
    assert result["da_ex_rou"] == Decimal("229800000")
    assert result["total_noncash"] == Decimal("494200000")


def test_partial_duplicate_aggregate_and_mixed_periods_are_not_added():
    r = rows()
    for case in (r[:1], r+[r[0]], r+[replace(r[0], kind="total")],
                 [replace(r[0], period_end=date(2024, 12, 31)), *r[1:]],
                 [replace(r[0], value=Decimal("NaN")), *r[1:]]):
        assert calc(case)["da_ex_rou"] is None
