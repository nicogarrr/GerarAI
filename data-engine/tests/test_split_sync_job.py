"""Job programado de splits (P1 splits AAPL): tracked = cartera+watchlist,
universo en chunks auto-encolados. Sin splits en BD el modelo degrada el
CAGR de acciones a N/D; este job es quien los puebla (Yahoo, FMP respaldo).
"""

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Company, Position, WatchItem
from app.workers import dramatiq_app as workers


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[Company.__table__, Position.__table__, WatchItem.__table__],
    )
    return sessionmaker(bind=engine)()


def _company(db, ticker):
    company = Company(
        ticker=ticker, name=ticker, exchange="TEST", currency="USD",
        sector="S", industry="I", company_type="standard",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_tracked_tickers_union_positions_and_watchlist():
    db = _db()
    held = _company(db, "AAPL")
    _company(db, "MSFT")
    db.add(Position(company_id=held.id, tenant_id=1))
    db.add(WatchItem(symbol="nvda", tenant_id=1))
    db.commit()

    tickers, next_cursor = workers.split_sync_tickers(db, "tracked")
    assert tickers == ["AAPL", "NVDA"]
    assert next_cursor is None


def test_universe_chunking():
    db = _db()
    for ticker in ["AAA", "BBB", "CCC"]:
        _company(db, ticker)

    first, cursor = workers.split_sync_tickers(db, "universe", cursor=0, chunk=2)
    assert first == ["AAA", "BBB"] and cursor == 2
    second, cursor = workers.split_sync_tickers(db, "universe", cursor=cursor, chunk=2)
    assert second == ["CCC"] and cursor is None


def test_actor_aggregates_and_enqueues_next_universe_chunk():
    db = _db()
    for ticker in ["AAA", "BBB", "CCC"]:
        _company(db, ticker)

    class _FakeService:
        async def sync_company(self, db, *, ticker):
            return {"ticker": ticker, "status": "ok", "inserted": 1, "existing": 0}

    with (
        patch.object(workers, "_session", return_value=db),
        patch.object(workers, "SPLIT_SYNC_UNIVERSE_CHUNK", 2),
        patch.object(workers.ingest_corporate_splits, "send") as send,
        patch("app.services.split_ingestion_service.SplitIngestionService", _FakeService),
    ):
        result = workers.ingest_corporate_splits(
            tenant_id=1, user_id="u", scope="universe", cursor=0)

    assert result["status"] == "ok"
    assert result["companies"] == 2 and result["synced"] == 2
    assert result["inserted"] == 2 and result["next_cursor"] == 2
    send.assert_called_once_with(1, "u", scope="universe", cursor=2)
