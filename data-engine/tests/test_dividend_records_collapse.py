"""Reajuste de split de Yahoo: una fila por (ex_date, divisa), sin doble conteo."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.entities import DividendRecord
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.dividend_records import collapse_yahoo_readjusted
from tests.test_dividend_ingestion import FakeFMP, FakeYahoo, _company, _position, db  # noqa: F401


def _row(db, company, ex, amount, source, fetched, currency="USD"):
    r = DividendRecord(
        company_id=company.id, ex_date=ex, amount=Decimal(amount), currency=currency,
        source=source, fetched_at=fetched,
    )
    db.add(r)
    db.commit()
    return r


def test_yield_does_not_double_count_split_readjusted_yahoo_rows(db):
    company = _company(db)
    _position(db, company, price=100.0)
    ex = date.today() - timedelta(days=60)
    _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1))     # pre-split
    _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1))  # reajustada
    pos = DividendIngestionService(fmp=FakeFMP(), yahoo=FakeYahoo()).portfolio_yields(db)["positions"][0]
    assert pos["ttm_dividend_per_share"] == 0.1925  # la mas reciente, no 0.9625
    assert len(db.scalars(select(DividendRecord)).all()) == 2  # nada borrado


def test_other_sources_and_special_dividends_are_untouched(db):
    company = _company(db)
    ex = date.today() - timedelta(days=30)
    ordinary = _row(db, company, ex, "0.50", "fmp", datetime(2026, 9, 1))
    special = _row(db, company, ex, "2.00", "fmp", datetime(2026, 9, 1))
    out = collapse_yahoo_readjusted([ordinary, special])
    assert sorted(r.amount for r in out) == [Decimal("0.50"), Decimal("2.00")]


def test_different_currencies_and_dates_are_kept(db):
    company = _company(db)
    ex = date.today() - timedelta(days=30)
    rows = [
        _row(db, company, ex, "1", "yahoo_finance", datetime(2026, 9, 1), "USD"),
        _row(db, company, ex, "1", "yahoo_finance", datetime(2026, 9, 1), "CHF"),
        _row(db, company, ex - timedelta(days=90), "1", "yahoo_finance", datetime(2026, 9, 1)),
    ]
    assert len(collapse_yahoo_readjusted(rows)) == 3
