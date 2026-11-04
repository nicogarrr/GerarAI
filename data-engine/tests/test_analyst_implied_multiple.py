from datetime import date
from decimal import Decimal

from app.valuation.analyst_implied_multiple import implied_forward_multiple


def args():
    return dict(target_price=100, shares=10, forward_fcf=100, net_debt_at_target=200,
                currency="USD", fcf_currency="USD", basis="enterprise", fcf_kind="fcff", target_date=date(2026, 1, 1),
                forward_date=date(2026, 1, 1), discount_rate=".1",
                evidence=dict.fromkeys(("target_price", "shares", "forward_fcf", "net_debt_at_target", "discount_rate"), "synthetic"))


def test_same_date_ev_multiple_adds_debt_to_pt_equity():
    assert implied_forward_multiple(**args())["multiple"] == 12


def test_forward_date_unwinds_discount_from_target_not_today():
    a = args()
    a["forward_date"] = date(2030, 1, 1)  # 1461 days = four ACT/365.25 years
    assert implied_forward_multiple(**a)["multiple"] == Decimal(12)*Decimal("1.1")**4


def test_equity_basis_does_not_add_debt():
    a = args()
    a.update(basis="equity", fcf_kind="fcfe", net_debt_at_target=None)
    assert implied_forward_multiple(**a)["multiple"] == 10


def test_missing_or_incompatible_values_never_create_multiple():
    for changes in ({"net_debt_at_target": None}, {"fcf_currency": "EUR"}, {"forward_fcf": 0},
                    {"target_price": "NaN"}, {"forward_date": date(2025, 1, 1)}, {"evidence": {}}, {"fcf_kind": "fcfe"}, {"currency": "GBp", "fcf_currency": "GBp"}):
        a = args()
        a.update(changes)
        assert implied_forward_multiple(**a)["multiple"] is None
