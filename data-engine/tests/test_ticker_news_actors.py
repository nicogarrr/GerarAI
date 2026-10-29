"""Actores de noticias por ticker: orden prioritario, carriles, corte por tiempo."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.connectors.base import ConnectorResult
from app.workers import dramatiq_app


def _fn(name: str):
    actor = getattr(dramatiq_app, name)
    return getattr(actor, "fn", actor)


class _Db:
    def commit(self) -> None:
        # refresh_news cierra la transaccion de lectura antes del bucle de red.
        pass

    def close(self) -> None:
        pass


class _FakeService:
    def __init__(self) -> None:
        self.polled: list[tuple[str, str]] = []
        self.ingested: list[str] = []
        self.lanes: list[str | None] = []

    async def poll_rss(self, url, ticker=None, max_items=30):
        self.polled.append((ticker, url))
        return ConnectorResult(source="rss", items=[])

    async def poll_gdelt(self, query, ticker=None, max_records=25):
        self.polled.append((ticker, query))
        return ConnectorResult(source="gdelt", items=[])

    def ingest_news_result(self, db, result, ticker=None, news_lane=None):
        self.ingested.append(ticker)
        self.lanes.append(news_lane)
        return {"created": 0}


class _FakeStockTwits:
    """Carril social de #2975: nunca red real en tests."""

    def __init__(self, service: _FakeService) -> None:
        self.service = service

    async def poll(self, ticker, max_items=30):
        self.service.polled.append((ticker, "stocktwits"))
        return ConnectorResult(source="stocktwits", items=[])


def _co(cid, ticker, exchange="NASDAQ", name=None):
    return SimpleNamespace(id=cid, ticker=ticker, exchange=exchange, name=name or f"{ticker} Inc")


@pytest.fixture
def env(monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: _Db())
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda db: None)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    monkeypatch.setattr(dramatiq_app, "_run", lambda coro: _drive(coro))
    monkeypatch.setattr(dramatiq_app.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        "app.services.feed_ingestion_service.FeedIngestionService", lambda: service
    )
    monkeypatch.setattr(
        "app.services.connectors.StockTwitsConnector", lambda: _FakeStockTwits(service)
    )
    return service


def _drive(coro):
    import asyncio

    return asyncio.run(coro)


def test_refresh_ticker_news_tracked_prioritises_and_uses_lanes(env, monkeypatch):
    zzz, asts = _co(1, "ZZZ"), _co(2, "ASTS")
    monkeypatch.setattr(dramatiq_app, "_tracked_companies", lambda db: [zzz])
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [zzz, asts])
    out = _fn("refresh_ticker_news")(tenant_id=1, user_id="u", scope="tracked")
    assert out["status"] == "ok"
    assert out["truncated"] is False
    tickers = [t for t, _ in env.polled]
    assert tickers[0] == "ASTS"  # prioritaria primero
    urls = [u for t, u in env.polled if t == "ASTS"]
    assert len(urls) == 4  # yahoo + google en + google es + stocktwits
    assert len([u for t, u in env.polled if t == "ZZZ"]) == 3  # sin es
    assert out["feeds_processed"] == 7
    assert [t for t, u in env.polled if u == "stocktwits"] == ["ASTS", "ZZZ"]


def test_refresh_ticker_news_all_is_yahoo_us_only(env, monkeypatch):
    us, foreign = _co(1, "AAPL"), _co(2, "SAN", exchange="BME")
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [us, foreign])
    out = _fn("refresh_ticker_news")(tenant_id=1, user_id="u", scope="all")
    assert [t for t, _ in env.polled] == ["AAPL"]
    assert out["status"] == "ok"


def test_refresh_ticker_news_single_ticker_adds_google(env, monkeypatch):
    monkeypatch.setattr(
        dramatiq_app, "_companies", lambda db, ticker=None: [_co(1, "SPCX")]
    )
    out = _fn("refresh_ticker_news")(tenant_id=1, user_id="u", ticker="SPCX")
    assert len(env.polled) == 4  # yahoo + google en + google es + stocktwits
    assert out["feeds_processed"] == 4
    assert out["status"] == "ok"


def test_refresh_ticker_news_truncated_is_partial(env, monkeypatch):
    from app.services import ticker_news_lane

    class _Expired(ticker_news_lane.Deadline):
        def __init__(self, seconds, clock=None):
            super().__init__(seconds, clock=lambda: 10**9 if self.__dict__.get("_go") else 0)
            self._go = True

    monkeypatch.setattr(ticker_news_lane, "Deadline", _Expired)
    monkeypatch.setattr(
        dramatiq_app, "_companies", lambda db, ticker=None: [_co(1, "ASTS")]
    )
    out = _fn("refresh_ticker_news")(tenant_id=1, user_id="u", ticker="ASTS")
    assert out["truncated"] is True
    assert out["status"] != "ok"
    assert env.polled == []


def test_refresh_ticker_news_permanent_error_returns_failure(monkeypatch):
    def boom(t, u):
        raise ValueError("tenant inactivo")

    monkeypatch.setattr(dramatiq_app, "_session", boom)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    out = _fn("refresh_ticker_news")(tenant_id=1, user_id="u")
    assert out["status"] == "error"


def test_refresh_news_priority_first_and_ok(env, monkeypatch):
    zzz, asts = _co(1, "ZZZ"), _co(2, "ASTS")
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [zzz, asts])
    out = _fn("refresh_news")(tenant_id=1, user_id="u", scope="all")
    assert [t for t, _ in env.polled][0] == "ASTS"
    assert out["status"] == "ok"
    assert out["companies_processed"] == 2
    assert out["truncated"] is False


def test_refresh_news_tracked_scope_and_deadline(env, monkeypatch):
    from app.services import ticker_news_lane

    monkeypatch.setattr(
        dramatiq_app, "_tracked_companies", lambda db: [_co(1, "AAPL"), _co(2, "MSFT")]
    )
    ticks = iter(range(0, 10_000, 400))

    real = ticker_news_lane.Deadline
    monkeypatch.setattr(
        ticker_news_lane, "Deadline", lambda s: real(s, clock=lambda: next(ticks))
    )
    out = _fn("refresh_news")(tenant_id=1, user_id="u", scope="tracked")
    assert out["truncated"] is True
    assert out["status"] == "partial"


def test_refresh_news_collects_connector_errors(env, monkeypatch):
    async def bad(query, ticker=None, max_records=25):
        return ConnectorResult(source="gdelt", errors=["429"])

    env.poll_gdelt = bad
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [_co(1, "AAPL")])
    out = _fn("refresh_news")(tenant_id=1, user_id="u", ticker="AAPL")
    assert out["errors"] and out["errors"][0]["message"] == "429"
    assert out["status"] == "error"


def test_refresh_news_company_exception_rolls_back(env, monkeypatch):
    rolled = []
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda db: rolled.append(1))

    async def boom(query, ticker=None, max_records=25):
        raise RuntimeError("fallo")

    env.poll_gdelt = boom
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [_co(1, "AAPL")])
    out = _fn("refresh_news")(tenant_id=1, user_id="u", ticker="AAPL")
    assert rolled and out["errors"][0]["type"] == "RuntimeError"
