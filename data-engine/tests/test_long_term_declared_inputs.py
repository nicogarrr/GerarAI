"""Los inputs declarados (estimados de analista) llegan al modelo de drivers.

No hay nada por ticker: una empresa con marco ``software_ai`` y sin ARR recibe
el ARR declarado por una firma, validado y con fuente, y la fórmula operativa
lo usa. Un hecho reportado de la misma clave nunca se sustituye.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import DeclaredInputValue, Tenant
from app.models.entities import Base, Company, FinancialFact
from app.services.company_framework import resolve_company_framework
from app.services.declared_input_service import DeclaredInput, DeclaredInputService
from app.services.driver_operating_model import DriverOperatingModel
from app.services.long_term_model_service import LongTermModelService

T1 = 1
URL = "https://research.example.com/company/arr"
QUOTE = "We model FY2027 ARR of USD 1.0bn."


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=T1, external_id="t1"))
        session.flush()
        session.info["tenant_id"] = T1
        yield session


def _company(db: Session, ticker: str = "SYNTH") -> Company:
    company = Company(
        ticker=ticker,
        name="Synthetic Software",
        exchange="NASDAQ",
        currency="USD",
        sector="Technology",
        industry="Data analytics software",
        company_type="software_ai_platform",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=["software", "ai"],
    )
    db.add(company)
    db.flush()
    return company


def _declare_arr(db: Session, company: Company, value: Decimal = Decimal("1000")) -> None:
    service = DeclaredInputService()
    outcome = service.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=DeclaredInput(
            input_key="arr",
            base=value,
            unit="USD",
            method="analyst",
            analyst_firm="Firma de prueba",
            source_url=URL,
            source_quote=QUOTE,
            as_of=date(2026, 11, 1),
        ),
    )
    assert outcome.changed is True


def test_declared_analyst_input_reaches_the_driver_formula(db: Session) -> None:
    company = _company(db)
    _declare_arr(db, company)
    framework = resolve_company_framework(company)
    assert framework.key == "software_ai"
    fact_cache: dict[str, list] = {}
    declared = LongTermModelService()._apply_declared_inputs(db, company, framework, fact_cache)
    assert declared
    assert declared[0]["input_key"] == "arr"
    assert declared[0]["method"] == "analyst"
    assert declared[0]["analyst_firm"] == "Firma de prueba"
    assert fact_cache["arr"]
    result = DriverOperatingModel().build(
        framework,
        fact_cache,
        latest_year=2026,
        horizon=1,
        scenario="base",
    )
    assert result["status"] != "missing_formula_inputs"
    assert result["years"][0]["output"] == pytest.approx(1000.0)


def test_reported_fact_is_never_replaced_by_a_declared_input(db: Session) -> None:
    company = _company(db)
    _declare_arr(db, company)
    reported = FinancialFact(
        tenant_id=T1,
        company_id=company.id,
        metric="arr",
        value=Decimal("2500"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="SEC",
        is_reported=True,
        confidence=Decimal("0.9"),
    )
    db.add(reported)
    db.flush()
    framework = resolve_company_framework(company)
    fact_cache = {"arr": [reported]}
    declared = LongTermModelService()._apply_declared_inputs(db, company, framework, fact_cache)
    assert declared == []
    assert fact_cache["arr"] == [reported]


def test_declared_row_without_valid_source_is_ignored(db: Session) -> None:
    company = _company(db)
    db.add(
        DeclaredInputValue(
            tenant_id=T1,
            company_id=company.id,
            input_key="arr",
            segment_key="",
            base=Decimal("1000"),
            unit="USD",
            status="estimado",
            method="analyst",
            source_url=None,
            source_quote=None,
            analyst_firm=None,
        )
    )
    db.flush()
    framework = resolve_company_framework(company)
    fact_cache: dict[str, list] = {}
    assert LongTermModelService()._apply_declared_inputs(db, company, framework, fact_cache) == []
    assert "arr" not in fact_cache
