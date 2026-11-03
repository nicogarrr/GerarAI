"""Movers/Mercado/watchlist: el último cierre oficial y el anterior de cada
compañía se buscan por índice (MAX correlacionado por compañía), no agrupando
todos los cierres oficiales del universo. Mismo resultado."""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, MarketPrice
from app.services import market_change

DAY = date(2026, 10, 30)  # viernes


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Test", industry="Test", company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _close(db: Session, company: Company, day: date, close: str, source: str = "yfinance") -> None:
    db.add(MarketPrice(company_id=company.id, date=day, open=Decimal(close), high=Decimal(close),
                       low=Decimal(close), close=Decimal(close), adj_close=Decimal(close),
                       volume=1000, source=source))


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@contextmanager
def _capture(db: Session):
    statements: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        yield statements
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)


def _seed(db: Session) -> None:
    weekdays = [DAY - timedelta(days=d) for d in range(0, 30) if (DAY - timedelta(days=d)).weekday() < 5]
    full = _company(db, "FULL")
    for i, day in enumerate(reversed(weekdays)):
        _close(db, full, day, str(100 + i))
    # Último registro intradía de otra fuente: el oficial más reciente manda.
    spot = _company(db, "SPOT")
    for i, day in enumerate(reversed(weekdays[1:])):
        _close(db, spot, day, str(50 + i))
    _close(db, spot, DAY, "999", source="finnhub")
    # Un solo cierre oficial: sin anterior.
    single = _company(db, "SINGLE")
    _close(db, single, DAY, "10")
    # Sin cierres oficiales: fuera del universo.
    other = _company(db, "OTHER")
    _close(db, other, DAY, "5", source="finnhub")
    db.commit()


def test_latest_and_previous_close_per_company(db):
    _seed(db)
    movers, stale, session_day = market_change.compute_session_changes(db)
    by_ticker = {row["ticker"]: row for row in movers}

    assert set(by_ticker) == {"FULL", "SPOT", "SINGLE"}
    assert session_day == DAY
    assert by_ticker["FULL"]["date"] == DAY.isoformat()
    assert by_ticker["FULL"]["previous_date"] == (DAY - timedelta(days=1)).isoformat()
    assert by_ticker["FULL"]["change_pct"] is not None
    # SPOT: su último cierre OFICIAL es del jueves (el finnhub del viernes no cuenta).
    assert by_ticker["SPOT"]["date"] == (DAY - timedelta(days=1)).isoformat()
    assert by_ticker["SPOT"]["price"] != 999
    assert by_ticker["SINGLE"]["previous_date"] is None
    assert by_ticker["SINGLE"]["change_pct"] is None
    assert stale == 1

    subset, _, _ = market_change.compute_session_changes(db, tickers=["full", "OTHER", "NOPE"])
    assert [row["ticker"] for row in subset] == ["FULL"]
    assert subset[0] == by_ticker["FULL"]


def test_latest_dates_come_from_index_lookups_not_universe_group_by(db):
    _seed(db)
    with _capture(db) as statements:
        market_change.compute_session_changes(db)
    movers_sql = " ".join(s for s in statements if "movers_latest" in s).lower()
    assert movers_sql
    assert "group by market_prices.company_id" not in movers_sql
    assert "max(market_prices_1.date)" in movers_sql
