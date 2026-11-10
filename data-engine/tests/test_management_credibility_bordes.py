"""Bordes de management_credibility_service: import_call_claims (creacion y
dedup), reconcile con promesa sin metrica y con periodo sin ano, y el parser
estatico _target (sin numero y cada familia de cualificador).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CallClaim,
    Company,
    FinancialFact,
    ManagementPromise,
    Transcript,
)
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
        ticker="MCO",
        name="MCO",
        exchange="NYSE",
        currency="USD",
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


def _claims(db: Session, company: Company) -> None:
    transcript = Transcript(company_id=company.id, title="Q4 call", period="Q4 2025")
    db.add(transcript)
    db.flush()
    db.add_all(
        [
            CallClaim(
                transcript_id=transcript.id,
                speaker="CEO",
                speaker_role="ceo",
                claim="Revenue at least €200 in FY2026",
                claim_type="guidance",
                metric="revenue",
                period="FY2026",
            ),
            CallClaim(
                transcript_id=transcript.id,
                speaker="CFO",
                speaker_role="cfo",
                claim="Margin up to 15.5 in FY2026",
                claim_type="commitment",
                metric="margin",
                period="FY2026",
            ),
            CallClaim(
                transcript_id=transcript.id,
                speaker="CEO",
                speaker_role="ceo",
                claim="Hola sin categoria",
                claim_type="other",
                metric=None,
                period=None,
            ),
        ]
    )
    db.commit()


def test_import_call_claims_crea_promesas_solo_de_tipos_objetivo(db):
    company = _company(db)
    _claims(db, company)
    created = ManagementCredibilityService().import_call_claims(db, company)
    assert len(created) == 2
    by_metric = {row.metric: row for row in created}
    assert by_metric["revenue"].operator == ">="
    assert by_metric["revenue"].target_value == Decimal("200")
    assert by_metric["margin"].operator == "<="
    assert by_metric["margin"].target_value == Decimal("15.5")
    for row in created:
        assert row.status == "open"
        assert row.evidence[0]["speaker"] in {"CEO", "CFO"}
        assert row.metadata_["source"] == "call_claim"


def test_import_call_claims_no_duplica_en_segunda_pasada(db):
    company = _company(db)
    _claims(db, company)
    service = ManagementCredibilityService()
    first = service.import_call_claims(db, company)
    second = service.import_call_claims(db, company)
    assert [row.id for row in second] == [row.id for row in first]
    assert db.query(ManagementPromise).filter_by(company_id=company.id).count() == 2


def test_reconcile_salta_promesas_sin_metrica(db):
    company = _company(db)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Algo sin metrica",
        promise_date=date(2024, 2, 1),
        expected_period="FY2025",
        metric=None,
        operator=None,
        target_value=None,
        unit=None,
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "open"
    assert promise.actual_fact_id is None


def test_reconcile_periodo_sin_ano_casa_por_periodo_exacto(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("120"),
        unit="USD",
        period="T3",
        fiscal_year=None,
        fiscal_quarter="Q3",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue >= 100 en T3",
        promise_date=date(2024, 2, 1),
        expected_period="T3",
        metric="revenue",
        operator=">=",
        target_value=Decimal("100"),
        unit="USD",
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "met"
    assert promise.actual_value == Decimal("120")


def test_target_sin_numero_devuelve_none():
    assert ManagementCredibilityService._target("sin cifras aqui") == (None, None)


@pytest.mark.parametrize(
    ("text", "operator", "target"),
    [
        ("Revenue at least $200", ">=", "200"),
        ("margin up to 15.5", "<=", "15.5"),
        ("growth of about 10", "==", "10"),
        ("revenue 300", "==", "300"),
    ],
)
def test_target_operadores_segun_cualificador(text, operator, target):
    assert ManagementCredibilityService._target(text) == (operator, Decimal(target))


def test_reconcile_periodo_solo_ano_sin_fy_ni_trimestre(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("120"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue >= 100 en 2025",
        promise_date=date(2024, 2, 1),
        expected_period="2025",
        metric="revenue",
        operator=">=",
        target_value=Decimal("100"),
        unit="USD",
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "met"
    assert promise.actual_value == Decimal("120")
