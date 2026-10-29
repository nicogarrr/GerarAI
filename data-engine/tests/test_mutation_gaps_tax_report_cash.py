"""Supervivientes de mutacion en ``TaxReportService.compute_report`` (ronda 3).

Primera pasada de caja: dividendos, retenciones, pagos especiales y caja sin
emisor resoluble. Fija el comportamiento ACTUAL; no cambia ninguna regla fiscal.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FXRate, Portfolio, Transaction
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


def _fx(db, rate="0.9", when=date(2026, 3, 13), quote="USD"):
    db.add(FXRate(base_currency="EUR", quote_currency=quote, rate=Decimal(rate),
                  rate_date=when, source="test"))
    db.flush()


def _company(db, ticker="AAA"):
    row = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD", sector="S",
                  industry="I", company_type="holding", valuation_model="unassigned",
                  special_sources=[], special_risks=[], factor_tags=[], domicile_country="US")
    db.add(row)
    db.flush()
    return row


_seq = iter(range(1, 10_000))


def _cash(db, *, action, amount, company=None, when=date(2026, 3, 15), symbol="AAPL",
          currency="USD", payload=None):
    row = Transaction(
        portfolio_id=db.query(Portfolio).one().id,
        company_id=company.id if company else None,
        trade_date=when, action=action, quantity=Decimal("1"),
        price=Decimal(str(amount)), fees=Decimal("0"), currency=currency,
        external_id=f"ext-{next(_seq)}",
        raw_payload=payload if payload is not None else ({"symbol": symbol} if symbol else {}),
    )
    db.add(row)
    db.flush()
    return row


def _report(db, year=2026):
    return TaxReportService().compute_report(db, year, include_filing=False)


@pytest.mark.parametrize("action", ["fee", "cash_misc", "interest"])
def test_unattributed_misc_cash_is_kept_in_misc_rows(db, action):
    _fx(db)
    _cash(db, action=action, amount="10.00", symbol="XYZ")
    report = _report(db)
    rows = [r for r in report["misc"] if r["type"] == action]
    assert len(rows) == 1
    assert rows[0]["ticker"] == "UNATTRIBUTED:XYZ"
    assert rows[0]["amount_native"] == pytest.approx(10.0)
    assert rows[0]["amount_base"] == pytest.approx(9.0)
    assert rows[0]["currency"] == "USD"


def test_unattributed_unknown_action_is_skipped(db):
    _fx(db)
    _cash(db, action="transfer", amount="10.00", symbol="XYZ")
    report = _report(db)
    assert report["misc"] == []
    assert report["dividends"] == []


@pytest.mark.parametrize("action", ["withholding", "withholding_tax"])
def test_unattributed_withholding_is_income_flagged_unattributed(db, action):
    _fx(db)
    _cash(db, action=action, amount="-15.00", symbol="MSFT")
    report = _report(db)
    [bucket] = report["dividends"]
    assert bucket["ticker"] == "UNATTRIBUTED:MSFT"
    assert bucket["unattributed"] is True
    assert report["summary"]["unattributed_tickers"] == ["UNATTRIBUTED:MSFT"]


def test_withholding_row_carries_eur_amount_and_date(db):
    _fx(db)
    company = _company(db)
    _cash(db, action="withholding_tax", amount="-15.00", company=company)
    report = _report(db)
    [bucket] = report["dividends"]
    assert bucket["unattributed"] is False
    [row] = bucket["payments"]
    assert row["type"] == "withholding"
    assert row["date"] == "2026-03-15"
    assert row["amount_native"] == pytest.approx(15.0)
    assert row["amount_base"] == pytest.approx(13.5)
    assert bucket["missing_fx"] is False
    assert report["summary"]["missing_fx"] == []


def test_withholding_without_fx_has_no_eur_amount_and_flags_missing_fx(db):
    company = _company(db)
    _cash(db, action="withholding", amount="-15.00", company=company)
    report = _report(db)
    [bucket] = report["dividends"]
    [row] = bucket["payments"]
    assert row["amount_native"] == pytest.approx(15.0)
    assert row["amount_base"] is None
    assert bucket["missing_fx"] is True
    assert report["summary"]["missing_fx"] == ["AAA"]


@pytest.mark.parametrize("action", ["div", "cash_dividend", "Dividend"])
def test_dividend_action_aliases_are_ordinary_dividends(db, action):
    _fx(db)
    company = _company(db)
    _cash(db, action=action, amount="100.00", company=company)
    report = _report(db)
    [bucket] = report["dividends"]
    [row] = bucket["payments"]
    assert row["type"] == "dividend"
    assert row["date"] == "2026-03-15"
    assert row["amount_base"] == pytest.approx(90.0)
    assert report["summary"]["total_dividends_base"] == pytest.approx(90.0)


def test_dividend_without_fx_flags_missing_fx(db):
    company = _company(db)
    _cash(db, action="dividend", amount="100.00", company=company)
    report = _report(db)
    [bucket] = report["dividends"]
    assert bucket["missing_fx"] is True
    assert report["summary"]["missing_fx"] == ["AAA"]


def test_prior_year_dividend_is_not_in_this_years_report(db):
    _fx(db, when=date(2025, 12, 30))
    _fx(db)
    company = _company(db)
    _cash(db, action="dividend", amount="50.00", company=company, when=date(2025, 12, 31))
    _cash(db, action="dividend", amount="100.00", company=company)
    report = _report(db)
    [bucket] = report["dividends"]
    assert [p["date"] for p in bucket["payments"]] == ["2026-03-15"]
    assert report["summary"]["total_dividends_base"] == pytest.approx(90.0)


def test_ambiguous_dividend_candidate_keeps_its_currency(db):
    _fx(db)
    company = _company(db)
    row = _cash(db, action="dividend", amount="2.00", company=company)
    row.quantity = Decimal("50")  # cantidad no canonica: fila ambigua
    db.flush()
    report = _report(db)
    [candidate] = report["summary"]["inconsistent_cash_rows"]
    assert candidate["currency"] == "USD"
    assert candidate["candidate"] is True
    assert candidate["date"] == "2026-03-15"
