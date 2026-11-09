"""Ingesta de documentos: caminos de ingest_bytes/ingest_url y sus salvaguardas.

SQLite real en memoria (estilo de la casa): cada test crea su empresa y sus
filas. El almacenamiento de bytes va doblado en memoria (DocumentStore real
escribe en storage/raw del repo; aqui no interesa el disco sino el camino de
ingesta), y los pasos opcionales post-ingesta (filing intelligence, inputs
sectoriales, auto-research, RAG, clasificador Jev) van doblados SOLO en los
tests que fijan su contrato de fallo: un paso opcional caido nunca disfraza
una ingesta ya persistida.

NO prueba (declarado): el disco real (DocumentStore doblado), LLMs reales
(Jev/RAG/claim intelligence doblados en los tests de fallo), ni el encolado
KPI al worker (CAVAAI_ENABLE_AUTO_KPI_EXTRACTION: camino saltado a proposito
por tocar el pipeline LLM; queda declarado).
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.services.document_ingestion_service as dis
from app.models.entities import Base, Company, Document, DocumentChunk
from app.services.document_ingestion_service import DocumentIngestionService

TENANT = 1  # int >= 1: el contrato de evidencia exige tenant ligado (evidence_contract.py:282)
SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/0001/aapl-20250329.htm"
TEXTO = b"Contenido del documento con texto suficiente para superar el minimo. " * 2


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = TENANT
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def _sin_disco(monkeypatch):
    """DocumentStore doblado en memoria: sin escrituras en storage/raw."""
    escritos: dict[str, int] = {}

    class _Store:
        def put_bytes(self, ticker, source_type, name, content, *,
                      tenant_id=None, content_type=None):
            uri = f"mem://{ticker}/{source_type}/{name}"
            escritos[uri] = len(content)
            return uri

    monkeypatch.setattr(dis, "DocumentStore", _Store)
    return escritos


def _empresa(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193",
        company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _ingesta_basica(db, **kwargs):
    params = dict(
        ticker="AAPL", title="Documento de prueba", content=TEXTO,
        filename="nota.txt", source_type="test_upload",
    )
    params.update(kwargs)
    return DocumentIngestionService().ingest_bytes(db, **params)


def test_contenido_vacio_rechazado(db):
    with pytest.raises(ValueError, match="Document is empty"):
        _ingesta_basica(db, content=b"")


def test_empresa_desconocida_rechazada(db):
    with pytest.raises(ValueError, match="not found"):
        _ingesta_basica(db, ticker="NOEXISTE")


def test_extension_no_soportada_rechazada(db):
    _empresa(db)
    with pytest.raises(ValueError, match="Unsupported document extension"):
        _ingesta_basica(db, filename="nota.bin")
    assert db.scalar(select(func.count(Document.id))) == 0


def test_texto_insuficiente_rechazado(db):
    """El parser devuelve menos de 20 caracteres: no se guarda nada."""
    _empresa(db)
    with pytest.raises(ValueError, match="too little text"):
        _ingesta_basica(db, content=b"corto")
    assert db.scalar(select(func.count(Document.id))) == 0


def test_ir_contenido_nuevo_con_misma_url_no_es_duplicado(db):
    """source_type IR sin ficha previa con ese digest: ingesta normal (la rama
    'known is None'), con el digest normalizado guardado en metadata."""
    _empresa(db)
    resultado = _ingesta_basica(
        db, source_type="IR", filename="nota.html",
        source_url="https://ir.example.com/apple/nota-2025",
        content=(b"<html><body><p>Nota de relaciones con inversores con "
                 b"texto real y suficiente para la ingesta.</p></body></html>"),
        content_type="text/html",
    )
    assert resultado["status"] == "ingested"
    documento = db.get(Document, resultado["document_id"])
    assert documento.metadata_["ir_normalized_digest"]


def test_ficha_stub_se_completa_con_la_ingesta_real(db):
    """Una ficha de filing (misma URL de archivo, sin bytes ni chunks) no
    bloquea la ingesta del texto: se completa en la misma fila."""
    company = _empresa(db)
    stub = Document(
        company_id=company.id, title="Ficha 10-K", source_type="filing_evidence",
        source_url=SEC_URL, published_at=datetime(2026, 9, 27, tzinfo=UTC),
        metadata_={"form": "10-K"}, tenant_id=TENANT,
    )
    db.add(stub)
    db.commit()
    stub_id = stub.id

    resultado = _ingesta_basica(
        db, title="AAPL 10-K texto completo", filename="aapl-20250329.htm",
        source_type="SEC", source_url=SEC_URL,
    )
    assert resultado["status"] == "ingested"
    assert resultado["document_id"] == stub_id
    db.expire_all()
    completada = db.get(Document, stub_id)
    assert completada.title == "AAPL 10-K texto completo"
    assert completada.source_type == "SEC"
    assert completada.storage_uri and completada.storage_uri.startswith("mem://")
    assert completada.checksum
    assert completada.metadata_["form"] == "10-K"  # conserva lo de la ficha
    assert completada.metadata_["parser"] == "native_html"
    filas = db.scalar(select(func.count(Document.id)).where(
        Document.source_url == SEC_URL))
    assert filas == 1
    chunks = db.scalars(select(DocumentChunk).where(
        DocumentChunk.document_id == stub_id)).all()
    assert len(chunks) == resultado["chunks"] > 0
    assert all("Contenido del documento" in chunk.text for chunk in chunks)
    contrato = completada.metadata_["evidence_contract"]
    assert contrato.get("source_id")  # no vacio: la igualdad siguiente no es None==None
    assert all(chunk.metadata_.get("evidence_source_id") == contrato["source_id"]
               for chunk in chunks)
    assert all(chunk.metadata_.get("evidence_chunk_id") for chunk in chunks)


def test_filing_intelligence_caido_no_disfraza_la_ingesta(db, monkeypatch):
    """El analisis opcional falla despues del commit: status failed con el tipo
    de la excepcion, y el documento sigue persistido."""
    import app.services.filing_intelligence as fi

    _empresa(db)
    monkeypatch.setattr(fi, "official_document", lambda document: True)

    def _cae(db_, document):
        raise RuntimeError("jev caido")

    monkeypatch.setattr(fi, "analyze_document", _cae)
    resultado = _ingesta_basica(db)
    assert resultado["status"] == "ingested"
    assert resultado["filing_analysis"] == {"status": "failed",
                                            "error": "RuntimeError"}
    assert db.get(Document, resultado["document_id"]) is not None


def test_sector_inputs_caido_no_disfraza_la_ingesta(db, monkeypatch):
    import app.services.sector_inputs as si

    _empresa(db)

    def _cae(db_, document):
        raise ValueError("extractor roto")

    monkeypatch.setattr(si, "extract_from_document", _cae)
    resultado = _ingesta_basica(db)
    assert resultado["status"] == "ingested"
    assert resultado["sector_inputs"] == {"status": "failed",
                                          "error": "ValueError"}


def test_auto_research_caido_no_disfraza_la_ingesta(db, monkeypatch):
    import app.services.claim_intelligence_service as ci

    _empresa(db)

    class _ServicioCaido:
        def scan_document(self, db_, document, auto_apply=False):
            raise RuntimeError("qdrant fuera")

    monkeypatch.setattr(ci, "ClaimIntelligenceService", _ServicioCaido)
    resultado = _ingesta_basica(db)
    assert resultado["status"] == "ingested"
    assert resultado["intelligence"]["status"] == "failed"
    assert resultado["intelligence"]["error"] == "qdrant fuera"  # mensaje redactado, no el tipo
    assert resultado["intelligence"]["document_id"] == resultado["document_id"]


def _rag_falso(monkeypatch, *, falla=False):
    modulo = types.ModuleType("app.services.rag")

    class _RAG:
        def ingest_document(self, db_, document):
            if falla:
                raise ConnectionError("qdrant fuera")
            return {"chunks_indexed": 3}

    modulo.RAGIndex = _RAG
    monkeypatch.setitem(sys.modules, "app.services.rag", modulo)


def test_rag_activado_indexa(db, monkeypatch):
    _empresa(db)
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_INGEST", "1")
    _rag_falso(monkeypatch)
    resultado = _ingesta_basica(db)
    assert resultado["status"] == "ingested"
    assert resultado["rag"] == {"chunks_indexed": 3}


def test_rag_activado_y_caido_no_tumba_la_ingesta(db, monkeypatch):
    _empresa(db)
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_INGEST", "1")
    _rag_falso(monkeypatch, falla=True)
    resultado = _ingesta_basica(db)
    assert resultado["status"] == "ingested"
    assert resultado["rag"]["chunks_indexed"] == 0
    assert "qdrant fuera" in resultado["rag"]["error"]


def test_jev_caido_no_rompe_la_ingesta(db, monkeypatch):
    """El clasificador documental Jev es best-effort: ante error, el documento
    se ingiere sin la clave jev_doc_type."""
    import app.services.jev_triage_service as jev

    _empresa(db)

    def _cae(texto):
        raise RuntimeError("typesafe fuera")

    monkeypatch.setattr(jev, "classify_doc_type_sync", _cae)
    resultado = _ingesta_basica(db)
    assert resultado["status"] == "ingested"
    documento = db.get(Document, resultado["document_id"])
    assert "jev_doc_type" not in documento.metadata_


def test_ingest_url_deriva_nombre_de_la_url_final(db, monkeypatch):
    """Sin path en la URL final, el nombre sale del host; el fetch va doblado."""
    _empresa(db)
    monkeypatch.setattr(dis, "fetch_public_url", lambda url, max_bytes, timeout: (
        TEXTO, "text/plain", "https://example.com/"))
    resultado = DocumentIngestionService().ingest_url(
        db, ticker="AAPL", title="Nota desde URL",
        url="https://example.com", source_type="test_upload",
    )
    assert resultado["status"] == "ingested"
    documento = db.get(Document, resultado["document_id"])
    assert documento.metadata_["filename"] == "example.com.html"
    assert documento.source_url == "https://example.com/"


def test_extension_desde_content_type_sin_sufijo():
    """Sin extension en el nombre, el content_type decide (pdf, hoja, word,
    html); sin ninguna pista, texto plano."""
    ext = dis._extension
    assert ext("informe", "application/pdf") == ".pdf"
    assert ext("informe", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") == ".xlsx"
    assert ext("informe", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") == ".docx"
    assert ext("informe", "text/html; charset=utf-8") == ".html"
    assert ext("informe", "text/plain") == ".txt"
    assert ext("informe", None) == ".txt"
    assert ext("nota.MD", None) == ".md"  # el sufijo manda y se normaliza
