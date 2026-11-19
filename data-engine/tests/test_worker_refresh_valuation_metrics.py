"""refresh_valuation_metrics con sesion SQLite real: breaker Finnhub 429,
lease, cursor en Redis para suspender/reanudar, presupuesto agotado con
continuacion en mensaje nuevo y lease siempre liberado. Solo se sustituyen
la red, Redis y el servicio de valoracion."""

from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.connectors.finnhub as finnhub_connector
import app.services.valuation_metrics_service as vms
import app.workers.rate_limit_retry as rlr
from app.models.entities import Base
from app.workers import dramatiq_app as worker


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    e = SimpleNamespace(db=db, redis=FakeRedis(), released=[], continuation=[],
                        refresh_calls=[], refresh_result={"status": "ok"},
                        refresh_error=None, blocked=0.0, exhausted=False)
    monkeypatch.setattr(worker, "_redis_client", lambda: e.redis)
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: "LEASE")
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(finnhub_connector, "finnhub_blocked_for", lambda: e.blocked)
    monkeypatch.setattr(rlr, "retries_exhausted", lambda: e.exhausted)

    def fake_refresh(db_, start_after_ticker=None, deadline=None):
        e.refresh_calls.append({"start_after_ticker": start_after_ticker})
        if e.refresh_error is not None:
            raise e.refresh_error
        return e.refresh_result

    monkeypatch.setattr(vms, "refresh_valuation_metrics", fake_refresh)
    original = worker.refresh_valuation_metrics
    monkeypatch.setattr(worker, "refresh_valuation_metrics", SimpleNamespace(
        fn=original.fn,
        send_with_options=lambda **kw: e.continuation.append(kw)))
    e.original = original
    return e


def test_corrida_ok_borra_el_cursor_previo_y_libera_lease(env):
    env.redis.set("valuation_metrics:cursor:1", "ACME")
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["actor"] == "refresh_valuation_metrics"
    # La corrida reanuda DESPUES del cursor y al acabar lo borra.
    assert env.refresh_calls[0]["start_after_ticker"] == "ACME"
    assert env.redis.get("valuation_metrics:cursor:1") is None
    assert env.released == [("refresh_valuation_metrics:1", "LEASE")]


def test_lease_en_curso_skips(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: None)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped" and out["reason"] == "lease_held"
    assert env.refresh_calls == []


def test_breaker_finnhub_con_reintentos_agotados_skips(env):
    env.blocked = 120.0
    env.exhausted = True
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped"
    assert out["reason"] == "rate_limited_retries_exhausted"


def test_breaker_finnhub_reprograma_tras_la_ventana(env):
    env.blocked = 120.0
    with pytest.raises(dramatiq.Retry):
        env.original.fn(tenant_id=1, user_id="u")


def test_429_a_mitad_guarda_cursor_y_reprograma(env):
    env.refresh_error = vms.ValuationUniverseRateSuspended("BETA", 30.0)
    with pytest.raises(dramatiq.Retry):
        env.original.fn(tenant_id=1, user_id="u")
    assert env.redis.get("valuation_metrics:cursor:1") == "BETA"
    assert env.released  # el lease se libera tambien al suspender


def test_429_a_mitad_con_reintentos_agotados_skips_con_cursor(env):
    env.refresh_error = vms.ValuationUniverseRateSuspended("BETA", 30.0)
    env.exhausted = True
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped"
    assert out["reason"] == "rate_limited_retries_exhausted"
    assert out["cursor"] == "BETA"


def test_presupuesto_agotado_continua_en_mensaje_nuevo(env):
    env.refresh_error = vms.ValuationTimeBudgetExhausted("ACME")
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and out["reason"] == "time_budget"
    assert out["cursor"] == "ACME"
    assert env.redis.get("valuation_metrics:cursor:1") == "ACME"
    assert env.continuation[0]["kwargs"] == {"tenant_id": 1, "user_id": "u"}
    assert env.continuation[0]["delay"] >= worker.VALUATION_CONTINUATION_DELAY_MS


def test_error_inesperado_rollback_y_payload(env):
    env.refresh_error = ValueError("bug")
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_valuation_metrics"
    assert env.released  # lease liberado tambien con error


def test_redis_caido_es_fail_open(env, monkeypatch):
    def boom():
        raise RuntimeError("sin redis")

    monkeypatch.setattr(worker, "_redis_client", boom)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok"  # sin cursor: corrida entera
    assert env.refresh_calls[0]["start_after_ticker"] is None


class RedisSelectivo(FakeRedis):
    def __init__(self, falla=()):
        super().__init__()
        self.falla = falla

    def get(self, key):
        if "get" in self.falla:
            raise RuntimeError("caido")
        return super().get(key)

    def set(self, key, value, ex=None):
        if "set" in self.falla:
            raise RuntimeError("caido")
        super().set(key, value, ex=ex)

    def delete(self, key):
        if "delete" in self.falla:
            raise RuntimeError("caido")
        super().delete(key)


def test_error_de_sesion_devuelve_payload(env, monkeypatch):
    def boom(tenant, user):
        raise ValueError("sin base de datos")

    monkeypatch.setattr(worker, "_session", boom)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_valuation_metrics"


def test_error_adquiriendo_lease_cierra_y_propaga(env, monkeypatch):
    def boom(key, **kw):
        raise RuntimeError("redis lease caido")

    monkeypatch.setattr(worker, "acquire_job_lease", boom)
    with pytest.raises(RuntimeError):
        env.original.fn(tenant_id=1, user_id="u")


def test_sonda_de_cursor_fallida_es_corrida_entera(env, monkeypatch):
    env.redis = RedisSelectivo(falla={"get"})
    monkeypatch.setattr(worker, "_redis_client", lambda: env.redis)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok"
    assert env.refresh_calls[0]["start_after_ticker"] is None


def test_borrado_de_cursor_fallido_expira_por_ttl(env, monkeypatch):
    env.redis = RedisSelectivo(falla={"delete"})
    env.redis.store["valuation_metrics:cursor:1"] = "ACME"
    monkeypatch.setattr(worker, "_redis_client", lambda: env.redis)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok"


def test_429_sin_ticker_completado_no_guarda_cursor(env):
    env.refresh_error = vms.ValuationUniverseRateSuspended(None, 30.0)
    with pytest.raises(dramatiq.Retry):
        env.original.fn(tenant_id=1, user_id="u")
    assert env.redis.get("valuation_metrics:cursor:1") is None


def test_cursor_429_no_guardable_expira_por_ttl(env, monkeypatch):
    env.redis = RedisSelectivo(falla={"set"})
    monkeypatch.setattr(worker, "_redis_client", lambda: env.redis)
    env.refresh_error = vms.ValuationUniverseRateSuspended("BETA", 30.0)
    with pytest.raises(dramatiq.Retry):
        env.original.fn(tenant_id=1, user_id="u")


def test_presupuesto_sin_ticker_completado_continua_sin_cursor(env):
    env.refresh_error = vms.ValuationTimeBudgetExhausted(None)
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and out["cursor"] is None
    assert env.redis.get("valuation_metrics:cursor:1") is None
    assert env.continuation  # la continuacion se encola igual


def test_cursor_de_presupuesto_no_guardable_continua(env, monkeypatch):
    env.redis = RedisSelectivo(falla={"set"})
    monkeypatch.setattr(worker, "_redis_client", lambda: env.redis)
    env.refresh_error = vms.ValuationTimeBudgetExhausted("ACME")
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and env.continuation
