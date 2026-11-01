"""Actor extract_document_kpis: idempotencia, limpieza del flag diferido y
degradacion estructurada ante errores permanentes.

El actor se invoca por ``.fn`` (sin broker): el contrato probado es el cuerpo
real — documento inexistente es error permanente (no reintento), la marca
``kpi_deferred`` se retira tras una extraccion exitosa, y los candidate_ids
devueltos son los del servicio.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Document
from app.services import kpi_extraction_service
from app.workers import dramatiq_app


@pytest.fixture
def engine():
    # una unica conexion compartida: el actor abre y CIERRA su sesion (finally),
    # asi que la verificacion usa otra sesion sobre el mismo sqlite en memoria
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _open(engine) -> Session:
    return Session(engine)


def _document(engine, metadata: dict | None = None) -> int:
    with _open(engine) as db:
        doc = Document(title="Doc", source_type="filing", metadata_=metadata or {})
        db.add(doc)
        db.commit()
        return doc.id


def _fake_service(monkeypatch, candidates=None, exc=None):
    async def fake_extract(self, db, document):
        if exc is not None:
            raise exc
        return candidates or []

    monkeypatch.setattr(kpi_extraction_service.KPIExtractionService, "extract_document", fake_extract)


def test_actor_documento_inexistente_es_error_permanente(engine, monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    out = dramatiq_app.extract_document_kpis.fn(9999)
    assert out["status"] == "error"
    assert out["actor"] == "extract_document_kpis"
    assert out["error"]["type"] == "ValueError"
    assert out["error"]["context"]["document_id"] == 9999


def test_actor_extrae_y_limpia_flag_diferido(engine, monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine, metadata={"kpi_deferred": {"attempts": 1}, "otro": "valor"})
    _fake_service(monkeypatch, candidates=[SimpleNamespace(id=11), SimpleNamespace(id=12)])
    out = dramatiq_app.extract_document_kpis.fn(doc_id)
    assert out["status"] == "ok"
    assert out["candidate_ids"] == [11, 12]
    assert out["candidates"] == 2
    with _open(engine) as db:
        doc = db.get(Document, doc_id)
        assert "kpi_deferred" not in doc.metadata_  # flag retirado tras exito
        assert doc.metadata_["otro"] == "valor"


def test_actor_sin_flag_no_toca_metadata(engine, monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine, metadata={"solo": "esto"})
    _fake_service(monkeypatch, candidates=[])
    out = dramatiq_app.extract_document_kpis.fn(doc_id)
    assert out["status"] == "ok" and out["candidates"] == 0
    with _open(engine) as db:
        assert db.get(Document, doc_id).metadata_ == {"solo": "esto"}


def test_actor_error_permanente_devuelve_fallo_estructurado(engine, monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine)
    _fake_service(monkeypatch, exc=ValueError("payload corrupto"))
    out = dramatiq_app.extract_document_kpis.fn(doc_id)
    assert out["status"] == "error"
    assert out["error"]["type"] == "ValueError"
    assert "payload corrupto" in out["error"]["message"]


def test_actor_error_transitorio_relancia_para_reintento(engine, monkeypatch):
    import redis.exceptions as redis_exc

    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine)
    _fake_service(monkeypatch, exc=redis_exc.ConnectionError("redis caido"))
    with pytest.raises(redis_exc.ConnectionError):
        dramatiq_app.extract_document_kpis.fn(doc_id)  # dramatiq reintenta


# ---------- 429 del proveedor LLM (dead-letter de prod, 1-nov-2026) ----------


def _current(monkeypatch, retries):
    import time

    message = SimpleNamespace(
        options={"retries": retries}, actor_name="extract_document_kpis", message_timestamp=time.time() * 1000
    )
    monkeypatch.setattr(dramatiq_app.CurrentMessage, "get_current_message", classmethod(lambda cls: message))


def test_actor_429_del_proveedor_reintenta_con_espera_larga(engine, monkeypatch):
    import dramatiq

    from app.llm.errors import ProviderHTTPError

    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine, metadata={"kpi_deferred": {"attempts": 0}})
    _fake_service(monkeypatch, exc=ProviderHTTPError("openrouter", 429))
    _current(monkeypatch, retries=1)
    with pytest.raises(dramatiq.Retry) as caught:
        dramatiq_app.extract_document_kpis.fn(doc_id)
    # Antes: backoff del actor de 15-30 s; la ventana del proveedor seguia cerrada.
    assert caught.value.delay >= 2 * dramatiq_app.KPI_RATE_LIMIT_BASE_SECONDS * 1000


def test_actor_429_en_el_ultimo_intento_no_va_a_dead_letter_y_queda_diferido(engine, monkeypatch):
    from app.llm.errors import ProviderHTTPError

    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine, metadata={"kpi_deferred": {"attempts": 0, "queued_at": 1}})
    _fake_service(monkeypatch, exc=ProviderHTTPError("openrouter", 429))
    _current(monkeypatch, retries=dramatiq_app.extract_document_kpis.options["max_retries"])
    out = dramatiq_app.extract_document_kpis.fn(doc_id)
    assert out["status"] == "skipped"
    assert out["reason"] == "rate_limited_retries_exhausted"
    with _open(engine) as db:
        # La marca diferida sigue: backfill_document_kpis lo vuelve a encolar.
        assert "kpi_deferred" in db.get(Document, doc_id).metadata_


def test_actor_5xx_del_proveedor_sigue_el_reintento_normal(engine, monkeypatch):
    from app.llm.errors import ProviderHTTPError

    monkeypatch.setattr(dramatiq_app, "_session", lambda *a: _open(engine))
    doc_id = _document(engine)
    _fake_service(monkeypatch, exc=ProviderHTTPError("openrouter", 503))
    with pytest.raises(ProviderHTTPError):
        dramatiq_app.extract_document_kpis.fn(doc_id)
