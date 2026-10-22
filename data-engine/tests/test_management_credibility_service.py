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


# --- Procedencia verificable (0078) -----------------------------------------


def _claim(db, company, text):
    from app.models.entities import CallClaim, Transcript

    transcript = Transcript(
        company_id=company.id, title="Q4 call (sintetico)", period="Q4 2025",
        transcript_text=text,
    )
    db.add(transcript)
    db.commit()
    claim = CallClaim(
        transcript_id=transcript.id, speaker="Persona Sintetica", speaker_role="CFO",
        claim=text, claim_type="commitment", period="FY2025",
    )
    db.add(claim)
    db.commit()
    return claim


def test_import_does_not_turn_a_year_into_a_numeric_target(db):
    """«25 satelites en 2025»: la heuristica tomaba un numero del texto como
    objetivo y la conciliacion lo daba por promesa numerica autenticada."""
    company = _company(db)
    _claim(db, company, "In 2025 we will have 25 satellites in orbit")
    rows = ManagementCredibilityService().import_call_claims(db, company)
    assert len(rows) == 1
    row = rows[0]
    assert row.operator is None and row.target_value is None
    assert row.metadata_["suggested_target_unverified"] is not None  # sugerencia, no dato
    assert row.status == "open"


def test_import_marks_date_basis_registered_not_call_date(db):
    company = _company(db)
    _claim(db, company, "We expect to launch the new product by year end")
    row = ManagementCredibilityService().import_call_claims(db, company)[0]
    assert row.date_basis == "registered_at"
    assert row.call_date is None
    assert row.quote_literal == "We expect to launch the new product by year end"
    assert row.speaker == "Persona Sintetica" and row.speaker_role == "CFO"


def test_register_records_provenance_and_date_basis(db):
    company = _company(db)
    svc = ManagementCredibilityService()
    row = svc.register(
        db, company, promise="Ampliar la oferta antes de fin de ano",
        promise_date=date(2026, 5, 11), expected_period="FY2026", metric=None,
        operator=None, target_value=None, unit=None,
        quote_literal="[...] into more complex offerings", speaker="X", speaker_role="CFO",
        call_date=date(2026, 5, 11), source_url="https://example.invalid/t.pdf",
        transcript_locator="27:04", due_date=date(2026, 12, 31),
        fulfillment_criteria="Oferta disponible al publico",
    )
    payload = ManagementCredibilityService.payload(row)
    assert payload["date_basis"] == "call_date"
    assert payload["due_date"] == date(2026, 12, 31)
    assert payload["fulfillment_criteria"] == "Oferta disponible al publico"
    other = svc.register(
        db, company, promise="Otra", promise_date=date(2026, 5, 12), expected_period="FY2026",
        metric=None, operator=None, target_value=None, unit=None,
    )
    assert other.date_basis == "user_entered" and other.quote_literal is None
