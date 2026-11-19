"""extract_document_kpis: extraccion idempotente, marca diferida que se
consume, deterministic-only con pendientes es partial, y aplazos por cuota
diaria / 402 (sin gastar el intento) / 429 (Retry, nunca dead-letter)."""

import time
from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.kpi_extraction_service as kes
from app.llm.errors import ProviderHTTPError
from app.models import Document
from app.models.entities import Base
from app.services.kpi_call_quota import KPIDailyDeferred
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    outcome = {"value": [SimpleNamespace(id=21)]}

    class FakeService:
        async def extract_document(self, db_, document):
            value = outcome["value"]
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(kes, "KPIExtractionService", FakeService)
    return SimpleNamespace(db=db, outcome=outcome)


def _document(db, metadata=None):
    doc = Document(tenant_id=1, title="informe", source_type="filing",
                   metadata_=metadata or {})
    db.add(doc)
    db.commit()
    return doc


def test_ok_devuelve_candidatos(env):
    doc = _document(env.db)
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["candidates"] == 1
    assert out["candidate_ids"] == [21] and out["document_id"] == doc.id


def test_documento_inexistente_es_error(env):
    out = worker.extract_document_kpis.fn(999, tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert "not found" in out["error"]["message"]


def test_marca_diferida_previa_se_consume(env):
    doc = _document(env.db, metadata={worker.KPI_DEFERRED_KEY: {"attempts": 2}})
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "ok"
    env.db.expire_all()
    assert worker.KPI_DEFERRED_KEY not in (env.db.get(Document, doc.id).metadata_ or {})


def test_deterministic_only_con_pendientes_es_partial(env):
    doc = _document(env.db, metadata={"kpi_deterministic": {
        "mode": "deterministic-only", "unresolved_metrics": ["ebitda"]}})
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "partial"
    assert out["mode"] == "deterministic-only"
    assert out["unresolved_metrics"] == ["ebitda"]


def test_cuota_diaria_agotada_difiere_con_marca(env):
    doc = _document(env.db)
    env.outcome["value"] = KPIDailyDeferred("cap diario")
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "deferred" and out["reason"] == "daily_call_limit"
    env.db.expire_all()
    meta = env.db.get(Document, doc.id).metadata_
    assert worker.KPI_DEFERRED_KEY in meta
    assert meta["kpi_daily_deferred"]["reason"] == "daily_call_limit"


def test_402_difiere_sin_gastar_el_intento(env):
    doc = _document(env.db, metadata={worker.KPI_DEFERRED_KEY: {"attempts": 3}})
    env.outcome["value"] = ProviderHTTPError("go", 402)
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "deferred"
    assert out["reason"] == "provider_payment_required"
    env.db.expire_all()
    deferred = env.db.get(Document, doc.id).metadata_[worker.KPI_DEFERRED_KEY]
    assert deferred["attempts"] == 2  # el reenvio ya persistio el intento
    assert deferred["not_before"] > int(time.time())


def test_429_reintenta_con_backoff_nunca_dead_letter(env):
    doc = _document(env.db)
    env.outcome["value"] = ProviderHTTPError("go", 429)
    with pytest.raises(dramatiq.Retry):
        worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")


def test_error_generico_devuelve_payload(env):
    doc = _document(env.db)
    env.outcome["value"] = ValueError("pdf roto")
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert out["error"]["context"]["document_id"] == doc.id
