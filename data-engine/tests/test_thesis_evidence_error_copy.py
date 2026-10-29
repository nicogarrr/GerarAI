"""El detalle de una fuente caida acaba en la tesis y en el memo.

Antes salia «Calendario inaccesible (RuntimeError).» o el texto crudo de la
excepcion (con la URL y su token). Ahora va un mensaje fijo en espanol y el
detalle (redactado) solo en el log del servidor.
"""

import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.thesis_evidence_service import ThesisEvidenceService

SECRET_URL = "https://ir.example.com/feed?apikey=SUPERSECRET123"
RAW = f"ConnectError: boom contacting {SECRET_URL}"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        ir_url=SECRET_URL,
    )
    db.add(company)
    db.commit()
    return company


def _boom(*_args, **_kwargs):
    raise RuntimeError(RAW)


def _texts(payload: dict) -> list[str]:
    return [str(v) for k, v in payload.items() if k in {"detail", "profile_detail", "action"}]


def _assert_clean(payload: dict) -> None:
    texts = _texts(payload)
    assert texts, payload
    for text in texts:
        assert "RuntimeError" not in text
        assert "SUPERSECRET123" not in text
        assert "boom" not in text
        assert "ir.example.com" not in text


def test_calendario_caido_no_ensena_la_clase_de_excepcion(db, caplog):
    company = _company(db)
    service = ThesisEvidenceService()
    service._fetch_earnings = _boom
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_evidence_service"):
        out = service._collect_earnings(db, company)
    assert out["status"] == "pending"
    _assert_clean(out)
    assert out["detail"] == "Calendario de resultados inaccesible ahora mismo."
    # El detalle queda en el log, sin el secreto.
    assert "boom" in caplog.text
    assert "SUPERSECRET123" not in caplog.text


def test_ir_caido_no_mete_url_ni_texto_crudo(db, caplog):
    company = _company(db)
    service = ThesisEvidenceService()
    service._fetch_ir = _boom
    with caplog.at_level(logging.WARNING, logger="app.services.thesis_evidence_service"):
        out = service._ingest_ir(db, company)
    assert out["status"] == "pending"
    _assert_clean(out)
    assert "boom" in caplog.text
    assert "SUPERSECRET123" not in caplog.text


def test_quote_y_perfil_caidos_mensaje_fijo(db):
    company = _company(db)
    service = ThesisEvidenceService()
    service._fetch_quote = _boom
    service._fetch_profile = _boom
    out = service._ingest_market(db, company)
    _assert_clean(out)
    assert out["profile_detail"] == "Perfil inaccesible ahora mismo."


def test_edgar_caido_mensaje_fijo(db):
    company = _company(db)
    service = ThesisEvidenceService()
    service._fetch_company_facts = _boom
    service._fetch_filings = _boom
    _assert_clean(service._ingest_fundamentals(db, company, "0000320193"))
    _assert_clean(service._ingest_filings(db, company, "0000320193"))
