"""Freno por proveedor aplicado al carril ticker-news (cola default).

Con el freno de Yahoo abierto, las lanes de Yahoo ni se intentan; con todos
los frenos del alcance abiertos, el actor skippea (tick nuevo) o se
reprograma (retry/eta) como en el disyuntor GDELT.
"""

from __future__ import annotations

from types import SimpleNamespace

import dramatiq
import pytest

from app.services.connectors.base import ConnectorResult
from app.services.provider_brake import PROVIDER_BRAKES
from app.workers import dramatiq_app


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    def eval(self, script, numkeys, *args):
        key, token = args
        if self.store.get(key) == token:
            self.store.pop(key)
            return 1
        return 0


class _Db:
    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeService:
    def __init__(self, yahoo_failures=0) -> None:
        self.polled: list[tuple[str, str]] = []
        self._yahoo_failures = yahoo_failures

    async def poll_rss(self, url, ticker=None, max_items=30):
        self.polled.append((ticker, url))
        if "yahoo" in url and self._yahoo_failures > 0:
            self._yahoo_failures -= 1
            return ConnectorResult.failed(
                "yahoo", Exception("Client error '429 Too Many Requests' for url 'https://finance.yahoo.com/rss'")
            )
        return ConnectorResult(source="rss", items=[])

    def ingest_news_result(self, db, result, ticker=None, news_lane=None, **kw):
        return {"created": 0}


def _co(cid, ticker, exchange="NASDAQ", name=None):
    return SimpleNamespace(id=cid, ticker=ticker, exchange=exchange, name=name or f"{ticker} Inc")


def _env(monkeypatch, service, client):
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: _Db())
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda db: None)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)
    monkeypatch.setattr(dramatiq_app, "_run", lambda coro: __import__("asyncio").run(coro))
    monkeypatch.setattr(dramatiq_app.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        "app.services.feed_ingestion_service.FeedIngestionService", lambda: service
    )


def test_429_streak_trips_brake_and_lanes_stop(monkeypatch):
    client = FakeRedis()
    # 4 companias US: las 3 primeras agotan la racha (umbral 3), la 4a no
    # debe ni intentar Yahoo.
    companies = [_co(i, t) for i, t in enumerate(("TAA", "TBB", "TCC", "TDD"), start=1)]
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: companies)
    service = _FakeService(yahoo_failures=10)
    _env(monkeypatch, service, client)
    out = dramatiq_app.refresh_ticker_news.fn(tenant_id=1, user_id="u", scope="all")
    yahoo_polls = [u for _, u in service.polled if "yahoo" in u]
    assert len(yahoo_polls) == PROVIDER_BRAKES["yahoo"].streak_limit
    assert client.get("provider_brake:yahoo:open") == "1"
    assert out["status"] in ("ok", "partial", "error")


def test_all_provider_brakes_open_skips_new_tick(monkeypatch):
    client = FakeRedis()
    client.set("provider_brake:yahoo:open", "1", ex=1800)
    client.set("provider_brake:google-news:open", "1", ex=1800)
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [_co(1, "AAPL")])
    service = _FakeService()
    _env(monkeypatch, service, client)
    out = dramatiq_app.refresh_ticker_news.fn(tenant_id=1, user_id="u", scope="tracked")
    assert out["status"] == "skipped"
    assert out["reason"] == "provider_brakes_open"
    assert service.polled == []


def test_scope_all_only_cares_about_yahoo(monkeypatch):
    client = FakeRedis()
    client.set("provider_brake:yahoo:open", "1", ex=1800)
    # google-news abierto no basta para scope=all, pero yahoo si.
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [_co(1, "AAPL")])
    service = _FakeService()
    _env(monkeypatch, service, client)
    out = dramatiq_app.refresh_ticker_news.fn(tenant_id=1, user_id="u", scope="all")
    assert out["status"] == "skipped"
    assert out["reason"] == "provider_brakes_open"


def test_retry_message_is_rescheduled_not_acked(monkeypatch):
    import time as _time

    client = FakeRedis()
    client.set("provider_brake:yahoo:open", "1", ex=1800)
    client.set("provider_brake:google-news:open", "1", ex=1800)
    service = _FakeService()
    _env(monkeypatch, service, client)
    retry_msg = SimpleNamespace(options={"retries": 1}, message_timestamp=_time.time() * 1000)
    monkeypatch.setattr(
        dramatiq_app.CurrentMessage,
        "get_current_message",
        classmethod(lambda cls: retry_msg),
    )
    with pytest.raises(dramatiq.Retry) as caught:
        dramatiq_app.refresh_ticker_news.fn(tenant_id=1, user_id="u", scope="tracked")
    assert caught.value.delay == PROVIDER_BRAKES["yahoo"].cooldown_s * 1000
