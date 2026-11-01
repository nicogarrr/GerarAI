"""Tests de helpers de app/workers/dramatiq_app.py (clasificacion de fallos y colas).

Cubre la logica de reintento (transitorio vs permanente, breaker 429 SEC),
extraccion de status HTTP del texto, marcas atomicas de encolado y el
enqueue de KPIs con backpressure. Redis se sustituye por un falso en memoria:
lo que se prueba es la logica del worker, no el falso.
"""

from __future__ import annotations

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.workers.dramatiq_app as da
from app.llm.errors import ProviderHTTPError, ProviderTransportError
from app.models.entities import Base, Company, Document


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.fail = False

    def _maybe_fail(self):
        if self.fail:
            raise ConnectionError("redis caido")

    def get(self, key):
        self._maybe_fail()
        return self.store.get(key)

    def incr(self, key):
        self._maybe_fail()
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, seconds):
        self._maybe_fail()
        return True

    def set(self, key, value, nx=False, ex=None):
        self._maybe_fail()
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        self._maybe_fail()
        self.store.pop(key, None)


def test_failure_estructura_estable():
    out = da._failure("actor_x", ValueError("boom"), doc_id=3)
    assert out["status"] == "error"
    assert out["actor"] == "actor_x"
    assert out["error"]["type"] == "ValueError"
    assert out["error"]["message"] == "boom"
    assert out["error"]["context"] == {"doc_id": 3}


def test_status_from_message_formas_conocidas():
    assert da._status_from_message("request failed (503 Service Unavailable)") == 503
    assert da._status_from_message("error (500)") == 500
    assert da._status_from_message("status 502") == 502
    assert da._status_from_message("status_code= 429") == 429
    assert da._status_from_message("Client error '429 Too Many Requests' for url") == 429
    assert da._status_from_message("HTTP/1.1 404 Not Found") == 404


def test_status_from_message_rechaza_no_status():
    # el parser no acepta cualquier numero de 3 cifras: solo formatos con
    # parentesis, "status", comillas estilo httpx o HTTP/x.y
    assert da._status_from_message("en 2024 hubo 500 empresas") is None
    assert da._status_from_message("sin numeros") is None
    assert da._status_from_message("(199) no es status") is None
    assert da._status_from_message("(700) fuera de rango") is None


def test_is_transient_clasificacion():
    assert da._is_transient(ProviderTransportError("p", "timeout", 1)) is True
    assert da._is_transient(ProviderHTTPError("p", 429)) is True
    assert da._is_transient(ProviderHTTPError("p", 500)) is True
    assert da._is_transient(ProviderHTTPError("p", 400)) is False
    assert da._is_transient(ConnectionError("corte")) is True
    assert da._is_transient(ValueError("payload malo")) is False


def test_is_transient_status_embebido_en_texto():
    exc = RuntimeError("SEC request failed (503 Service Unavailable)")
    assert da._is_transient(exc) is True
    exc400 = RuntimeError("Client error '400 Bad Request' for url 'https://x'")
    assert da._is_transient(exc400) is False


def test_is_sec_failure_por_url_en_mensaje_y_lookalikes():
    exc = RuntimeError("Client error '403 Forbidden' for url 'https://www.sec.gov/cgi-bin/x'")
    assert da._is_sec_failure(exc) is True
    evil = RuntimeError("Client error '403 Forbidden' for url 'https://sec.gov.evil.com/x'")
    assert da._is_sec_failure(evil) is False
    plain = RuntimeError("fallo generico")
    assert da._is_sec_failure(plain) is False


