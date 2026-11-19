"""Ramas 404 de los endpoints de /api/companies con ticker desconocido.

Cada endpoint resuelve primero la empresa en el master (resolve_company) y
falla cerrado con 404 si no existe, ANTES de tocar servicios o proveedores:
un ticker inventado nunca puede derivar en una llamada externa. Estas ramas
quedaron sin cobertura medida en la ronda del Auditor de 2026-11-19 (fichero
app/api/routes/companies.py por debajo del suelo de 85% en ramas).
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.companies import (
    company_changes_since,
    company_ttm,
    create_driver_assumption,
    create_inferred_input,
    financial_terminal,
    generate_long_term_model,
    get_company,
    list_calculated_metrics,
    list_driver_assumptions,
    list_financial_facts,
    list_inferred_inputs,
    long_term_model,
)
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.mark.parametrize(
    "endpoint",
    [
        get_company,
        list_financial_facts,
        financial_terminal,
        company_ttm,
        list_calculated_metrics,
        long_term_model,
        generate_long_term_model,
        list_driver_assumptions,
        list_inferred_inputs,
    ],
)
def test_ticker_desconocido_devuelve_404(db: Session, endpoint):
    with pytest.raises(HTTPException) as excinfo:
        endpoint("NOPE-NO-EXISTE", db=db)
    assert excinfo.value.status_code == 404


def test_changes_since_ticker_desconocido_devuelve_404(db: Session):
    with pytest.raises(HTTPException) as excinfo:
        company_changes_since(
            "NOPE-NO-EXISTE", since=datetime(2026, 1, 1, tzinfo=UTC), db=db
        )
    assert excinfo.value.status_code == 404


@pytest.mark.parametrize("endpoint", [create_driver_assumption, create_inferred_input])
def test_altas_ticker_desconocido_devuelven_404(db: Session, endpoint):
    # El payload no llega a validarse: el 404 salta antes, al resolver el ticker.
    with pytest.raises(HTTPException) as excinfo:
        endpoint("NOPE-NO-EXISTE", payload=None, db=db)
    assert excinfo.value.status_code == 404


def test_inferred_inputs_sin_tenant_devuelve_lista_vacia(db: Session):
    company = Company(
        ticker="TEN1", name="Tenant Uno", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.info.pop("tenant_id", None)
    assert list_inferred_inputs(company.ticker, db=db) == []
