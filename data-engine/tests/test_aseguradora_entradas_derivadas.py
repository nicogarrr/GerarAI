"""El motor de aseguradoras deriva ROE y crecimiento del libro de los hechos.

Antes (main 95a9c193d): CB tenia beneficio 10.310, patrimonio 73.757 (y 64.021
el ejercicio anterior) y el motor pedia el ROE, el ratio combinado y el
crecimiento del libro ya calculados: «insufficient» en CB y FFH. Ahora los
calcula (mismo calculo de 1 ejercicio que midio el backtest del motor actual,
no la regla de 5 anos que no paso el holdout), los declara como calculados y,
si el modelo no los admite (crecimiento >= coste del capital), lo dice con las
cifras.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, FinancialFact
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.sector_specific import InsurerValuationEngine


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.info["tenant_id"] = 2
        yield session
    eng.dispose()


def _insurer(db, facts):
    company = Company(ticker="INSX", name="Insurer X", exchange="NYSE", currency="USD", sector="Financials",
                      industry="Insurance", company_type="insurer", valuation_model="insurance_book_value",
                      special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.flush()
    for metric, year, value, unit in facts:
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
                             period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY", source_type="SEC"))
    db.commit()
    return company


BASE = [
    ("total_equity", 2025, 1100, "USD"),
    ("total_equity", 2024, 1000, "USD"),
    ("net_income", 2025, 147, "USD"),
    ("shares_diluted", 2025, 100, "shares"),
    ("cost_of_equity", 2025, 0.10, "decimal"),
    ("combined_ratio", 2025, 0.95, "decimal"),
]


def _value(db, company):
    return InsurerValuationEngine().value(
        ValuationContext(db=db, company=company, snapshot=None, current_price=12.0, engine_key="insurer")
    )


def test_deriva_roe_y_crecimiento_del_libro(db):
    out = _value(db, _insurer(db, BASE))
    # 10 % de crecimiento del libro = coste del capital: el modelo de Gordon no
    # lo admite y lo dice con las cifras (el caso valido, 5 %, va abajo).
    assert out["status"] == "insufficient_data"
    inputs = out["trace"]["inputs"]
    assert inputs["roe"] == pytest.approx(147 / 1050)
    assert inputs["book_value_growth"] == pytest.approx(0.10)
    assert "10.00%" in out["trace"]["reason"]


def test_valora_con_entradas_derivadas_y_las_declara(db):
    facts = [("total_equity", 2025, 1050, "USD"), *BASE[1:]]
    out = _value(db, _insurer(db, facts))
    assert out["status"] != "insufficient_data", out.get("missing_inputs")
    assert out["base_value"] > 0
    methods = {item["metric"]: item for item in out.get("estimated_inputs") or []}
    assert methods["roe"]["status"] == "calculado"
    assert methods["book_value_growth"]["value"] == pytest.approx(0.05)
    assert "combined_ratio" not in methods  # publicado: no se toca


def test_sin_libro_del_ejercicio_anterior_dice_por_que(db):
    facts = [row for row in BASE if not (row[0] == "total_equity" and row[1] == 2024)]
    out = _value(db, _insurer(db, facts))
    assert out["status"] == "insufficient_data"
    assert "roe" in out["missing_inputs"] and "book_value_growth" in out["missing_inputs"]
    assert "2024" in out["trace"]["derivation_gaps"]["roe"]


def test_roe_publicado_manda_sobre_el_derivado(db):
    facts = [("total_equity", 2025, 1050, "USD"), *BASE[1:], ("roe", 2025, 0.12, "decimal")]
    out = _value(db, _insurer(db, facts))
    methods = {item["metric"] for item in out.get("estimated_inputs") or []}
    assert "roe" not in methods
