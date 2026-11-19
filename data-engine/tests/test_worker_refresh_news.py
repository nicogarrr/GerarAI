"""refresh_news: barrido GDELT con disyuntor compartido (skip / Retry tras
su TTL), prioritarias primero, corte limpio por presupuesto, 429 que para
el barrido sin quemar cuota y errores por empresa sin frenar el resto."""

from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.feed_ingestion_service as fis
import app.workers.rate_limit_retry as rlr
from app.models import Company
from app.models.entities import Base
from app.services.connectors.base import ConnectorResult
from app.services.connectors.gdelt import GdeltRateLimited
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
    polls = []
    outcomes = {}

    class FakeService:
        async def poll_gdelt(self, query, *, ticker, max_records):
            polls.append(ticker)
            outcome = outcomes.get(ticker)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
            return ConnectorResult(source="gdelt", items=[f"i-{ticker}"])

        def ingest_news_result(self, db_, part, *, ticker):
            return {"created": len(part.items)}

    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    return SimpleNamespace(db=db, redis=redis, polls=polls, outcomes=outcomes)


def _company(db, ticker):
    db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ",
                   company_type="operating", valuation_model="standard"))
    db.commit()


def test_disyuntor_abierto_sin_reintento_salta(env, monkeypatch):
    env.redis.set(worker._GDELT_CIRCUIT_KEY, "1")
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: False)
    out = worker.refresh_news.fn(tenant_id=1, user_id="u")
    assert out == {"status": "skipped", "actor": "refresh_news",
                   "reason": "gdelt_circuit_open"}
    assert env.polls == []  # no se quema cuota contra una ventana cerrada


def test_disyuntor_abierto_con_reintento_reprograma_tras_ttl(env, monkeypatch):
    env.redis.set(worker._GDELT_CIRCUIT_KEY, "1")
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: True)
    monkeypatch.setattr(rlr, "retries_exhausted", lambda: False)
    with pytest.raises(dramatiq.Retry) as excinfo:
        worker.refresh_news.fn(tenant_id=1, user_id="u")
    ttl_ms = worker.GDELT_CIRCUIT_TTL_SECONDS * 1000
    assert excinfo.value.delay >= ttl_ms  # nunca antes de que cierre el disyuntor


def test_barrido_ok_prioritarias_primero_y_exito_registrado(env):
    _company(env.db, "ZZZ")
    _company(env.db, "ASTS")
    out = worker.refresh_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["companies_processed"] == 2
    assert out["news_ingested"] == 2
    assert env.polls[0] == "ASTS"  # prioritarias primero aunque el orden sea alfabetico
    assert env.redis.get(worker._GDELT_CIRCUIT_STREAK_KEY) in (None, "0")


def test_error_en_una_empresa_es_parcial_y_sigue(env):
    _company(env.db, "ACME")
    _company(env.db, "BETA")
    env.outcomes["ACME"] = ValueError("parse roto")
    out = worker.refresh_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and out["companies_processed"] == 1
    assert out["errors"][0]["ticker"] == "ACME"
    assert env.polls == ["ACME", "BETA"]  # el fallo no frena el resto


def test_429_para_el_barrido_y_reintenta_tras_la_ventana(env):
    _company(env.db, "ACME")
    _company(env.db, "BETA")
    env.outcomes["ACME"] = GdeltRateLimited(retry_after=300)
    with pytest.raises(dramatiq.Retry):
        worker.refresh_news.fn(tenant_id=1, user_id="u")
    assert env.polls == ["ACME"]  # no se quema cuota en las restantes


def test_resultado_con_errores_se_anota_y_cuenta(env):
    _company(env.db, "ACME")
    env.outcomes["ACME"] = ConnectorResult(
        source="gdelt", items=["i1"], errors=["timeout parcial"])
    out = worker.refresh_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial"
    assert out["errors"][0]["message"] == "timeout parcial"
    assert out["news_ingested"] == 1


def test_presupuesto_agotado_corta_limpio(env, monkeypatch):
    import app.services.ticker_news_lane as lane

    class FakeDeadline:
        def __init__(self, budget):
            self.calls = 0
            self.truncated = False

        def expired(self):
            self.calls += 1
            if self.calls > 1:
                self.truncated = True
            return self.truncated

    monkeypatch.setattr(lane, "Deadline", FakeDeadline)
    _company(env.db, "ACME")
    _company(env.db, "BETA")
    out = worker.refresh_news.fn(tenant_id=1, user_id="u")
    assert out["truncated"] is True and out["status"] == "partial"
    assert len(env.polls) <= 1
