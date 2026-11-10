"""Caché de /api/market/changes (tickers concretos): TTL + invalidación al
escribir cierres, una entrada por conjunto de tickers.

Prod 2026-11-09: la watchlist lo pedía en cada carga y el cálculo llegaba a
8-9 s con la BD lenta; el frontend corta a 8 s y se quedaba sin cierre
datado de respaldo en TODAS las filas."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.market import market_changes
from app.core.database import Base
from app.models.entities import Company, MarketPrice
from app.services import market_change, movers_cache
from app.services.propicks_price_service import PriceBar, upsert_prices


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture(autouse=True)
def _clean_cache():
    movers_cache.clear_local()
    yield
    movers_cache.clear_local()


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        company_type="operating", valuation_model="dcf",
    )
    db.add(company)
    db.flush()
    return company


def _price(db: Session, company: Company, day: date, close: str) -> None:
    db.add(MarketPrice(
        company_id=company.id, date=day, open=Decimal(close), high=Decimal(close),
        low=Decimal(close), close=Decimal(close), adj_close=Decimal(close),
        volume=2_000_000, source="yfinance", quote_currency="USD",
    ))
    db.flush()


def _seed_two_sessions(db: Session, ticker: str) -> Company:
    company = _company(db, ticker)
    _price(db, company, date(2026, 11, 5), "100")
    _price(db, company, date(2026, 11, 6), "110")
    db.commit()
    return company


def _count_calls(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = market_change.compute_session_changes

    def spy(session, tickers=None):
        calls.append(0)
        return real(session, tickers=tickers)

    monkeypatch.setattr(market_change, "compute_session_changes", spy)
    monkeypatch.setattr("app.api.routes.market.market_change.compute_session_changes", spy)
    return calls


def test_second_call_same_tickers_does_not_recompute(db, monkeypatch):
    _seed_two_sessions(db, "AAA")
    calls = _count_calls(monkeypatch)
    first = market_changes(tickers="AAA", db=db)
    second = market_changes(tickers="AAA", db=db)
    assert first == second
    assert len(calls) == 1


def test_distinct_ticker_sets_compute_apart(db, monkeypatch):
    _seed_two_sessions(db, "AAA")
    _seed_two_sessions(db, "BBB")
    calls = _count_calls(monkeypatch)
    market_changes(tickers="AAA", db=db)
    market_changes(tickers="BBB", db=db)
    market_changes(tickers="AAA,BBB", db=db)
    assert len(calls) == 3


def test_price_write_invalidates(db, monkeypatch):
    company = _seed_two_sessions(db, "AAA")
    calls = _count_calls(monkeypatch)
    before = market_changes(tickers="AAA", db=db)
    written = upsert_prices(db, company, [PriceBar(
        day=date(2026, 11, 6), close=Decimal("121"), adj_close=Decimal("121"),
        volume=2_500_000,
    )], now=datetime(2026, 11, 9, 18, 0, tzinfo=UTC))
    assert written == 1
    db.commit()
    after = market_changes(tickers="AAA", db=db)
    assert len(calls) == 2
    item = after["items"]["AAA"]
    assert item["price"] == 121.0
    assert item["change_pct"] == 21.0
    assert before["items"]["AAA"]["price"] == 110.0


def test_keyed_cache_bounded(db, monkeypatch):
    _seed_two_sessions(db, "AAA")
    market_changes(tickers="AAA", db=db)
    with movers_cache._lock:
        movers_cache._entry_by_key.update({f"k{i}": {"at": 0, "version": None, "value": None} for i in range(movers_cache._KEYED_MAX)})
    # Alcanzado el tope, la siguiente clave nueva vacía y recalcula sin crecer.
    market_changes(tickers="BBB", db=db)
    with movers_cache._lock:
        assert len(movers_cache._entry_by_key) <= movers_cache._KEYED_MAX
