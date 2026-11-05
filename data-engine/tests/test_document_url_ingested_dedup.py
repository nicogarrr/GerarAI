"""_document_url_ingested: dedup de encolado por URL (regresion F821).

La funcion llego a main sin el import local de ``select`` (NameError en
cada llamada del encolado horario de refresh_ir_pages). Test directo con
sqlite: cubre hit y miss por tenant.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, Document
from app.workers.dramatiq_app import _document_url_ingested

URL = "https://krakenrobotics.com/news-releases/comunicado-1"


def _session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="KRKNF", name="Kraken Robotics", exchange="TSXV", currency="CAD",
        sector="Tech", industry="Robotics", cik=None, company_type="operating",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    session.add(Document(
        company_id=company.id, title="Comunicado 1", source_type="ir_news",
        source_url=URL, metadata_={}, tenant_id="tenant-test",
    ))
    session.commit()
    return session


def test_url_ya_ingerida_del_tenant_es_dedup():
    assert _document_url_ingested(_session(), URL) is True


def test_url_desconocida_no_es_dedup():
    assert _document_url_ingested(_session(), "https://otra.example.com/nueva") is False


def test_url_de_otro_tenant_no_es_dedup():
    db = _session()
    db.info["tenant_id"] = "otro-tenant"
    assert _document_url_ingested(db, URL) is False
