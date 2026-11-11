"""Informe: un EBITDA «—» dice por qué (r5-front2).

Antes ``estimates.*[].ebitda`` era ``None`` a secas: BX, TSM o un emisor IFRS sin D&A salían con «—» en
todos los años y nada explicaba si faltaba el resultado operativo, las amortizaciones o si no aplica
(bancos y aseguradoras). Ahora cada periodo trae ``ebitda_reason`` cuando no hay cifra.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services.analyst_report import build_company_report

M = 1_000_000
END = "2025-12-31"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, *, industry="I", sector="S"):
    company = Company(
        ticker="X", name="X", exchange="NYSE", currency="USD", sector=sector, industry=industry,
        company_type="quality", valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, metric, value, *, unit="USD", period=END):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit, period=f"{period}:FY",
        fiscal_year=int(period[:4]), fiscal_quarter="FY", source_type="SEC", is_reported=True,
    ))


def _annual(db, company):
    db.commit()
    return build_company_report(db, company, today=date(2026, 3, 1))["estimates"]["annual"]


def test_sin_amortizaciones(db):
    company = _company(db)
    _fact(db, company, "revenue", 100 * M)
    _fact(db, company, "operating_income", 20 * M)
    row = _annual(db, company)[0]
    assert row["ebitda"] is None
    assert row["ebitda_reason"] == "missing_da"


def test_sin_resultado_operativo_ni_componentes_ifrs(db):
    company = _company(db)
    _fact(db, company, "revenue", 100 * M)
    _fact(db, company, "depreciation_amortization", 5 * M)
    row = _annual(db, company)[0]
    assert row["ebitda"] is None
    assert row["ebitda_reason"] == "missing_operating_income"


def test_sin_resultado_operativo_ni_amortizaciones(db):
    company = _company(db)
    _fact(db, company, "revenue", 100 * M)
    row = _annual(db, company)[0]
    assert row["ebitda"] is None
    assert row["ebitda_reason"] == "missing_operating_income_and_da"


def test_unidades_distintas(db):
    company = _company(db)
    _fact(db, company, "revenue", 100 * M)
    _fact(db, company, "operating_income", 20 * M)
    _fact(db, company, "depreciation_amortization", 5 * M, unit="EUR")
    row = _annual(db, company)[0]
    assert row["ebitda"] is None
    assert row["ebitda_reason"] == "unit_mismatch"


def test_bancos_y_aseguradoras_no_aplica(db):
    company = _company(db, industry="Banks - Regional", sector="Financial Services")
    _fact(db, company, "revenue", 100 * M)
    _fact(db, company, "depreciation_amortization", 5 * M)
    row = _annual(db, company)[0]
    assert row["ebitda"] is None
    assert row["ebitda_reason"] == "financial_issuer"


def test_con_cifra_no_hay_motivo(db):
    company = _company(db)
    _fact(db, company, "revenue", 100 * M)
    _fact(db, company, "operating_income", 20 * M)
    _fact(db, company, "depreciation_amortization", 5 * M)
    row = _annual(db, company)[0]
    assert row["ebitda"]["value"] == 25 * M
    assert row["ebitda_reason"] is None
