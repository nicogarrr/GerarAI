"""Desviacion del plan: objetivos por sector o clase de activo escritos como los ve el usuario.

La web muestra los sectores en español («Tecnología») y la caja como
«Caja», pero el backend los guarda en inglés («Technology», «Cash»). La
etiqueta del objetivo es texto libre: un objetivo «Tecnología 60 %» o
«Caja 40 %» leia 0 % y sugeria comprar lo que ya estaba en cartera.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Company, Position
from app.services.investment_plan_service import InvestmentPlanService
from tests.test_investment_plan_service import _plan


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _position(db, ticker, sector, value):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector=sector, industry=sector, company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    db.add(Position(company_id=company.id, quantity=Decimal("10"), market_price=Decimal("1"),
                    currency="EUR", market_value_base=Decimal(value), as_of=date(2026, 9, 20)))


def _deviations(db, targets):
    service = InvestmentPlanService()
    _plan(service, db, target_allocations=targets)
    _position(db, "MSFT", "Technology", "450")
    _position(db, "JPM", "Financial Services", "150")
    db.add(CashBalance(currency="EUR", balance=Decimal("400"), as_of=date(2026, 9, 20)))
    db.commit()
    drift = service.drift_analysis(db)
    return {d["label"]: d for d in drift["deviations"]}, drift["suggestions"]


def test_objetivos_en_espanol_leen_el_peso_real(db):
    by_label, suggestions = _deviations(db, [
        {"kind": "sector", "label": "Tecnología", "target_pct": 45, "band_pct": 5},
        {"kind": "sector", "label": "Servicios financieros", "target_pct": 15, "band_pct": 5},
        {"kind": "asset_class", "label": "Caja", "target_pct": 40, "band_pct": 5},
    ])
    assert by_label["Tecnología"]["current_pct"] == 45.0
    assert by_label["Servicios financieros"]["current_pct"] == 15.0
    assert by_label["Caja"]["current_pct"] == 40.0
    assert suggestions == []


def test_mayusculas_y_tildes_no_cambian_el_objetivo(db):
    by_label, _ = _deviations(db, [
        {"kind": "sector", "label": "technology", "target_pct": 45, "band_pct": 5},
        {"kind": "sector", "label": "tecnologia", "target_pct": 0, "band_pct": 50},
        {"kind": "asset_class", "label": "cash", "target_pct": 40, "band_pct": 5},
    ])
    assert by_label["technology"]["current_pct"] == 45.0
    assert by_label["tecnologia"]["current_pct"] == 45.0
    assert by_label["cash"]["current_pct"] == 40.0


def test_etiqueta_desconocida_sigue_en_cero(db):
    by_label, _ = _deviations(db, [
        {"kind": "sector", "label": "Minería lunar", "target_pct": 10, "band_pct": 5},
        {"kind": "sector", "label": "Technology", "target_pct": 45, "band_pct": 5},
    ])
    assert by_label["Minería lunar"]["current_pct"] == 0.0
    assert by_label["Technology"]["current_pct"] == 45.0
