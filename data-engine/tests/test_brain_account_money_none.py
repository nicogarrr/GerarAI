"""Missing account amounts stay unknown, while an explicit zero stays zero."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import brain_account_tools as tools


@pytest.mark.parametrize("english,unknown,zero", [(False, "N/D", "0,00 €"), (True, "N/A", "0.00 €")])
def test_money_none_is_not_zero(english, unknown, zero):
    assert tools._money(None, "EUR", english=english) == unknown
    assert tools._money(0, "EUR", english=english) == zero


@pytest.mark.parametrize("english,unknown", [(False, "N/D"), (True, "N/A")])
def test_daily_missing_total_does_not_claim_change(monkeypatch, english, unknown):
    monkeypatch.setattr(tools, "_english", lambda: english)
    monkeypatch.setattr(tools, "local_today", lambda: date(2026, 11, 1))
    latest = SimpleNamespace(id=1, portfolio_id=1, base_currency="EUR", total_value_base=None,
                             snapshot_date=date(2026, 11, 1), daily_return=Decimal("0.1"))
    previous = SimpleNamespace(total_value_base=Decimal("100"))
    db = Mock()
    db.scalar.side_effect = [latest, previous]
    answer = tools._daily_change_answer(db, 1).answer
    assert unknown in answer
    assert "0,00 €" not in answer and "0.00 €" not in answer
    assert "10,0 %" not in answer and "10.0%" not in answer


@pytest.mark.parametrize("english,unknown", [(False, "N/D"), (True, "N/A")])
@pytest.mark.parametrize("withheld", [None, 0])
def test_year_withholding_unknown_vs_explicit_zero(monkeypatch, english, unknown, withheld):
    monkeypatch.setattr(tools, "_english", lambda: english)
    monkeypatch.setattr(tools, "local_today", lambda: date(2026, 11, 1))
    monkeypatch.setattr(tools, "_tax_data", lambda *_: {"summary": {
        "total_dividends_base": 100, "total_withholding_base": withheld,
    }})
    monkeypatch.setattr(tools, "_unrealized", lambda *_: None)
    answer = tools._year_gains_answer(Mock(), 1, 2026).answer
    if withheld is None:
        assert unknown in answer
        assert "0,00 € de retención" not in answer and "0.00 € withheld" not in answer
    else:
        assert unknown not in answer
        assert ("0.00 € withheld" if english else "0,00 € de retención") in answer


@pytest.mark.parametrize("english,unknown", [(False, "N/D"), (True, "N/A")])
def test_cash_missing_amount_poison_currency_total(monkeypatch, english, unknown):
    monkeypatch.setattr(tools, "_english", lambda: english)
    db = Mock()
    db.scalars.return_value = [
        SimpleNamespace(id=1, currency="EUR", balance=Decimal("100"), as_of=date(2026, 11, 1)),
        SimpleNamespace(id=2, currency="EUR", balance=None, as_of=date(2026, 11, 1)),
        SimpleNamespace(id=3, currency="USD", balance=Decimal("0"), as_of=date(2026, 11, 1)),
    ]
    answer = tools._cash_answer(db, 1).answer
    assert unknown in answer
    assert "100" not in answer
    assert ("0.00 USD" if english else "0,00 USD") in answer


@pytest.mark.parametrize("english,unknown", [(False, "N/D"), (True, "N/A")])
@pytest.mark.parametrize("missing", ["withholding_native", "dividends_native"])
def test_missing_dividend_component_poison_totals_and_omit_rate(monkeypatch, english, unknown, missing):
    monkeypatch.setattr(tools, "_english", lambda: english)
    rows = [
        {"ticker": "A", "currency": "USD", "withholding_native": 10, "dividends_native": 100},
        {"ticker": "B", "currency": "USD", "withholding_native": 5, "dividends_native": 50, missing: None},
    ]
    monkeypatch.setattr(tools, "_tax_data", lambda *_: {"dividends": rows})
    answer = tools._withholding_answer(Mock(), 1, 2026, set()).answer
    head = answer.splitlines()[0]
    assert unknown in head
    assert "%" not in head
    if missing == "withholding_native":
        assert ("150.00 USD" if english else "150,00 USD") in head
    else:
        assert ("15.00 USD" if english else "15,00 USD") in head
