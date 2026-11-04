from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.valuation.cfo_fcff_bridge import CashFlowInput, cfo_to_fcff


def rows():
    base = CashFlowInput("cfo", Decimal(800), date(2025, 1, 1), date(2025, 12, 31),
                         "USD", 1, "consolidated", date(2026, 2, 1),
                         "https://example.com/synthetic", "Synthetic cash-flow fixture")
    return [base, replace(base, key="cash_capex", value=Decimal(500)),
            replace(base, key="cash_interest_deducted_in_cfo", value=Decimal(200)),
            replace(base, key="cash_interest_tax_shield", value=Decimal(50))]


def calc(r):
    return cfo_to_fcff(r, as_of=date(2026, 11, 4))


def test_cash_interest_is_added_back_after_explicit_shield():
    assert calc(rows())["fcff"] == 450


def test_financing_classified_interest_is_not_added_back_again():
    r = rows()
    r[2] = replace(r[2], value=Decimal(0))
    assert calc(r)["fcff"] == 250  # taxes in CFO still contain the interest shield


def test_no_net_income_interest_or_tax_defaults():
    r = rows()
    assert calc(r[:2])["fcff"] is None
    assert calc([*r[:2], replace(r[2], key="net_interest_expense"), r[3]])["fcff"] is None


def test_mixed_period_and_negative_shield_fail_closed():
    r = rows()
    for case in ([replace(r[0], end=date(2025, 6, 30)), *r[1:]],
                 [*r[:3], replace(r[3], value=Decimal(-1))],
                 [replace(r[0], value=Decimal("Infinity")), *r[1:]]):
        assert calc(case)["fcff"] is None
