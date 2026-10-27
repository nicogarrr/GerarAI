"""Puerta suave: un KPI operativo sin dato no despublica la tesis.

Prueba real (27 oct 2026): 14 de las 19 tesis de Nico salian «sin datos
suficientes» aunque los inputs centrales (ingresos, flujo de caja, acciones)
estaban en el 10-K. Lo que faltaba eran KPIs operativos del marco que NO
existen en XBRL (suscriptores, ARPU, churn...). Caso HIMS (Hims & Hers,
CIK 0001773751, 10-K presentado en 2026): ingresos FY2024 1.476.514.000 y
FY2025 2.347.637.000; flujo operativo 251.084.000 / 300.006.000; inversion
(PaymentsToAcquireProductiveAssets) 52.800.000 / 242.600.000; acciones
diluidas 236.808.876 / 258.230.547.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, CalculatedMetric, Company, FinancialFact
from app.services.long_term_model_service import LongTermModelService
from app.services.thesis_service import _driver_gaps_es, _ltm_status_es


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _hims(db, *, with_wacc: bool) -> Company:
    company = Company(
        ticker="HIMS", name="Hims & Hers Health, Inc.", exchange="NYSE", currency="USD",
        sector="Healthcare", industry="Health Information Services",
        company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()

    def fact(metric, value, year, unit="USD"):
        return FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
            period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
            source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
        )

    db.add_all([
        fact("revenue", 1_476_514_000, 2024),
        fact("revenue", 2_347_637_000, 2025),
        fact("operating_cash_flow", 251_084_000, 2024),
        fact("operating_cash_flow", 300_006_000, 2025),
        fact("capital_expenditure", 52_800_000, 2024),
        fact("capital_expenditure", 242_600_000, 2025),
        fact("shares_diluted", 236_808_876, 2024, "shares"),
        fact("shares_diluted", 258_230_547, 2025, "shares"),
    ])
    if with_wacc:
        db.add(CalculatedMetric(
            company_id=company.id, metric="wacc", value=Decimal("0.10"), unit="decimal",
            period="FY2025", fiscal_year=2025, status="ok", definition_version="wacc-v1",
            formula="E/(D+E)*cost_of_equity + D/(D+E)*after_tax_cost_of_debt",
            source_fact_ids=[], calculation_trace={"risk_free_rate": 0.04},
            confidence=Decimal("0.90"),
        ))
    db.commit()
    return company


def test_kpis_operativos_sin_dato_no_bloquean_el_modelo(db):
    company = _hims(db, with_wacc=True)
    model = LongTermModelService().build(db, company, commit=False)

    assert model["framework"]["key"] == "subscriber"
    # Siguen declarados (trazabilidad), pero ya no son un estado de bloqueo.
    assert "subscribers" in model["missing_mandatory_drivers"]
    assert model["status"] == "ok"
    assert model["publishable"] is True
    gaps = {gap["key"]: gap["motivo"] for gap in model["driver_gaps"]}
    assert set(gaps) == set(model["missing_mandatory_drivers"])
    assert "XBRL" in gaps["churn"]
    assert all(motivo and "_" not in motivo for motivo in gaps.values())


def test_sin_inputs_centrales_sigue_bloqueado(db):
    company = _hims(db, with_wacc=True)
    db.query(FinancialFact).filter(FinancialFact.metric == "shares_diluted").delete()
    db.commit()
    model = LongTermModelService().build(db, company, commit=False)
    assert model["status"] == "insufficient_data"
    assert model["publishable"] is False


def test_memo_muestra_sin_dato_con_motivo_y_sin_claves_internas(db):
    company = _hims(db, with_wacc=False)
    model = LongTermModelService().build(db, company, commit=False)
    text = _driver_gaps_es(model)
    assert "sin dato (" in text
    assert "monthly_arpu" not in text and "subscribers" not in text
    assert "No bloquean la valoración" in text


def test_estado_del_motor_en_espanol_nunca_el_codigo():
    assert _ltm_status_es("missing_mandatory_drivers") == "con datos operativos pendientes"
    assert _ltm_status_es("preview_only").startswith("vista previa")
    assert _ltm_status_es("ok") == "completo"
    assert "_" not in _ltm_status_es("insufficient_data")
    assert _ltm_status_es(None) == "sin estado"


def test_memo_snapshot_antiguo_sin_driver_gaps():
    text = _driver_gaps_es({"missing_mandatory_drivers": ["subscribers"]})
    assert "sin dato" in text and "subscribers" not in text
    assert _driver_gaps_es({"missing_mandatory_drivers": [], "driver_gaps": []}) == "todos con dato"
