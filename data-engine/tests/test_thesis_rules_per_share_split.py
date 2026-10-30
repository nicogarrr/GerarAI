"""Criterio de tesis sobre BPA: el dato anual de antes de un split se reexpresa.

10-K de 2024 (cerrado 2024-12-31, publicado 2025-02-15): BPA diluido 10,00.
Split 10:1 efectivo el 2025-06-10. Hoy el BPA comparable es 10,00 / 10 = 1,00.
Sin ajuste «metrica:eps_diluted < 2» leia 10,00 y no saltaba nunca; con un
umbral «> 5» saltaba sin motivo. Las acciones van al reves: 100 x 10 = 1000.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AlertRule
from app.models.entities import (
    Base,
    CalculatedMetric,
    Company,
    CorporateAction,
    FinancialFact,
    ThesisVersion,
)
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
        ticker="SPLT", name="SPLT", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Software", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _split(db, company, day, ratio):
    db.add(CorporateAction(company_id=company.id, action_type="split", effective_date=day,
                           ratio=Decimal(ratio)))
    db.commit()


def _fact(db, company, metric, value, filed):
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
                         period="2024-12-31:FY", fiscal_year=2024, fiscal_quarter="FY",
                         filed=filed))
    db.commit()


def _observe(db, company, metric):
    thesis = ThesisVersion(company_id=company.id, version=1, status="final", thesis_markdown="# T",
                           executive_summary="R", rating="watch")
    db.add(thesis)
    db.commit()
    rule = AlertRule(company_id=company.id, name="criterio", rule_type=RULE_TYPE,
                     target={"metric": f"metrica:{metric}", "thesis_version_id": thesis.id})
    return observe(db, rule)


def test_annual_eps_before_a_split_is_restated_to_todays_basis(db):
    company = _company(db)
    _fact(db, company, "eps_diluted", "10", date(2025, 2, 15))
    _split(db, company, date(2025, 6, 10), "10")
    value, info = _observe(db, company, "eps_diluted")
    assert value == Decimal("1")
    assert info["period"] == "2024-12-31:FY"


def test_share_count_before_a_split_is_multiplied(db):
    company = _company(db)
    _fact(db, company, "shares_diluted", "100", date(2025, 2, 15))
    _split(db, company, date(2025, 6, 10), "10")
    value, _info = _observe(db, company, "shares_diluted")
    assert value == Decimal("1000")


def test_eps_filed_after_the_split_is_already_restated(db):
    company = _company(db)
    _split(db, company, date(2025, 1, 20), "10")
    _fact(db, company, "eps_diluted", "1", date(2025, 2, 15))
    value, _info = _observe(db, company, "eps_diluted")
    assert value == Decimal("1")


def test_non_per_share_metric_is_untouched(db):
    company = _company(db)
    _fact(db, company, "revenue", "400", date(2025, 2, 15))
    _split(db, company, date(2025, 6, 10), "10")
    value, _info = _observe(db, company, "revenue")
    assert value == Decimal("400")


def test_calculated_per_share_across_a_split_is_nd(db):
    company = _company(db)
    db.add(CalculatedMetric(company_id=company.id, metric="fcf_per_share", value=Decimal("8"),
                            unit="USD", period="2024-12-31:FY", fiscal_year=2024,
                            formula="fcf / shares"))
    db.commit()
    _split(db, company, date(2025, 6, 10), "10")
    value, info = _observe(db, company, "fcf_per_share")
    assert value is None
    assert info["missing"] == "split_posterior_al_periodo"
