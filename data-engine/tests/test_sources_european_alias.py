"""F313: alias europeo (SAN.MC -> SAN) en sources y alerts.

Los endpoints filtraban Company.ticker == ticker.upper() literal mientras
/api/companies/{ticker} y /api/alerts/rules resuelven el alias: la pestaña
de documentos, su recuento, las auditorías y las alertas quedaban vacías
(o 404) para la misma entidad. Todos usan resolve_company ahora.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, ResearchAlert, SourceAudit, ThesisVersion


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _san_base(db: Session) -> Company:
    """SAN registrado solo como base, sin el exacto SAN.MC."""
    company = Company(
        ticker="SAN", name="Banco Santander", exchange="BME", currency="EUR",
        sector="Finanzas", industry="Banca", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_documents_resolves_european_alias(db: Session):
    from app.api.routes.sources import documents, documents_count

    company = _san_base(db)
    db.add(Document(company_id=company.id, title="10-K", source_type="sec"))
    db.commit()

    rows = documents(ticker="SAN.MC", scope="all", include_chunks=False, page=1, page_size=50,
                     chunk_limit=1000, chunk_text_limit=1500, db=db)
    assert rows != []
    assert documents_count(ticker="SAN.MC", scope="all", db=db)["total"] == 1
    # Ticker realmente desconocido: vacío, nunca un error.
    assert documents(ticker="ZZZZ.MC", scope="all", include_chunks=False, page=1, page_size=50,
                     chunk_limit=1000, chunk_text_limit=1500, db=db) == []
    assert documents_count(ticker="ZZZZ.MC", scope="all", db=db)["total"] == 0


def test_audits_resolves_european_alias(db: Session):
    from app.api.routes.sources import source_audits

    company = _san_base(db)
    thesis = ThesisVersion(company_id=company.id, version=1, status="published",
                           thesis_markdown="# T", executive_summary="r")
    db.add(thesis)
    db.commit()
    db.add(SourceAudit(thesis_version_id=thesis.id, passed=True))
    db.commit()

    audits = source_audits(ticker="SAN.MC", limit=100, offset=0, db=db)
    assert len(audits) == 1
    assert source_audits(ticker="ZZZZ.MC", limit=100, offset=0, db=db) == []


def test_alerts_resolves_european_alias(db: Session):
    from app.api.routes.alerts import list_alerts

    company = _san_base(db)
    db.add(ResearchAlert(company_id=company.id, status="open", alert_type="drift", title="a", message="m", fingerprint=f"fp-{company.id}"))
    db.commit()

    alerts = list_alerts(ticker="SAN.MC", status=None, include_snoozed=False, limit=100, db=db)
    assert len(alerts) == 1

    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        list_alerts(ticker="ZZZZ.MC", status=None, include_snoozed=False, limit=100, db=db)
