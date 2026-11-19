"""Helpers nucleo del worker: breaker SEC 429, coalesced_send (dedup en
vuelo, fail-open), _session (tenant activo + idioma heredado, transaccion
cerrada), tenant_contexts, carriles tracked (news y precios con reglas de
alerta) y enqueue_document_kpis (estado persistido antes de encolar)."""

import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.core.database as coredb
from app.models import AlertRule, Company, Position, Tenant, WatchItem
from app.models.entities import Base
from app.workers import dramatiq_app as worker
from app.workers.bounded_broker import QueueCapacityError


class FakeRedis:
    def __init__(self):
        self.store = {}

    def exists(self, key):
        return int(key in self.store)

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    def expire(self, key, ttl):
        return True

    def eval(self, script, nkeys, key, token):
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0

    def close(self):
        pass


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.info["user_id"] = "u"
    return db


def _tenant(db, tid, status="active", metadata=None):
    db.add(Tenant(id=tid, external_id=f"ext-{tid}", name=f"t{tid}",
                  status=status, metadata_=metadata or {}))
    db.commit()


# --- _sec_rate_limit_allows_retry -------------------------------------------

def test_sec_retry_sin_redis_failopen(monkeypatch):
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    assert worker._sec_rate_limit_allows_retry() is True


def test_sec_retry_breaker_abierto_no_reintenta():
    redis = FakeRedis()
    redis.set(worker._SEC_BREAKER_OPEN_KEY, "1")
    assert worker._sec_rate_limit_allows_retry(redis) is False


def test_sec_retry_racha_abre_el_breaker():
    redis = FakeRedis()
    limite = worker._SEC_429_STREAK_LIMIT
    for _ in range(limite - 1):
        assert worker._sec_rate_limit_allows_retry(redis) is True
    assert worker._sec_rate_limit_allows_retry(redis) is False
    assert redis.get(worker._SEC_BREAKER_OPEN_KEY) == "1"  # la racha abre el breaker
    assert redis.get(worker._SEC_BREAKER_STREAK_KEY) is None


def test_sec_retry_redis_roto_failopen():
    class BrokenRedis:
        def get(self, key):
            raise ConnectionError("caido")

    assert worker._sec_rate_limit_allows_retry(BrokenRedis()) is True


# --- coalesced_send ------------------------------------------------------------

def _fake_actor(sends, name="refresh_news", exc=None):
    def send(*args, **kwargs):
        if exc is not None:
            raise exc
        sends.append((args, kwargs))
        return SimpleNamespace(message_id=f"m-{len(sends)}")
    return SimpleNamespace(actor_name=name, send=send)


def test_coalesced_sin_politica_envia_siempre(monkeypatch):
    sends = []
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    actor = _fake_actor(sends, name="actor_sin_politica")
    assert worker.coalesced_send(actor, 1, user_id="u") is not None
    assert worker.coalesced_send(actor, 1, user_id="u") is not None
    assert len(sends) == 2  # trabajo por evento: nunca se suprime


def test_coalesced_una_copia_en_vuelo(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(worker, "_redis_client", lambda: redis)
    sends = []
    actor = _fake_actor(sends)
    first = worker.coalesced_send(actor, tenant_id=1, user_id="u")
    assert first is not None
    assert worker.coalesced_send(actor, tenant_id=1, user_id="u") is None
    assert len(sends) == 1  # el tick duplicado se suprime


def test_coalesced_redis_caido_failopen(monkeypatch):
    monkeypatch.setattr(worker, "_redis_client",
                        lambda: (_ for _ in ()).throw(ConnectionError("caido")))
    sends = []
    assert worker.coalesced_send(_fake_actor(sends), tenant_id=1) is not None
    assert len(sends) == 1  # perder el tick es peor que un duplicado


def test_coalesced_send_roto_libera_la_marca(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(worker, "_redis_client", lambda: redis)
    actor = _fake_actor([], exc=RuntimeError("broker lleno"))
    with pytest.raises(RuntimeError):
        worker.coalesced_send(actor, tenant_id=1, user_id="u")
    key = worker._enqueue_mark_key("refresh_news", tuple(str(v) for v in (None,)))
    # la marca se libera solo si somos dueños del token: el siguiente tick encola
    assert not any(k.startswith("enqueue:") or "refresh_news" in k for k in redis.store)


# --- _session -------------------------------------------------------------------

def test_session_ok_hereda_idioma_y_cierra_transaccion(db_session, monkeypatch):
    _tenant(db_session, 1, metadata={"language": "es"})
    monkeypatch.setattr(coredb, "SessionLocal", lambda: db_session)
    db = worker._session(1, "u")
    assert db.info["tenant_id"] == 1 and db.info["user_id"] == "u"
    assert db.info["language"] == "es"


def test_session_sin_tenant_lanza(db_session, monkeypatch):
    monkeypatch.setattr(coredb, "SessionLocal", lambda: db_session)
    with pytest.raises(ValueError, match="required"):
        worker._session(None, "u")
    with pytest.raises(ValueError, match="not found"):
        worker._session(999, "u")


def test_session_tenant_inactivo_lanza(db_session, monkeypatch):
    _tenant(db_session, 2, status="suspended")
    monkeypatch.setattr(coredb, "SessionLocal", lambda: db_session)
    with pytest.raises(ValueError, match="not found"):
        worker._session(2, "u")


# --- tenant_contexts --------------------------------------------------------------

def test_tenant_contexts_solo_activos_con_usuario(db_session, monkeypatch):
    _tenant(db_session, 1, metadata={"created_by": "nico"})
    _tenant(db_session, 2)  # sin created_by: fuera
    _tenant(db_session, 3, status="suspended", metadata={"created_by": "x"})
    monkeypatch.setattr(coredb, "SessionLocal", lambda: db_session)
    assert worker.tenant_contexts() == [(1, "nico")]


# --- carriles tracked ---------------------------------------------------------

def _company(db, ticker):
    db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ",
                   company_type="operating", valuation_model="standard"))
    db.commit()
    return db.query(Company).filter_by(ticker=ticker).one()