def test_sec_403_es_permanente_y_429_depende_del_breaker(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(da, "_redis_client", lambda: fake)
    exc403 = RuntimeError("Client error '403 Forbidden' for url 'https://www.sec.gov/x'")
    assert da._is_transient(exc403) is False
    exc429 = RuntimeError("Client error '429 Too Many Requests' for url 'https://www.sec.gov/x'")
    assert da._is_transient(exc429) is True  # racha 1: reintenta


def test_sec_429_breaker_se_abre_tras_racha(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(da, "_redis_client", lambda: fake)
    for _ in range(da._SEC_429_STREAK_LIMIT - 1):
        assert da._sec_rate_limit_allows_retry() is True
    assert da._sec_rate_limit_allows_retry() is False  # abre el breaker
    assert fake.store[da._SEC_BREAKER_OPEN_KEY] == "1"
    fake.store.clear()
    assert da._sec_rate_limit_allows_retry() is True  # racha reiniciada


def test_sec_breaker_fail_open_sin_redis(monkeypatch):
    monkeypatch.setattr(da, "_redis_client", lambda: None)
    assert da._sec_rate_limit_allows_retry() is True
    fake = _FakeRedis()
    fake.fail = True
    monkeypatch.setattr(da, "_redis_client", lambda: fake)
    assert da._sec_rate_limit_allows_retry() is True


def test_raise_gdelt_retry_respeta_ventana_y_suelo():
    class _E(Exception):
        retry_after = 3600.0

    with pytest.raises(dramatiq.Retry) as exc:
        da._raise_gdelt_retry(_E("cerrado"))
    assert exc.value.delay == 3_600_000

    class _E0(Exception):
        retry_after = 0.0

    with pytest.raises(dramatiq.Retry) as exc0:
        da._raise_gdelt_retry(_E0("sin ventana"))
    assert exc0.value.delay == int(da.GDELT_RETRY_FLOOR_SECONDS * 1000)


def test_handle_actor_error_relancia_transitorios_y_registra_permanentes():
    with pytest.raises(ProviderTransportError):
        da._handle_actor_error("actor", ProviderTransportError("p", "timeout", 1))
    out = da._handle_actor_error("actor", ValueError("malo"), doc=1)
    assert out["status"] == "error"
    assert out["error"]["type"] == "ValueError"


def test_batch_status():
    assert da._batch_status(0, []) == "ok"
    assert da._batch_status(3, []) == "ok"
    assert da._batch_status(3, [{"e": 1}]) == "partial"
    assert da._batch_status(0, [{"e": 1}]) == "error"


def test_claim_analysis_enqueue_atomica_y_fail_open(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(da, "_redis_client", lambda: fake)
    assert da._claim_analysis_enqueue(1, 10) is True
    assert da._claim_analysis_enqueue(1, 10) is False  # ya marcada
    assert da._claim_analysis_enqueue(2, 10) is True  # otro tenant
    da._clear_analysis_enqueue_mark(1, 10)
    assert da._claim_analysis_enqueue(1, 10) is True
    monkeypatch.setattr(da, "_redis_client", lambda: None)
    assert da._claim_analysis_enqueue(1, 99) is True  # fail-open


def _db_with_document():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    session.info["user_id"] = "user-1"
    company = Company(
        ticker="KPI", name="KPI Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    session.add(company)
    session.flush()
    doc = Document(company_id=company.id, tenant_id=1, title="10-K", source_type="sec_filing")
    session.add(doc)
    session.commit()
    return session, doc


def test_enqueue_document_kpis_marca_deferred_y_envia(monkeypatch):
    session, doc = _db_with_document()
    sent = {}

    class _Msg:
        message_id = "msg-1"

    monkeypatch.setattr(da.extract_document_kpis, "send", lambda *a, **k: sent.update({"args": a, "kwargs": k}) or _Msg())
    out = da.enqueue_document_kpis(session, doc)
    assert out["status"] == "queued"
    assert out["message_id"] == "msg-1"
    assert sent["args"] == (doc.id,)
    assert sent["kwargs"] == {"tenant_id": 1, "user_id": "user-1"}
    assert da.KPI_DEFERRED_KEY in doc.metadata_  # estado de recovery persistido


def test_enqueue_document_kpis_backpressure_y_cola_caida(monkeypatch):
    session, doc = _db_with_document()

    def boom(*a, **k):
        raise da.QueueCapacityError("llena")

    monkeypatch.setattr(da.extract_document_kpis, "send", boom)
    out = da.enqueue_document_kpis(session, doc)
    assert out == {"status": "deferred_backpressure"}
    assert doc.metadata_[da.KPI_DEFERRED_KEY]["attempts"] == 0

    def boom2(*a, **k):
        raise ConnectionError("broker caido")

    monkeypatch.setattr(da.extract_document_kpis, "send", boom2)
    out2 = da.enqueue_document_kpis(session, doc)
    assert out2["status"] == "queue_unavailable"
    assert out2["error"] == "ConnectionError"
