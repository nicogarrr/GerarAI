"""Tests de /api/companies driver-assumptions y financial-terminal (app/api/routes/companies.py).

Endpoints sin cobertura previa: creacion/listado de supuestos por driver con
encadenado de versiones y 409 si el driver no existe, y el terminal financiero
(ventana de años, cobertura de métricas). Se ejercitan las funciones de ruta
contra SQLite en memoria; el modelo a largo plazo se sustituye porque aquí lo
que se prueba es el cableado del endpoint, no el motor de valoración.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.routes.companies as companies_route
from app.models.entities import (
    Base,
    Company,
    DriverAssumptionVersion,
    FundamentalDriver,
    FundamentalModelVersion,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "DRV") -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _driver(db: Session, company: Company, driver_key: str = "revenue_growth") -> FundamentalDriver:
    model = FundamentalModelVersion(
        company_id=company.id, version=1, engine_version="test-engine",
        algorithm_version="test-algo", framework_key="holding", horizon_years=5,
        status="active", input_fingerprint=f"fp-{company.id}",
        forecast_fingerprint="ff", market_snapshot_fingerprint="mf",
        valuation_snapshot_fingerprint="vf",
    )
    db.add(model)
    db.flush()
    driver = FundamentalDriver(
        model_version_id=model.id, company_id=company.id, driver_key=driver_key,
        driver_type="revenue", status="active", unit="ratio",
    )
    db.add(driver)
    db.commit()
    return driver


def _payload(driver_key: str = "revenue_growth", fiscal_year: int = 2026, scenario: str = "base"):
    return companies_route.DriverAssumptionCreate(
        driver_key=driver_key,
        fiscal_year=fiscal_year,
        scenario=scenario,
        value=Decimal("0.12"),
        source="analyst",
        user_override=True,
        confidence=Decimal("0.8"),
        rationale="consenso",
    )


def test_driver_assumptions_404_compania_desconocida(db: Session):
    with pytest.raises(HTTPException) as exc:
        companies_route.list_driver_assumptions("NOPE", db=db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        companies_route.create_driver_assumption("NOPE", payload=_payload(), horizon=5, db=db)
    assert exc.value.status_code == 404


def test_create_driver_assumption_409_si_el_driver_no_existe(db: Session):
    _company(db, "DRV")
    with pytest.raises(HTTPException) as exc:
        companies_route.create_driver_assumption("DRV", payload=_payload("no_existe"), horizon=5, db=db)
    assert exc.value.status_code == 409
    assert "no_existe" in exc.value.detail


def test_driver_assumptions_cadena_de_versiones_y_filtros(db: Session, monkeypatch):
    company = _company(db, "DRV")
    _driver(db, company)
    monkeypatch.setattr(
        companies_route.LongTermModelService,
        "build",
        lambda self, db, company, horizon=5: {"persistence": {"model_version": 7}},
    )

    first = companies_route.create_driver_assumption("DRV", payload=_payload(), horizon=5, db=db)
    assert first["model_version"] == {"model_version": 7}
    assert first["assumption"]["driver_key"] == "revenue_growth"
    assert first["assumption"]["previous_version_id"] is None

    second = companies_route.create_driver_assumption("DRV", payload=_payload(), horizon=5, db=db)
    assert second["assumption"]["previous_version_id"] == first["assumption"]["id"]

    companies_route.create_driver_assumption("DRV", payload=_payload(scenario="bear"), horizon=5, db=db)

    todas = companies_route.list_driver_assumptions("DRV", db=db)
    assert len(todas) == 3
    assert all(item["driver_key"] == "revenue_growth" for item in todas)

    solo_bear = companies_route.list_driver_assumptions("DRV", scenario="bear", db=db)
    assert [item["scenario"] for item in solo_bear] == ["bear"]

    otro_driver = companies_route.list_driver_assumptions("DRV", driver_key="otro", db=db)
    assert otro_driver == []


def test_financial_terminal_404_compania_desconocida(db: Session):
    with pytest.raises(HTTPException) as exc:
        companies_route.financial_terminal("NOPE", years=10, db=db)
    assert exc.value.status_code == 404


def test_financial_terminal_sin_datos_marca_metricas_como_missing(db: Session):
    company = _company(db, "TERM")
    result = companies_route.financial_terminal(
        "TERM", metrics="revenue, net_income ,", years=5, db=db
    )
    assert result["ticker"] == "TERM"
    assert result["company"] == company.name
    assert result["years"] == 5
    assert result["range"]["to_fiscal_year"] - result["range"]["from_fiscal_year"] == 4
    assert result["coverage"]["requested"] == 2
    assert result["coverage"]["available"] == 0
    assert set(result["coverage"]["missing"]) == {"revenue", "net_income"}
    estados = {m["metric"]: m["status"] for m in result["metrics"]}
    assert estados == {"revenue": "missing", "net_income": "missing"}


def test_financial_terminal_periodicidad_invalida_es_error_controlado(db: Session):
    _company(db, "TERM")
    with pytest.raises(ValueError, match="periodicity"):
        companies_route.financial_terminal("TERM", years=10, periodicity="mensual", db=db)
