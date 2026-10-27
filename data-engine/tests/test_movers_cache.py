"""Caché de /api/market/movers: TTL corto + invalidación al escribir cierres."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.market import market_movers
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


def _count_calls(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = market_change.compute_session_changes

    def counting(db, *args, **kwargs):
        calls.append(1)
        return real(db, *args, **kwargs)

    monkeypatch.setattr(market_change, "compute_session_changes", counting)
    return calls


def test_second_call_is_served_from_cache(db: Session, monkeypatch):
    aaa = _company(db, "AAA")
    _price(db, aaa, date(2026, 9, 21), "100")
    _price(db, aaa, date(2026, 9, 22), "110")
    calls = _count_calls(monkeypatch)

    first = market_movers(db, 10)
    second = market_movers(db, 5)

    assert len(calls) == 1
    assert first["gainers"][0]["change_pct"] == second["gainers"][0]["change_pct"]


def test_ttl_expiry_recomputes(db: Session, monkeypatch):
    calls = _count_calls(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(movers_cache.time, "monotonic", lambda: clock[0])

    market_movers(db, 10)
    clock[0] += movers_cache.TTL_SECONDS + 1
    market_movers(db, 10)

    assert len(calls) == 2


def test_closing_price_write_invalidates_after_commit(db: Session, monkeypatch):
    """El sync de cierres (upsert_prices + commit) no puede dejar Movers con el cierre viejo."""
    aaa = _company(db, "AAA")
    _price(db, aaa, date(2026, 9, 21), "100")
    _price(db, aaa, date(2026, 9, 22), "110")
    db.commit()
    before = market_movers(db, 10)
    assert before["gainers"][0]["change_pct"] == 10.0

    bar = PriceBar(day=date(2026, 9, 22), close=Decimal("120"), adj_close=Decimal("120"), volume=2_000_000)
    written = upsert_prices(db, aaa, [bar], now=datetime(2026, 10, 1, tzinfo=UTC))
    assert written == 1
    db.commit()

    after = market_movers(db, 10)
    assert after["gainers"][0]["change_pct"] == 20.0


def test_rollback_does_not_invalidate(db: Session, monkeypatch):
    calls = _count_calls(monkeypatch)
    market_movers(db, 10)
    movers_cache.mark_prices_written(db)
    db.rollback()
    market_movers(db, 10)
    assert len(calls) == 1


def test_remote_version_bump_invalidates_other_process(db: Session, monkeypatch):
    """El sync corre en el worker: una versión nueva en Redis obliga a recalcular aquí."""
    calls = _count_calls(monkeypatch)
    version = ["1"]
    monkeypatch.setattr(movers_cache, "_read_version", lambda: version[0])

    market_movers(db, 10)
    market_movers(db, 10)
    version[0] = "2"  # otro proceso escribió cierres
    market_movers(db, 10)

    assert len(calls) == 2


def test_invalidation_during_compute_is_not_cached(monkeypatch):
    results = iter(["viejo", "nuevo"])

    def compute():
        value = next(results)
        if value == "viejo":
            movers_cache.invalidate()  # llega una escritura mientras se calcula
        return value

    assert movers_cache.get_or_compute(compute) == "viejo"
    assert movers_cache.get_or_compute(compute) == "nuevo"


def test_redis_down_degrades_to_ttl_without_raising(monkeypatch):
    class _Broken:
        def get(self, key):
            raise ConnectionError("down")

        def incr(self, key):
            raise ConnectionError("down")

    monkeypatch.setitem(movers_cache._redis_state, "client", _Broken())
    monkeypatch.setitem(movers_cache._redis_state, "down_until", 0.0)
    assert movers_cache._read_version() is None
    assert movers_cache._redis() is None  # en backoff: no se reintenta en cada petición
    movers_cache.invalidate()  # no lanza
