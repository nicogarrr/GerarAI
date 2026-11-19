"""refresh_macro_news con sesion SQLite real: lease, disyuntor GDELT,
racha de fallos, corte por presupuesto y contabilidad por tema.
Solo se sustituyen la red (poll_gdelt/ingest) y Redis."""

from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.feed_ingestion_service as fis
import app.services.macro_news as macro_news
from app.models.entities import Base
from app.services.connectors.gdelt import GdeltRateLimited
from app.workers import dramatiq_app as worker


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def exists(self, key):
        return int(key in self.store)

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    def expire(self, key, seconds):
        return True

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
    e = SimpleNamespace(
        db=db, redis=FakeRedis(), polls={}, poll_order=[], ingest_calls=[],
        released=[], lease="LEASE",
    )
    monkeypatch.setattr(worker, "_redis_client", lambda: e.redis)
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: e.lease)
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda key, lease, **kw: e.released.append((key, lease)))
    e.themes = [("inflacion", "q1"), ("tipos", "q2")]

    class FakeService:
        async def poll_gdelt(self, query, ticker=None, max_records=15):
            e.poll_order.append(query)
            outcome = e.polls[query]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def ingest_news_result(self, db_, result, **kw):
            e.ingest_calls.append(kw)
            return {"created": 1}

    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    monkeypatch.setattr(macro_news, "iter_macro_queries", lambda: e.themes)
    return e


def _ok():
    return SimpleNamespace(errors=[], status="ok")


def test_lease_en_curso_skips_y_cierra(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: None)
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped" and out["reason"] == "lease_held"


def test_temas_ok_ingieren_sin_empresa_y_liberan_lease(env):
    env.polls = {"q1": _ok(), "q2": _ok()}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["themes_processed"] == 2
    assert out["news_ingested"] == 2 and out["truncated"] is False
    assert env.poll_order == ["q1", "q2"]
    for call in env.ingest_calls:
        assert call["detect_company"] is False
        assert call["news_lane"] == "macro"
        assert call["macro_theme"] in {"inflacion", "tipos"}
    assert env.released == [("refresh_macro_news:1", "LEASE")]


def test_dos_fallos_seguidos_abren_el_disyuntor(env):
    env.polls = {"q1": RuntimeError("caido"), "q2": RuntimeError("caido")}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["themes_processed"] == 0
    tipos = [e["type"] for e in out["errors"] if e.get("type")]
    assert tipos == ["RuntimeError", "RuntimeError", "circuit_open"]
    assert env.redis.get(worker._GDELT_CIRCUIT_KEY) == "1"
    assert env.released  # el lease se libera tambien con error


def test_status_error_del_conector_tambien_abre_el_disyuntor(env):
    env.polls = {"q1": SimpleNamespace(errors=["red caida"], status="error"),
                 "q2": SimpleNamespace(errors=["red caida"], status="error")}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["themes_processed"] == 0
    assert any(e.get("type") == "circuit_open" for e in out["errors"])
    assert env.redis.get(worker._GDELT_CIRCUIT_KEY) == "1"


def test_429_lanza_retry_sin_tragar_la_ventana(env):
    env.polls = {"q1": GdeltRateLimited(120.0), "q2": _ok()}
    with pytest.raises(dramatiq.Retry):
        worker.refresh_macro_news.fn(tenant_id=1, user_id="u")


def test_presupuesto_agotado_corta_entre_temas(env, monkeypatch):
    monkeypatch.setattr(worker, "MACRO_NEWS_BUDGET_SECONDS", 0)
    env.polls = {"q1": _ok(), "q2": _ok()}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["themes_processed"] == 0 and out["truncated"] is True
    assert out["status"] == "partial"
    assert env.poll_order == []


def test_disyuntor_abierto_skips_sin_trabajar(env, monkeypatch):
    env.redis.set(worker._GDELT_CIRCUIT_KEY, "1")
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: False)
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped" and out["reason"] == "gdelt_circuit_open"
    assert env.poll_order == []


def test_disyuntor_abierto_en_reintento_reprograma(env, monkeypatch):
    import app.workers.rate_limit_retry as rlr

    env.redis.set(worker._GDELT_CIRCUIT_KEY, "1")
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: True)
    monkeypatch.setattr(rlr, "retries_exhausted", lambda: False)
    with pytest.raises(dramatiq.Retry):
        worker.refresh_macro_news.fn(tenant_id=1, user_id="u")


def _connector_result(items, errors):
    from app.services.connectors.base import ConnectorItem, ConnectorResult

    return ConnectorResult(
        source="gdelt",
        items=[ConnectorItem(source="gdelt", title=t) for t in items],
        errors=errors,
    )


def test_cache_hit_no_sondea_y_propaga_errores_cacheados(env):
    # Poblar la cache con el set REAL y leer con el get real (end to end).
    worker._gdelt_macro_cache_set(env.redis, "inflacion",
                                  _connector_result(["t1"], ["aviso parcial"]))
    env.polls = {"q2": _ok()}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert env.poll_order == ["q2"]  # inflacion vino de cache
    assert out["themes_processed"] == 2  # partial no es error: cuenta
    assert "aviso parcial" in [e["message"] for e in out["errors"]]


def test_cache_hit_con_error_no_cuenta_procesado(env):
    worker._gdelt_macro_cache_set(env.redis, "inflacion",
                                  _connector_result([], ["caido"]))
    env.polls = {"q2": _ok()}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["themes_processed"] == 1
    assert "caido" in [e["message"] for e in out["errors"]]


def test_redis_caido_es_fail_open(env, monkeypatch):
    def boom():
        raise RuntimeError("sin redis")

    monkeypatch.setattr(worker, "_redis_client", boom)
    env.polls = {"q1": _ok(), "q2": _ok()}
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["themes_processed"] == 2


def test_error_adquiriendo_lease_cierra_y_reporta(env, monkeypatch):
    def boom(key, **kw):
        raise RuntimeError("redis lease caido")

    monkeypatch.setattr(worker, "acquire_job_lease", boom)
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_macro_news"


def test_error_de_sesion_devuelve_payload_estructurado(env, monkeypatch):
    def boom(tenant, user):
        raise ValueError("sin base de datos")

    monkeypatch.setattr(worker, "_session", boom)
    out = worker.refresh_macro_news.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_macro_news"


def test_cache_get_fallo_de_redis_y_payload_corrupto_son_miss():
    class RedisRoto(FakeRedis):
        def get(self, key):
            raise RuntimeError("caido")

    assert worker._gdelt_macro_cache_get(RedisRoto(), "tema") is None
    ok = FakeRedis()
    ok.store[worker._gdelt_macro_cache_key("tema")] = "{json roto"
    assert worker._gdelt_macro_cache_get(ok, "tema") is None
