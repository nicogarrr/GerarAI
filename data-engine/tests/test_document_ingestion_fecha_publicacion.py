"""Fecha de publicacion desconocida en la ingesta de documentos.

Doctrina: un sello de la peticion nunca es un sello del dato. Si la fuente
no declara fecha de publicacion, ``Document.published_at`` y el
``published_on`` del contrato de evidencia quedan en None: estampar
``now()`` convertia la fecha de subida en fecha de publicacion y los
contextos de expertos (recopilador, sotp_valuer, analyst_blend, thesis)
presentaban ese invento como ``date`` del documento. La columna es
nullable y todos los consumidores ya toleran None (orden ``nullslast``,
``else ""``/``else None``).

NO prueba (declarado): ``NewsEvent.date`` (news_service) tiene la misma
forma de fallback pero la columna es NOT NULL con default utcnow: dejarla
en None exige migracion de esquema y queda fuera de este cambio.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.services.document_ingestion_service as dis
from app.models.entities import Base, Company, Document
from app.services.document_ingestion_service import DocumentIngestionService

TENANT = 1  # int >= 1: el contrato de evidencia exige tenant ligado
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

    class _Store:
        def put_bytes(self, ticker, source_type, name, content, *,
                      tenant_id=None, content_type=None):
            return f"mem://{ticker}/{source_type}/{name}"

    monkeypatch.setattr(dis, "DocumentStore", _Store)


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


def _ingesta(db: Session, **kwargs):
    params = dict(
        ticker="AAPL", title="Documento de prueba", content=TEXTO,
        filename="nota.txt", source_type="test_upload",
    )
    params.update(kwargs)
    return DocumentIngestionService().ingest_bytes(db, **params)


def test_sin_fecha_declarada_published_at_queda_none(db):
    """Subida manual sin fecha: la fila conserva None en vez de now()."""
    _empresa(db)
    resultado = _ingesta(db)
    assert resultado["status"] == "ingested"
    documento = db.get(Document, resultado["document_id"])
    assert documento.published_at is None


def test_sin_fecha_declarada_evidencia_publicada_on_none(db):
    """El contrato de evidencia tampoco fabrica fecha: published_on None."""
    _empresa(db)
    resultado = _ingesta(db)
    documento = db.get(Document, resultado["document_id"])
    evidencia = documento.metadata_["evidence_contract"]
    assert evidencia["published_on"] is None


def test_con_fecha_declarada_se_conserva(db):
    """Con fecha real de la fuente, la fila y la evidencia la conservan."""
    _empresa(db)
    fecha = datetime(2025, 3, 29, 12, 0, tzinfo=UTC)
    resultado = _ingesta(db, published_at=fecha)
    documento = db.get(Document, resultado["document_id"])
    # SQLite devuelve la fecha sin tzinfo: compara el instante sin zona.
    assert documento.published_at is not None
    assert documento.published_at.replace(tzinfo=None) == fecha.replace(tzinfo=None)
    evidencia = documento.metadata_["evidence_contract"]
    assert evidencia["published_on"] == "2025-03-29"


def test_ficha_stub_sin_fecha_no_hereda_fecha_fabricada(db):
    """Un stub sin fecha completado por la ingesta real sigue sin fecha."""
    company = _empresa(db)
    stub = Document(
        company_id=company.id, title="Ficha 10-K", source_type="filing_evidence",
        source_url=SEC_URL, metadata_={"form": "10-K"}, tenant_id=TENANT,
    )
    db.add(stub)
    db.commit()
    stub_id = stub.id

    resultado = _ingesta(db, source_url=SEC_URL, source_type="filing_evidence")
    assert resultado["document_id"] == stub_id
    documento = db.get(Document, stub_id)
    assert documento.published_at is None


def test_fila_no_tiene_otra_fecha_fabricada_en_metadata(db):
    """Ningun campo de metadata suplanta la fecha de publicacion ausente."""
    _empresa(db)
    resultado = _ingesta(db)
    documento = db.get(Document, resultado["document_id"])
    assert "report_date" not in documento.metadata_
    assert "period_of_report" not in documento.metadata_
