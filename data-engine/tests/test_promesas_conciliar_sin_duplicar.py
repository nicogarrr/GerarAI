"""Promesas de la dirección: pulsar «Conciliar» otra vez no repite la evidencia.

Antes cada conciliación añadía de nuevo el mismo dato financiero a la lista de
evidencias de cada promesa ya conciliada (tres pulsaciones = tres copias)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.management_credibility_service import ManagementCredibilityService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="MCO", name="MCO", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, value, created_at=None):
    fact = FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal(str(value)),
        unit="USD", period="FY2025", fiscal_year=2025, fiscal_quarter=None,
        source_type="filing",
    )
    if created_at is not None:
        fact.created_at = created_at
    db.add(fact)
    db.commit()
    return fact


def _promise(db, company):
    return ManagementCredibilityService().register(
        db, company, promise="Revenue >= 100 in FY2025",
        promise_date=date(2024, 2, 1), expected_period="FY2025",
        metric="revenue", operator=">=", target_value=Decimal("100"), unit="USD",
    )


def _fact_ids(promise):
    return [e.get("financial_fact_id") for e in promise.evidence or [] if "financial_fact_id" in e]


def test_conciliar_dos_veces_no_duplica_la_evidencia(db):
    c = _company(db)
    fact = _fact(db, c, 120)
    _promise(db, c)
    service = ManagementCredibilityService()
    for _ in range(3):
        [p] = service.reconcile(db, c)
    assert p.status == "met"
    assert _fact_ids(p) == [fact.id]


def test_un_dato_nuevo_si_se_anade(db):
    c = _company(db)
    first = _fact(db, c, 120)
    _promise(db, c)
    service = ManagementCredibilityService()
    service.reconcile(db, c)
    # Un 10-K/A corrige la cifra: es otra evidencia y cambia el veredicto.
    second = _fact(db, c, 80, created_at=first.created_at + timedelta(days=30))
    [p] = service.reconcile(db, c)
    assert p.status == "missed"
    assert _fact_ids(p) == [first.id, second.id]
    [p] = service.reconcile(db, c)
    assert _fact_ids(p) == [first.id, second.id]
