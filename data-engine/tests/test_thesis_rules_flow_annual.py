"""Criterio de tesis sobre una metrica de flujo: dato anual, no trimestral.

El 10-Q del Q1 2026 tiene fiscal_year 2026, mas reciente que el 10-K de
2025, y ganaba el orden. «metrica:revenue < 200» comparaba los ingresos de un
trimestre (110) con un umbral anual y disparaba; los ingresos del ultimo año
son 400.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AlertRule
from app.models.entities import Base, Company, FinancialFact, ThesisVersion
from app.services.thesis_invalidation_rules import RULE_TYPE, observe


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="FLOW", name="FLOW", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Software", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, metric, value, period, year, quarter):
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
                         period=period, fiscal_year=year, fiscal_quarter=quarter))
    db.commit()


def _observe(db, company, metric):
    thesis = ThesisVersion(company_id=company.id, version=1, status="final", thesis_markdown="# T",
                           executive_summary="R", rating="watch")
    db.add(thesis)
    db.commit()
    rule = AlertRule(company_id=company.id, name="criterio", rule_type=RULE_TYPE,
                     target={"metric": f"metrica:{metric}", "thesis_version_id": thesis.id})
    return observe(db, rule)


def test_flow_metric_uses_the_last_annual_value_not_a_newer_quarter(db):
    company = _company(db)
    _fact(db, company, "revenue", "400", "2025-12-31:FY", 2025, "FY")
    _fact(db, company, "revenue", "110", "2026-03-31:Q1", 2026, "Q1")
    value, info = _observe(db, company, "revenue")
    assert value == Decimal("400")
    assert info["period"] == "2025-12-31:FY"


def test_quarter_only_flow_metric_is_not_read_as_annual(db):
    company = _company(db)
    _fact(db, company, "net_income", "30", "2026-03-31:Q1", 2026, None)
    value, info = _observe(db, company, "net_income")
    assert value is None
    assert info["status"] == "missing"


def test_balance_metric_still_reads_the_latest_quarter(db):
    company = _company(db)
    _fact(db, company, "cash_and_equivalents", "50", "2025-12-31:FY", 2025, "FY")
    _fact(db, company, "cash_and_equivalents", "70", "2026-03-31:Q1", 2026, "Q1")
    value, _info = _observe(db, company, "cash_and_equivalents")
    assert value == Decimal("70")
