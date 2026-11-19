"""Split universo US: una descarga global de Yahoo (freno con recheck por
unidad, cache de crudos, copias encoladas por tenant) y persistencia por
tenant (hit de cache, miss en vivo, freno sin cache no reintenta)."""

import dataclasses
import time
from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.feed_ingestion_service as fis
import app.services.provider_brake as brake
import app.services.ticker_news_lane as lane_mod
from app.models import Company
from app.models.entities import Base
from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.workers import dramatiq_app as worker


class FakeRedis:
    def __init__(self):
        self.store = {}

    def exists(self, key):
        return int(key in self.store)

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    def expire(self, key, ttl):
        return True

    def eval(self, *a, **k):
        return 1

    def close(self):
        pass


def _label(result, company, evidence):
    return dataclasses.replace(result, metadata={**result.metadata, "news_lane": "yahoo"})


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    redis = FakeRedis()
    monkeypatch.setattr(worker, "_redis_client", lambda: redis)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    open_brakes = set()
    calls_429, calls_ok = [], []
    monkeypatch.setattr(brake, "is_open", lambda client, p: p in open_brakes)
    monkeypatch.setattr(brake, "record_429", lambda client, p: calls_429.append(p))
    monkeypatch.setattr(brake, "record_success", lambda client, p: calls_ok.append(p))
    monkeypatch.setattr(lane_mod, "label_yahoo", _label)
    polls = []
    outcomes = {}

    class FakeService:
        async def poll_rss(self, url, *, ticker, max_items):
            polls.append(ticker)
            outcome = outcomes.get(ticker)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
            return ConnectorResult(
                source="rss",
                items=[ConnectorItem(source="rss", title=f"t-{ticker}", url=f"https://x/{ticker}")])

        def ingest_news_result(self, db_, part, *, ticker, news_lane=None):
            return {"created": len(part.items)}

    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    monkeypatch.setattr(worker, "coalesced_send",
                        lambda actor, t, u: SimpleNamespace(message_id=f"m-{t}"))
    return SimpleNamespace(db=db, redis=redis, polls=polls, outcomes=outcomes,
                           open_brakes=open_brakes, calls_429=calls_429,
                           calls_ok=calls_ok, sleeps=sleeps)


def _company(db, ticker, exchange="NASDAQ"):
    db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange=exchange,
                   company_type="operating", valuation_model="standard"))
    db.commit()


# --- refresh_ticker_news_universe -----------------------------------------

def test_universo_sin_tenants_salta(env, monkeypatch):
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [])
    out = worker.refresh_ticker_news_universe.fn()
    assert out == {"status": "skipped", "actor": "refresh_ticker_news_universe",
                   "reason": "no_tenants"}


def test_universo_freno_abierto_salta_o_reprograma(env, monkeypatch):
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u")])
    env.open_brakes.add("yahoo")
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: False)
    out = worker.refresh_ticker_news_universe.fn()
    assert out["reason"] == "provider_brakes_open"
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: True)
    with pytest.raises(dramatiq.Retry):
        worker.refresh_ticker_news_universe.fn()


def test_universo_descarga_una_vez_y_encola_copias(env, monkeypatch):
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u"), (2, "v")])
    _company(env.db, "ACME")
    _company(env.db, "TEF.MC", exchange="BME")  # no US: fuera del universo
    out = worker.refresh_ticker_news_universe.fn()
    assert out["status"] == "ok" and out["universe"] == 1
    assert out["feeds_fetched"] == 1
    assert env.polls == ["ACME"]  # una descarga por ticker, no por tenant
    assert len(out["queued"]) == 2  # una copia persistida por tenant
    assert env.redis.get(worker._yahoo_universe_cache_key("ACME")) is not None
    assert worker._yahoo_universe_cache_key("TEF.MC") not in env.redis.store


def test_universo_freno_a_mitad_de_ciclo_corta(env, monkeypatch):
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u")])
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: False)
    _company(env.db, "ACME")
    _company(env.db, "BETA")

    def fake_is_open(client, p):
        return len(env.polls) >= 1  # se abre tras la primera descarga

    monkeypatch.setattr(brake, "is_open", fake_is_open)
    out = worker.refresh_ticker_news_universe.fn()
    assert len(env.polls) == 1  # no sigue pegando al proveedor
    assert any("freno abierto" in e["message"] for e in out["errors"])


def test_universo_429_alimenta_freno_y_no_cachea(env, monkeypatch):
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u")])
    _company(env.db, "ACME")
    env.outcomes["ACME"] = ConnectorResult(
        source="rss", errors=["Client error '429 Too Many Requests' for url"])
    out = worker.refresh_ticker_news_universe.fn()
    assert "yahoo" in env.calls_429
    assert worker._yahoo_universe_cache_key("ACME") not in env.redis.store
    assert out["feeds_fetched"] == 0


# --- persist_ticker_news_universe ------------------------------------------

def test_persistencia_hit_de_cache_sin_red(env):
    _company(env.db, "ACME")
    cached = ConnectorResult(
        source="rss",
        items=[ConnectorItem(source="rss", title="cacheado", url="https://x/1")])
    worker._yahoo_universe_cache_set(env.redis, "ACME", cached)
    out = worker.persist_ticker_news_universe.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["cache_hits"] == 1
    assert out["live_fetches"] == 0 and env.polls == []
    assert out["news_ingested"] == 1
    assert env.sleeps == []  # el pacing solo aplica a fail-open en vivo


def test_persistencia_miss_sin_freno_cae_a_la_red(env):
    _company(env.db, "ACME")
    out = worker.persist_ticker_news_universe.fn(tenant_id=1, user_id="u")
    assert out["live_fetches"] == 1 and env.polls == ["ACME"]
    assert env.redis.get(worker._yahoo_universe_cache_key("ACME")) is not None
    assert env.sleeps == [1.5]


def test_persistencia_miss_con_freno_no_reintenta(env):
    _company(env.db, "ACME")
    env.open_brakes.add("yahoo")
    out = worker.persist_ticker_news_universe.fn(tenant_id=1, user_id="u")
    assert env.polls == []  # nunca contra el proveedor con el freno abierto
    assert any("freno yahoo abierto" in e["message"] for e in out["errors"])


def test_cache_corrupta_es_un_miss(env):
    _company(env.db, "ACME")
    env.redis.set(worker._yahoo_universe_cache_key("ACME"), "{no-json")
    out = worker.persist_ticker_news_universe.fn(tenant_id=1, user_id="u")
    assert out["live_fetches"] == 1  # payload corrupto se trata como miss
