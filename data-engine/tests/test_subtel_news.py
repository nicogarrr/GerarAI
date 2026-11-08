"""Evidencia regulatoria SUBTEL (ASTS): persistencia aislada por tenant.

La ingesta guarda decretos oficiales como NewsEvent de baja materialidad, sin
alertas, y NO duplica por URL del PDF. Sin contexto de tenant debe fallar
(fail-closed), y sin la empresa ASTS en la base no inserta nada.
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent, Tenant
from app.services.subtel_news import persist_decrees

FETCHED = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def decree(number="123", url="https://subtel.gob.cl/decreto-123.pdf", date="2026-11-03"):
    return {"pdf_url": url, "decree_date": date, "decree_number": number, "request_number": "REQ-1"}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="t1", name="workspace")
        session.add(tenant)
        session.commit()
        session.info["tenant_id"] = tenant.id
        yield session


def _asts(db) -> Company:
    company = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
                      sector="Telecom", industry="Satellite", company_type="pre_revenue",
                      valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    return company


def test_sin_contexto_de_tenant_falla():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(RuntimeError):
            persist_decrees(session, [decree()], FETCHED)


def test_sin_asts_no_inserta_nada(db):
    assert persist_decrees(db, [decree()], FETCHED) == 0
    assert db.scalars(select(NewsEvent)).all() == []


def test_inserta_el_decreto_como_evidencia_regulatoria_sin_alertas(db):
    company = _asts(db)
    assert persist_decrees(db, [decree()], FETCHED) == 1
    row = db.scalar(select(NewsEvent))
    assert row.company_id == company.id
    assert row.tenant_id == db.info["tenant_id"]
    assert row.source == "SUBTEL (oficial)"
    assert row.event_type == "regulatory"
    assert "decreto 123" in row.title
    # SQLite devuelve DateTime naive: se compara el instante, no el tzinfo.
    assert row.date.replace(tzinfo=UTC) == datetime(2026, 11, 3, tzinfo=UTC)
    assert row.materiality_score == 5
    assert row.impact_direction == "neutral"
    assert row.affected_thesis is False
    assert row.metadata_["no_new_alerts"] is True
    assert row.metadata_["regulatory_evidence"]["decree_number"] == "123"


def test_no_duplica_por_url_del_pdf(db):
    _asts(db)
    assert persist_decrees(db, [decree()], FETCHED) == 1
    # Mismo PDF aunque cambien otros campos: ya está, no se repite.
    assert persist_decrees(db, [decree(number="123", date="2026-11-04")], FETCHED) == 0
    assert len(db.scalars(select(NewsEvent)).all()) == 1


def test_decretos_distintos_se_insertan_todos(db):
    _asts(db)
    dos = [decree(), decree(number="456", url="https://subtel.gob.cl/decreto-456.pdf")]
    assert persist_decrees(db, dos, FETCHED) == 2