def test_tracked_companies_watchlist_y_cartera(db_session):
    acme = _company(db_session, "ACME")
    beta = _company(db_session, "BETA")
    _company(db_session, "GAMMA")
    db_session.add(WatchItem(tenant_id=1, symbol="acme"))  # minusculas valen
    db_session.add(Position(tenant_id=1, company_id=beta.id, quantity=1))
    db_session.commit()
    assert [c.ticker for c in worker._tracked_companies(db_session)] == ["ACME", "BETA"]
    assert acme is not None


def test_tracked_companies_sin_nada_vacio(db_session):
    _company(db_session, "ACME")
    assert worker._tracked_companies(db_session) == []


def test_price_tracked_incluye_reglas_de_alerta(db_session):
    _company(db_session, "ACME")
    gamma = _company(db_session, "GAMMA")
    db_session.add(WatchItem(tenant_id=1, symbol="ACME"))
    db_session.add(AlertRule(tenant_id=1, company_id=gamma.id, name="r",
                             rule_type="price", active=True))
    db_session.commit()
    assert [c.ticker for c in worker._price_tracked_companies(db_session)] == ["ACME", "GAMMA"]


# --- enqueue_document_kpis -------------------------------------------------------

def _document(db):
    from app.models import Document

    doc = Document(tenant_id=1, title="informe", source_type="filing", metadata_={})
    db.add(doc)
    db.commit()
    return doc


def test_enqueue_kpis_ok_marca_y_encola(db_session, monkeypatch):
    doc = _document(db_session)
    monkeypatch.setattr(worker, "extract_document_kpis", SimpleNamespace(
        send=lambda *a, **k: SimpleNamespace(message_id="m-1")))
    out = worker.enqueue_document_kpis(db_session, doc)
    assert out == {"status": "queued", "message_id": "m-1"}
    db_session.expire_all()
    meta = db_session.get(type(doc), doc.id).metadata_
    assert meta[worker.KPI_DEFERRED_KEY]["attempts"] == 0
    assert meta[worker.KPI_DEFERRED_KEY]["queued_at"] <= int(time.time())


def test_enqueue_kpis_cola_llena_estado_persistido(db_session, monkeypatch):
    doc = _document(db_session)

    def full(*a, **k):
        raise QueueCapacityError("llena")

    monkeypatch.setattr(worker, "extract_document_kpis", SimpleNamespace(send=full))
    out = worker.enqueue_document_kpis(db_session, doc)
    assert out == {"status": "deferred_backpressure"}
    db_session.expire_all()
    # nunca se pierde el trabajo KPI del documento ya ingerido
    assert worker.KPI_DEFERRED_KEY in db_session.get(type(doc), doc.id).metadata_


def test_enqueue_kpis_timeout_ambiguo(db_session, monkeypatch):
    doc = _document(db_session)

    def timeout(*a, **k):
        raise TimeoutError("quiza llego")

    monkeypatch.setattr(worker, "extract_document_kpis", SimpleNamespace(send=timeout))
    out = worker.enqueue_document_kpis(db_session, doc)
    assert out["status"] == "queue_unavailable" and out["error"] == "TimeoutError"
