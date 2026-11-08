"""Rutas /api/sources: chunks, analisis, KPIs, ingesta y auditorias.

Sobre main (61.5%) faltaban el rebuild del indice, los chunks de un
documento, analyze/extract-kpis con sus 400/429/503, los candidatos KPI y
su aprobacion, la ingesta por fichero y URL (400/502) y el alias de ticker
en auditorias. Servicios sustituidos por dobles: sin LLM ni red.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import sources as mod
from app.api.routes.sources import (
    UrlIngestRequest,
    action_kpi_candidate,
    analyze_document,
    document_chunks,
    documents,
    documents_count,
    extract_document_kpis,
    import_transcript_text,
    ingest_document_file,
    ingest_document_url,
    kpi_candidates,
    rebuild_document_index,
    source_audits,
)
from app.llm.errors import LLMError
from app.models import (
    Company,
    Document,
    DocumentChunk,
    KPIExtractionCandidate,
    Position,
    SourceAudit,
    WatchItem,
)
from app.models.entities import Base
from app.services.budget import BudgetExceededError


@pytest.fixture
def db():
    # check_same_thread=False: extract-kpis e ingest-file sueltan la sesion
    # al pool de hilos (run_in_threadpool).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # una sola conexion: todos los hilos ven la misma DB en memoria
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.info["tenant_id"] = 1
        yield db
    engine.dispose()


def _document(db, **kw) -> Document:
    data = {"tenant_id": 1, "title": "Memoria 2025", "source_type": "upload"}
    data.update(kw)
    doc = Document(**data)
    db.add(doc)
    db.commit()
    return doc


# --- rebuild del indice ---------------------------------------------------


def test_rebuild_index_camino_feliz(db, monkeypatch):
    monkeypatch.setattr(
        mod, "RAGIndex", lambda: SimpleNamespace(rebuild_tenant=lambda db_: {"indexed": 5})
    )
    assert rebuild_document_index(db=db) == {"indexed": 5}


def test_rebuild_index_validacion_es_400(db, monkeypatch):
    def boom(db_):
        raise ValueError("indice corrupto")

    monkeypatch.setattr(mod, "RAGIndex", lambda: SimpleNamespace(rebuild_tenant=boom))
    with pytest.raises(HTTPException) as exc:
        rebuild_document_index(db=db)
    assert exc.value.status_code == 400


def test_rebuild_index_error_interno_es_502_sin_internos(db, monkeypatch):
    def boom(db_):
        raise RuntimeError("dsn=postgres://secreto")

    monkeypatch.setattr(mod, "RAGIndex", lambda: SimpleNamespace(rebuild_tenant=boom))
    with pytest.raises(HTTPException) as exc:
        rebuild_document_index(db=db)
    assert exc.value.status_code == 502
    assert "secreto" not in str(exc.value.detail)


# --- chunks de un documento ------------------------------------------------


def test_document_chunks_404(db):
    with pytest.raises(HTTPException) as exc:
        document_chunks(999, db=db)
    assert exc.value.status_code == 404


def test_document_chunks_orden_pagina_y_recorte(db):
    doc = _document(db)
    for i in range(3):
        db.add(
            DocumentChunk(
                tenant_id=1,
                document_id=doc.id,
                chunk_index=i,
                text="x" * 100,
                token_count=10,
            )
        )
    db.commit()
    page1 = document_chunks(doc.id, page=1, page_size=2, text_limit=50, db=db)
    assert [c["chunk_index"] for c in page1] == [0, 1]
    assert all(len(c["text"]) == 50 for c in page1)  # recortado a text_limit
    page2 = document_chunks(doc.id, page=2, page_size=2, text_limit=1800, db=db)
    assert [c["chunk_index"] for c in page2] == [2]


# --- analyze y extract-kpis -----------------------------------------------


def test_analyze_document_404(db):
    with pytest.raises(HTTPException) as exc:
        analyze_document(999, db=db)
    assert exc.value.status_code == 404


def test_analyze_document_delega_en_el_servicio(db, monkeypatch):
    doc = _document(db)
    monkeypatch.setattr(
        mod,
        "ClaimIntelligenceService",
        lambda: SimpleNamespace(
            scan_document=lambda db_, document, auto_apply: {"claims": 2, "auto": auto_apply}
        ),
    )
    assert analyze_document(doc.id, db=db) == {"claims": 2, "auto": True}


def _extract_mocks(monkeypatch, *, result=None, error=None):
    def fake_run(coro):
        if error:
            raise error
        return result

    monkeypatch.setattr(
        mod,
        "KPIExtractionService",
        lambda: SimpleNamespace(extract_document=lambda db_, doc: object()),
    )
    monkeypatch.setattr(mod, "run_from_any_context", fake_run)


def test_extract_kpis_404(db):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(extract_document_kpis(999, db=db))
    assert exc.value.status_code == 404


def test_extract_kpis_camino_feliz(db, monkeypatch):
    doc = _document(db)
    _extract_mocks(monkeypatch, result=[{"metric_key": "revenue"}])
    assert asyncio.run(extract_document_kpis(doc.id, db=db)) == [{"metric_key": "revenue"}]


def test_extract_kpis_validacion_es_400(db, monkeypatch):
    doc = _document(db)
    _extract_mocks(monkeypatch, error=ValueError("documento sin texto"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(extract_document_kpis(doc.id, db=db))
    assert exc.value.status_code == 400


def test_extract_kpis_llm_caido_es_503_sin_internos(db, monkeypatch):
    doc = _document(db)
    _extract_mocks(monkeypatch, error=LLMError("provider=X status=500 key=sk-123"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(extract_document_kpis(doc.id, db=db))
    assert exc.value.status_code == 503
    assert "sk-123" not in str(exc.value.detail)  # diagnostico interno no sale


def test_extract_kpis_presupuesto_agotado_es_429(db, monkeypatch):
    doc = _document(db)
    _extract_mocks(monkeypatch, error=BudgetExceededError("limite diario"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(extract_document_kpis(doc.id, db=db))
    assert exc.value.status_code == 429


# --- candidatos KPI --------------------------------------------------------


def _candidate(db, **kw) -> KPIExtractionCandidate:
    data = {
        "tenant_id": 1,
        "company_id": 1,
        "company_kpi_id": 1,
        "document_id": 1,
        "document_chunk_id": 1,
        "metric_key": "revenue",
        "raw_label": "Revenue",
        "raw_value": "100M",
        "period": "2025",
        "status": "pending_approval",
        "confidence": 0.9,
    }
    data.update(kw)
    cand = KPIExtractionCandidate(**data)
    db.add(cand)
    db.commit()
    return cand


def test_kpi_candidates_ticker_desconocido_es_404(db, monkeypatch):
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: None)
    with pytest.raises(HTTPException) as exc:
        kpi_candidates(ticker="NOPE", document_id=None, status=None, limit=100, db=db)
    assert exc.value.status_code == 404


def test_kpi_candidates_filtra_por_estado(db):
    _candidate(db)
    _candidate(db, metric_key="ebitda", status="approved")
    pending = kpi_candidates(ticker=None, document_id=None, status="pending_approval", limit=100, db=db)
    assert [c.metric_key for c in pending] == ["revenue"]
    todos = kpi_candidates(ticker=None, document_id=None, status=None, limit=100, db=db)
    assert len(todos) == 2


def test_action_kpi_candidate_404(db):
    payload = SimpleNamespace(action="approve", actor="qa")
    with pytest.raises(HTTPException) as exc:
        action_kpi_candidate(999, payload, db=db)
    assert exc.value.status_code == 404


def test_action_kpi_candidate_aprueba(db, monkeypatch):
    cand = _candidate(db)
    llamadas = []
    monkeypatch.setattr(
        mod,
        "KPIExtractionService",
        lambda: SimpleNamespace(
            approve=lambda db_, c, actor: llamadas.append(("approve", actor)),
            reject=lambda db_, c, actor: llamadas.append(("reject", actor)),
        ),
    )
    payload = SimpleNamespace(action="approve", actor="qa")
    out = action_kpi_candidate(cand.id, payload, db=db)
    assert llamadas == [("approve", "qa")]
    assert out.id == cand.id


def test_action_kpi_candidate_error_es_400(db, monkeypatch):
    cand = _candidate(db)

    def boom(db_, c, actor):
        raise ValueError("candidato ya resuelto")

    monkeypatch.setattr(
        mod,
        "KPIExtractionService",
        lambda: SimpleNamespace(approve=boom, reject=boom),
    )
    payload = SimpleNamespace(action="reject", actor="qa")
    with pytest.raises(HTTPException) as exc:
        action_kpi_candidate(cand.id, payload, db=db)
    assert exc.value.status_code == 400


# --- ingesta de documentos ---------------------------------------------------


class _FakeUpload:
    def __init__(self, data: bytes, filename="memoria.pdf"):
        self._data = data
        self.filename = filename
        self.content_type = "application/pdf"
        self._sent = False

    async def read(self, n: int) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._data


def test_ingest_file_camino_feliz(db, monkeypatch):
    capturado = {}
    monkeypatch.setattr(
        mod,
        "DocumentIngestionService",
        lambda: SimpleNamespace(ingest_bytes=lambda db_, **kw: capturado.update(kw) or {"id": 1}),
    )
    out = asyncio.run(
        ingest_document_file(
            ticker="ASTS", title="Memoria", source_type="manual_upload",
            source_url=None, file=_FakeUpload(b"pdf-content"), db=db,
        )
    )
    assert out == {"id": 1}
    assert capturado["ticker"] == "ASTS"
    assert capturado["content"] == b"pdf-content"


def test_ingest_file_validacion_es_400(db, monkeypatch):
    def boom(db_, **kw):
        raise ValueError("ticker desconocido")

    monkeypatch.setattr(
        mod, "DocumentIngestionService", lambda: SimpleNamespace(ingest_bytes=boom)
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingest_document_file(
                ticker="X", title="Memoria", source_type="manual_upload",
                source_url=None, file=_FakeUpload(b"data"), db=db,
            )
        )
    assert exc.value.status_code == 400


def test_ingest_file_error_interno_es_502(db, monkeypatch):
    def boom(db_, **kw):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(
        mod, "DocumentIngestionService", lambda: SimpleNamespace(ingest_bytes=boom)
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingest_document_file(
                ticker="X", title="Memoria", source_type="manual_upload",
                source_url=None, file=_FakeUpload(b"data"), db=db,
            )
        )
    assert exc.value.status_code == 502


def test_ingest_file_por_encima_del_limite_es_400(db, monkeypatch):
    monkeypatch.setattr(mod, "MAX_DOCUMENT_BYTES", 4)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingest_document_file(
                ticker="X", title="Memoria", source_type="manual_upload",
                source_url=None, file=_FakeUpload(b"0123456789"), db=db,
            )
        )
    assert exc.value.status_code == 400
    assert "15MB" in str(exc.value.detail)


def test_ingest_url_camino_feliz(db, monkeypatch):
    monkeypatch.setattr(
        mod,
        "DocumentIngestionService",
        lambda: SimpleNamespace(ingest_url=lambda db_, **kw: {"id": 7, **kw}),
    )
    payload = UrlIngestRequest(
        ticker="ASTS", title="Carta", url="https://example.com/carta", source_type="url"
    )
    out = ingest_document_url(payload, db=db)
    assert out["id"] == 7
    assert out["ticker"] == "ASTS"


def test_ingest_url_validacion_es_400(db, monkeypatch):
    def boom(db_, **kw):
        raise ValueError("url no accesible")

    monkeypatch.setattr(
        mod, "DocumentIngestionService", lambda: SimpleNamespace(ingest_url=boom)
    )
    payload = UrlIngestRequest(
        ticker="ASTS", title="Carta", url="https://example.com/carta", source_type="url"
    )
    with pytest.raises(HTTPException) as exc:
        ingest_document_url(payload, db=db)
    assert exc.value.status_code == 400


def test_ingest_url_error_interno_es_502(db, monkeypatch):
    def boom(db_, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr(
        mod, "DocumentIngestionService", lambda: SimpleNamespace(ingest_url=boom)
    )
    payload = UrlIngestRequest(
        ticker="ASTS", title="Carta", url="https://example.com/carta", source_type="url"
    )
    with pytest.raises(HTTPException) as exc:
        ingest_document_url(payload, db=db)
    assert exc.value.status_code == 502


# --- auditorias ------------------------------------------------------------


def test_source_audits_ticker_desconocido_devuelve_vacio(db, monkeypatch):
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: None)
    assert source_audits(ticker="SAN.MC", limit=100, offset=0, db=db) == []


def test_source_audits_sin_filtro_lista(db):
    db.add(SourceAudit(tenant_id=1, passed=True, source_coverage_score=0.8))
    db.commit()
    out = source_audits(ticker=None, limit=100, offset=0, db=db)
    assert len(out) == 1
    assert out[0]["passed"] is True
    assert out[0]["source_coverage_score"] == 0.8


# --- listado y recuento de documentos --------------------------------------


def _company(db, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=f"{ticker} Corp",
        exchange="BME",
        company_type="bank",
        valuation_model="dividend",
    )
    db.add(company)
    db.commit()
    return company


def _list_documents(db, **kw):
    # Todos los params explicitos: fuera del router los defaults Query(...)
    # no se resuelven y llegaria el objeto Query.
    params = {
        "ticker": None,
        "scope": None,
        "source_type": None,
        "q": None,
        "include_chunks": False,
        "page": 1,
        "page_size": 50,
        "chunk_limit": 1000,
        "chunk_text_limit": 1500,
        "db": db,
    }
    params.update(kw)
    return documents(**params)


def test_documents_ticker_desconocido_devuelve_vacio(db, monkeypatch):
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: None)
    assert _list_documents(db, ticker="NOPE") == []


def test_documents_scope_por_defecto_solo_seguidas(db):
    held = _company(db, "SAN")
    watched = _company(db, "IBE")
    other = _company(db, "TEF")
    db.add(Position(tenant_id=1, company_id=held.id, quantity=10))
    # El sufijo de mercado se resuelve a la empresa base: IBE.MC -> IBE.
    db.add(WatchItem(tenant_id=1, symbol="IBE.MC"))
    db.commit()
    _document(db, company_id=held.id, title="Doc cartera")
    _document(db, company_id=watched.id, title="Doc watchlist")
    _document(db, company_id=other.id, title="Doc no seguida")
    _document(db, title="Doc sin empresa")

    out = _list_documents(db)
    # created_at desempata (publicados NULL al final): mas reciente primero.
    assert [d["title"] for d in out] == ["Doc watchlist", "Doc cartera"]
    assert out[0]["ticker"] == "IBE"


def test_documents_scope_all_y_busqueda_escapa_comodines(db):
    company = _company(db, "TEF")
    _document(db, company_id=company.id, title="Informe 100% anual")
    _document(db, company_id=company.id, title="Informe 100 anual")

    assert len(_list_documents(db, scope="all")) == 2
    # Sin escape, el % seria comodin y casaria tambien "Informe 100 anual".
    out = _list_documents(db, scope="all", q="100%")
    assert [d["title"] for d in out] == ["Informe 100% anual"]
    assert len(_list_documents(db, scope="all", q="informe")) == 2
    assert _list_documents(db, scope="all", source_type="filing") == []


def test_documents_ticker_explicito_no_se_acota_al_universo(db, monkeypatch):
    company = _company(db, "TEF")
    _document(db, company_id=company.id, title="Doc TEF")
    _document(db, title="Doc otro")
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: company)

    out = _list_documents(db, ticker="TEF.MC")
    assert [d["title"] for d in out] == ["Doc TEF"]
    assert out[0]["ticker"] == "TEF"
    assert out[0]["chunks"] == []


def test_documents_con_chunks_ordenados_y_recortados(db):
    doc = _document(db)
    db.add(
        DocumentChunk(
            tenant_id=1, document_id=doc.id, chunk_index=1, text="b" * 300, token_count=2
        )
    )
    db.add(
        DocumentChunk(
            tenant_id=1, document_id=doc.id, chunk_index=0, text="a" * 300, token_count=1
        )
    )
    db.commit()

    out = _list_documents(db, scope="all", include_chunks=True, chunk_text_limit=120)
    chunks = out[0]["chunks"]
    assert [c["chunk_index"] for c in chunks] == [0, 1]
    assert all(len(c["text"]) == 120 for c in chunks)
    assert chunks[0]["token_count"] == 1


def test_documents_count_mismos_filtros_que_el_listado(db, monkeypatch):
    company = _company(db, "SAN")
    db.add(Position(tenant_id=1, company_id=company.id, quantity=1))
    _document(db, company_id=company.id, title="Doc cartera")
    _document(db, title="Doc sin empresa")

    assert documents_count(ticker=None, scope=None, source_type=None, q=None, db=db) == {
        "total": 1
    }
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: None)
    assert documents_count(ticker="NOPE", scope=None, source_type=None, q=None, db=db) == {
        "total": 0
    }


def test_kpi_candidates_filtra_por_documento(db):
    _candidate(db)
    _candidate(db, metric_key="ebitda", document_id=2)
    out = kpi_candidates(
        ticker=None, document_id=2, status="pending_approval", limit=100, db=db
    )
    assert [c.metric_key for c in out] == ["ebitda"]


# --- importacion manual de transcripciones ----------------------------------


def _transcript_payload(**kw):
    data = {"ticker": "SAN", "title": "Resultados 3T", "text": "x" * 40}
    data.update(kw)
    return mod.ManualTranscriptImportRequest(**data)


def test_import_transcript_text_camino_feliz(db, monkeypatch):
    service = SimpleNamespace(import_text=lambda **kw: {"document_id": 7})
    monkeypatch.setattr(mod, "ManualTranscriptImportService", lambda: service)
    assert import_transcript_text(payload=_transcript_payload(), db=db) == {"document_id": 7}


def test_import_transcript_text_valueerror_es_404(db, monkeypatch):
    def _raise(**kw):
        raise ValueError("empresa desconocida")

    service = SimpleNamespace(import_text=_raise)
    monkeypatch.setattr(mod, "ManualTranscriptImportService", lambda: service)
    with pytest.raises(HTTPException) as exc:
        import_transcript_text(payload=_transcript_payload(ticker="NOPE"), db=db)
    assert exc.value.status_code == 404
