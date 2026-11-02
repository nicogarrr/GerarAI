"""Los siete envoltorios privados de documento de fuente delegan en
get_or_create_source_document (app.services.source_documents).

Fija el contrato visible de cada envoltorio (título, tipo, URL, metadatos,
idempotencia) para que la extracción no mueva ni un byte de comportamiento:
los tests existentes (ESEF scrub, idempotencia de evidencia de tesis) ya
cubren dos; aquí el resto y la pieza común.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, Tenant
from app.services import class_filer_eps_service as class_filer
from app.services import edgartools_ingestion_service as edgartools
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.source_documents import get_or_create_source_document
from app.services.thesis_evidence_service import ThesisEvidenceService
from app.services.wacc_input_service import WaccInputService


@pytest.fixture(params=["sqlite:///:memory:"] + ([os.environ["CAVAAI_SOURCE_DOCUMENT_TEST_URL"]] if os.environ.get("CAVAAI_SOURCE_DOCUMENT_TEST_URL") else []))
def db(request):
    schema = f"source_doc_test_{uuid4().hex}"
    admin_engine = None
    if request.param.startswith("postgresql"):
        admin_engine = create_engine(request.param)
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(request.param, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(request.param)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        tenant = Tenant(external_id="source-document-test")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session
        session.rollback()
    Base.metadata.drop_all(engine)
    engine.dispose()
    if admin_engine is not None:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def _company(db, ticker="ITX"):
    company = Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="BME",
        currency="EUR",
        sector="S",
        industry="I",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _count(db, company):
    return db.scalar(select(func.count()).select_from(Document).where(Document.company_id == company.id))


def test_helper_get_or_create_es_idempotente(db):
    company = _company(db)
    first = get_or_create_source_document(
        db,
        company,
        title="t",
        source_type="SEC",
        source_url="https://sec.gov/x",
        metadata={"provider": "SEC"},
    )
    second = get_or_create_source_document(
        db,
        company,
        title="t",
        source_type="SEC",
        source_url="https://sec.gov/x",
        metadata={"provider": "SEC"},
    )
    assert first.id == second.id
    assert _count(db, company) == 1


def test_class_filer_conserva_titulo_url_y_metadata(db):
    company = _company(db)
    doc = class_filer._get_or_create_document(db, company, "https://sec.gov/instance")
    assert doc.title == "SEC XBRL instance (class facts) - ITX"
    assert doc.source_type == "SEC"
    assert doc.source_url == "https://sec.gov/instance"
    assert doc.metadata_ == {"provider": "SEC", "xbrl_instance": True}
    assert class_filer._get_or_create_document(db, company, "https://sec.gov/instance").id == doc.id
    assert _count(db, company) == 1


def test_edgartools_conserva_titulo_url_y_metadata(db):
    company = _company(db)
    doc = edgartools._source_document(db, company, "ITX")
    assert doc.title == "SEC XBRL facts (edgartools) - ITX"
    assert doc.source_url.endswith("type=10-K")
    assert doc.metadata_["pipeline"] == edgartools.PIPELINE
    assert doc.metadata_["normalized"] is True
    assert edgartools._source_document(db, company, "ITX").id == doc.id
    assert _count(db, company) == 1


def test_fmp_y_sec_de_financial_ingestion_conservan_contrato(db):
    company = _company(db)
    service = FinancialIngestionService()
    fmp = service._source_document(db, company)
    assert fmp.title == "FMP normalized financials - ITX"
    assert fmp.source_type == "FMP"
    assert fmp.source_url.endswith("/financial-summary/ITX")
    sec = service._source_document_sec(db, company, "ITX")
    assert sec.title == "SEC XBRL facts - ITX"
    assert sec.source_type == "SEC"
    assert service._source_document(db, company).id == fmp.id
    assert service._source_document_sec(db, company, "ITX").id == sec.id
    assert _count(db, company) == 2


def test_tesis_conserva_metadata_auto_ingested(db):
    company = _company(db)
    service = ThesisEvidenceService()
    doc = service._get_or_create_document(
        db, company, title="10-K 2025", source_type="SEC", source_url="https://sec.gov/x"
    )
    assert doc.metadata_ == {"provider": "SEC", "auto_ingested": True}
    assert (
        service._get_or_create_document(
            db, company, title="10-K 2025", source_type="SEC", source_url="https://sec.gov/x"
        ).id
        == doc.id
    )
    assert _count(db, company) == 1


def test_wacc_conserva_metadata_y_publicada(db):
    company = _company(db)
    service = WaccInputService()
    doc = service._source_document(db, company, source_type="damodaran", title="ERP", metadata={"k": 1})
    assert doc.metadata_ == {"k": 1}
    assert doc.published_at is not None
    assert (
        service._source_document(db, company, source_type="damodaran", title="ERP", metadata={"k": 1}).id
        == doc.id
    )
    assert _count(db, company) == 1


def test_reuse_preserves_existing_evidence_and_scrubs_only_when_requested(db):
    company = _company(db)
    doc = get_or_create_source_document(db, company, title="old", source_type="ESEF", source_url="https://filings.xbrl.org/api/filings (fxo_id=old)", metadata={"original": True})
    same = get_or_create_source_document(db, company, title="old", source_type="ESEF", source_url="https://example.com/replacement", metadata={"original": False})
    assert same.id == doc.id
    assert same.source_url == "https://filings.xbrl.org/api/filings (fxo_id=old)"
    assert same.metadata_ == {"original": True}
    same = get_or_create_source_document(db, company, title="old", source_type="ESEF", scrub_unlinkable_url=True)
    assert same.source_url is None
    assert same.metadata_ == {"original": True}


def test_same_source_document_is_scoped_to_active_tenant(db):
    company = _company(db)
    first = get_or_create_source_document(db, company, title="t", source_type="SEC")
    first_tenant = first.tenant_id
    other = Tenant(external_id="other-source-document-test")
    db.add(other)
    db.flush()
    db.info["tenant_id"] = other.id
    second = get_or_create_source_document(db, company, title="t", source_type="SEC")
    assert second.id != first.id
    assert second.tenant_id == other.id
    assert first.tenant_id == first_tenant
