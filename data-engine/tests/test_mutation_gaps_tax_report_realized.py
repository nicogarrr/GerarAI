"""Supervivientes de mutacion en ``TaxReportService.compute_report`` (ronda 3): agregados.

Sumas por empresa (dividendos, transmisiones, numero de ventas y de ventas
descubiertas), ventana abierta de la regla de los dos meses en su limite,
perdida bloqueada sin tipo de cambio, compra anulada (revision manual) y filas
de caja ambiguas. Fija el comportamiento ACTUAL; no cambia ninguna regla fiscal.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Portfolio, Transaction
from app.models.entities import Base
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Portfolio(name="P", base_currency="EUR", is_default=True))
        session.flush()
        yield session


def _company(db, ticker="AAA", currency="EUR"):
    row = Company(ticker=ticker, name=ticker, exchange="XETRA", currency=currency, sector="S",
                  industry="I", company_type="holding", valuation_model="unassigned",
                  special_sources=[], special_risks=[], factor_tags=[], domicile_country="DE")
    db.add(row)
    db.flush()
    return row


_seq = iter(range(1, 10_000))


def _tx(db, company, day, action, qty, price, currency="EUR", payload=None):
    db.add(Transaction(
        portfolio_id=db.query(Portfolio).one().id, company_id=company.id if company else None,
        trade_date=date.fromisoformat(day), action=action, quantity=Decimal(qty),
        price=Decimal(price), fees=Decimal("0"), currency=currency,
        external_id=f"ext-{next(_seq)}", raw_payload=payload or {},
    ))
    db.flush()


def _report(db, year=2026):
    return TaxReportService().compute_report(db, year, include_filing=False)


def _realized(report, ticker="AAA"):
    return next(b for b in report["realized"] if b["ticker"] == ticker)


def test_two_dividends_of_one_company_are_added_up(db):
    company = _company(db)
    _tx(db, company, "2026-03-15", "dividend", "1", "10")
    _tx(db, company, "2026-09-15", "dividend", "1", "15")
    [bucket] = _report(db)["dividends"]
    assert bucket["dividends_native"] == pytest.approx(25.0)
    assert bucket["dividends_base"] == pytest.approx(25.0)
    assert len(bucket["payments"]) == 2


def test_two_sales_of_one_company_add_proceeds_and_count(db):
    company = _company(db)
    _tx(db, company, "2026-01-05", "buy", "10", "10")
    _tx(db, company, "2026-04-01", "sell", "4", "12")
    _tx(db, company, "2026-06-01", "sell", "6", "15")
    bucket = _realized(_report(db))
    assert bucket["sale_count"] == 2
    assert bucket["proceeds_native"] == pytest.approx(48.0 + 90.0)
    assert bucket["cost_native"] == pytest.approx(100.0)
    assert bucket["gain_native"] == pytest.approx(38.0)
    assert [s["warning"] for s in bucket["sales"]] == [None, None]


def test_every_uncovered_sale_is_counted_and_warned(db):
    company = _company(db)
    _tx(db, company, "2026-01-05", "buy", "2", "10")
    _tx(db, company, "2026-04-01", "sell", "3", "12")
    _tx(db, company, "2026-06-01", "sell", "2", "12")
    bucket = _realized(_report(db))
    assert bucket["over_sell"] is True
    assert bucket["over_sell_count"] == 2
    assert all(s["warning"].startswith("over_sell: sold more shares") for s in bucket["sales"])
    assert all(s["cost_native"] is None for s in bucket["sales"])


def _loss_sale_then_last_data(db, last_day):
    company = _company(db)
    other = _company(db, "ZZZ")
    _tx(db, company, "2026-01-05", "buy", "10", "10")
    _tx(db, company, "2026-03-02", "sell", "10", "8")
    _tx(db, other, last_day, "buy", "1", "1")


def test_wash_sale_window_closes_exactly_two_months_after_the_sale(db):
    _loss_sale_then_last_data(db, "2026-05-02")
    bucket = _realized(_report(db))
    assert bucket["sales"][0]["wash_sale_window_open"] is False
    assert bucket["wash_sale_window_open"] is False


def test_wash_sale_window_is_open_the_day_before(db):
    _loss_sale_then_last_data(db, "2026-05-01")
    bucket = _realized(_report(db))
    assert bucket["sales"][0]["wash_sale_window_open"] is True
    assert bucket["wash_sale_window_open"] is True


def test_small_blocked_loss_without_fx_is_still_marked_blocked(db):
    company = _company(db, "USX", currency="USD")
    _tx(db, company, "2026-01-05", "buy", "1", "10", currency="USD")
    _tx(db, company, "2026-03-02", "sell", "1", "9.5", currency="USD")
    _tx(db, company, "2026-03-20", "buy", "1", "9.5", currency="USD")
    sale = _realized(_report(db), "USX")["sales"][0]
    assert sale["blocked_loss_native"] == pytest.approx(0.5)
    assert sale["blocked_loss_base"] is None
    assert sale["wash_sale_blocked"] is True


def test_sale_after_a_cancelled_buy_goes_to_manual_review(db):
    company = _company(db)
    _tx(db, company, "2026-01-05", "buy", "10", "10")
    _tx(db, company, "2026-02-01", "cancelled", "5", "10", payload={"buySell": "BUY"})
    _tx(db, company, "2026-04-01", "sell", "4", "12")
    report = _report(db)
    bucket = _realized(report)
    [sale] = bucket["sales"]
    assert bucket["cancelled_lot"] is True
    assert sale["cancelled_lot"] is True
    assert sale["manual_review"] is True
    assert sale["cost_native"] is None
    assert sale["warning"].startswith("cancelled_lot: the broker cancelled a purchase")
    assert report["summary"]["manual_review"] is True


def test_sale_before_a_cancelled_buy_is_not_flagged(db):
    company = _company(db)
    _tx(db, company, "2026-01-05", "buy", "10", "10")
    _tx(db, company, "2026-04-01", "sell", "4", "12")
    _tx(db, company, "2026-05-01", "cancelled", "5", "10", payload={"buySell": "BUY"})
    bucket = _realized(_report(db))
    assert bucket["cancelled_lot"] is False
    assert bucket["sales"][0]["manual_review"] is False


def test_cash_misc_with_company_is_a_misc_row(db):
    company = _company(db)
    _tx(db, company, "2026-03-15", "cash_misc", "1", "-4")
    report = _report(db)
    [row] = report["misc"]
    assert (row["type"], row["ticker"], row["amount_native"]) == ("cash_misc", "AAA", pytest.approx(-4.0))
    assert row["ambiguous"] is False


def test_ambiguous_misc_row_is_listed_with_its_raw_values(db):
    company = _company(db)
    _tx(db, company, "2026-03-15", "fee", "3", "2")
    report = _report(db)
    [row] = report["misc"]
    assert row["amount_native"] is None and row["manual_review"] is True
    [candidate] = report["summary"]["inconsistent_cash_rows"]
    assert candidate["action"] == "fee"
    assert candidate["quantity"] == pytest.approx(3.0)
    assert candidate["amount"] is not None
    assert candidate["currency"] == "EUR"
    assert candidate["date"] == "2026-03-15"


def test_dividends_on_the_first_and_last_day_of_the_year_count(db):
    company = _company(db)
    _tx(db, company, "2026-01-01", "dividend", "1", "10")
    _tx(db, company, "2026-12-31", "dividend", "1", "20")
    _tx(db, company, "2027-01-01", "dividend", "1", "40")
    _tx(db, company, "2025-12-31", "dividend", "1", "80")
    [bucket] = _report(db)["dividends"]
    assert [p["date"] for p in bucket["payments"]] == ["2026-01-01", "2026-12-31"]
    assert bucket["dividends_native"] == pytest.approx(30.0)
