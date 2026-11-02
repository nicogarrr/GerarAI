"""Cita de la tesis en el asistente de la ficha: fecha en el día de Madrid."""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Tenant, ThesisVersion
from app.services.research_assistant_service import _thesis_citations


def _as_of(created_at: datetime) -> str:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="ra-date", name="A", status="active", metadata_={})
        company = Company(
            ticker="RAD", name="Rad", exchange="NYSE", currency="USD", sector="Tech",
            industry="Tech", company_type="standard", valuation_model="standard_dcf",
        )
        db.add_all([tenant, company])
        db.flush()
        db.info["tenant_id"] = tenant.id
        db.add(ThesisVersion(
            company_id=company.id, version=1, status="draft", thesis_markdown="# Tesis",
            executive_summary="Resumen.", rating="buy", tenant_id=tenant.id, created_at=created_at,
        ))
        db.commit()
        citations = _thesis_citations(db, company, tenant.id)
    engine.dispose()
    return citations[0]["as_of"]


def test_late_utc_evening_is_next_madrid_day():
    # 23:30 UTC del 9 de marzo = 00:30 del 10 en Madrid.
    assert _as_of(datetime(2026, 3, 9, 23, 30)) == "2026-03-10"


def test_midday_unchanged():
    assert _as_of(datetime(2026, 3, 9, 12, 0)) == "2026-03-09"
