"""ManagementCredibilityService reconciliation contracts.

A credibility score is only meaningful if promise matching is strict: an
annual promise must never be reconciled against a quarterly observation,
"partial" means genuinely close (within 5%), and unmatched promises stay
honestly open.
"""

from datetime import date
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


def _fact(db, company, value, year=2025, quarter="FY", metric="revenue"):
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="USD", period=f"{quarter} {year}" if quarter != "FY" else f"FY{year}",
        fiscal_year=year, fiscal_quarter=None if quarter == "FY" else quarter,
        source_type="filing",
    )
    db.add(fact)
    db.commit()
    return fact


def _promise(db, company, *, period="FY2025", operator=">=", target="100"):
    return ManagementCredibilityService().register(
        db, company,
        promise=f"Revenue {operator} {target} in {period}",
        promise_date=date(2024, 2, 1), expected_period=period,
        metric="revenue", operator=operator,
        target_value=Decimal(target), unit="USD",
    )


def test_met_when_operator_satisfied(db):
    c = _company(db)
    _fact(db, c, 120)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "met"
    assert p.actual_value == Decimal("120")


def test_missed_when_clearly_below_target(db):
    c = _company(db)
    _fact(db, c, 80)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "missed"


def test_partial_within_five_percent_only(db):
    c = _company(db)
    _fact(db, c, 97)  # 3% below target
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "partial"


def test_just_outside_five_percent_is_missed(db):
    c = _company(db)
    _fact(db, c, 94)  # 6% below target
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "missed"


def test_annual_promise_ignores_quarterly_fact(db):
    c = _company(db)
    _fact(db, c, 130, quarter="Q3")  # same fiscal year, but quarterly
    _promise(db, c, period="FY2025")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_quarterly_promise_matches_quarterly_fact(db):
    c = _company(db)
    _fact(db, c, 130, quarter="Q2")
    _promise(db, c, period="Q2 2025")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "met"


def test_quarterly_promise_matches_ten_q_fact_with_null_fiscal_year(db):
    """Hechos de la ingesta 10-Q: fiscal_year NULL, period '<end>:Qn'."""
    c = _company(db)
    fact = FinancialFact(
        company_id=c.id, metric="revenue", value=Decimal("130"),
        unit="USD", period="2025-06-30:Q2",
        fiscal_year=None, fiscal_quarter="Q2",
        source_type="filing",
    )
    db.add(fact)
    db.commit()
    _promise(db, c, period="2025 Q2")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "met"
    assert p.actual_fact_id == fact.id


def test_quarterly_promise_ignores_null_fiscal_year_fact_from_other_year(db):
    c = _company(db)
    fact = FinancialFact(
        company_id=c.id, metric="revenue", value=Decimal("130"),
        unit="USD", period="2024-06-30:Q2",
        fiscal_year=None, fiscal_quarter="Q2",
        source_type="filing",
    )
    db.add(fact)
    db.commit()
    _promise(db, c, period="2025 Q2")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_unmatched_promise_stays_open(db):
    c = _company(db)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_value is None


def test_numeric_promise_requires_supported_operator(db):
    c = _company(db)
    with pytest.raises(ValueError):
        _promise(db, c, operator="~=")


def test_promise_without_target_records_outcome(db):
    c = _company(db)
    _fact(db, c, 110)
    ManagementCredibilityService().register(
        db, c, promise="Revenue will grow in FY2025",
        promise_date=date(2024, 2, 1), expected_period="FY2025",
        metric="revenue", operator=None, target_value=None, unit=None,
    )
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "outcome_recorded"
    assert p.actual_value == Decimal("110")


def _document(db: Session, company_id: int | None) -> int:
    from app.models.entities import Document

    doc = Document(company_id=company_id, title="10-K", source_type="filing")
    db.add(doc)
    db.commit()
    return doc.id


def _register_with_doc(db: Session, company: Company, document_id: int):
    return ManagementCredibilityService().register(
        db, company, promise="Revenue above 100", promise_date=date(2025, 1, 10),
        expected_period="FY2025", metric="revenue", operator=">=",
        target_value=Decimal("100"), unit="USD", source_document_id=document_id,
    )


def test_promesa_con_documento_inexistente_se_rechaza(db):
    """Sin comprobar, en Postgres la FK rompía con IntegrityError (500)."""
    company = _company(db)
    with pytest.raises(ValueError):
        _register_with_doc(db, company, 999_999)


def test_promesa_con_documento_de_otro_usuario_o_empresa_se_rechaza(db):
    company = _company(db)
    other = Company(
        ticker="OTR", name="OTR", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(other)
    db.commit()
    other_company_doc = _document(db, other.id)
    with pytest.raises(ValueError):
        _register_with_doc(db, company, other_company_doc)

    db.info["tenant_id"] = "otro-tenant"
    foreign_doc = _document(db, company.id)
    db.info["tenant_id"] = "tenant-test"
    with pytest.raises(ValueError):
        _register_with_doc(db, company, foreign_doc)


def test_promesa_con_documento_propio_entra(db):
    company = _company(db)
    own = _document(db, company.id)
    general = _document(db, None)
    assert _register_with_doc(db, company, own).source_document_id == own
    assert _register_with_doc(db, company, general).source_document_id == general
