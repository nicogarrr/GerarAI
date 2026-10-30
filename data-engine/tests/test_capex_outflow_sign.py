"""Signo del capex: salida de caja, FCF = flujo operativo - |capex|.

El relleno SEC de la tesis guardaba PaymentsToAcquirePropertyPlantAndEquipment
tal cual (positivo) mientras el resto de la app lo guarda en negativo. Con
FCF = OCF + capex, un capex positivo inflaba el FCF en 2 x capex.

Calculo independiente: OCF 1.000, capex 200 -> FCF 800. Main daba 1.200.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import FinancialFact
from app.services.long_term_model_service import _derived_fcf
from app.services.thesis_evidence_service import ThesisEvidenceService
from app.services.ttm_service import build_company_ttm
from tests.test_ttm_service import _company, _metric, db  # noqa: F401  (fixture)


def _annual(db, company, metric, value):  # noqa: F811
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
        period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY", source_type="SEC",
        is_reported=True, filed=date(2026, 2, 1),
    ))


def test_fcf_ttm_resta_un_capex_guardado_en_positivo(db):  # noqa: F811
    company = _company(db, "CAPX")
    _annual(db, company, "operating_cash_flow", "1000")
    _annual(db, company, "capital_expenditure", "200")
    db.commit()
    payload = build_company_ttm(db, company)
    assert Decimal(str(_metric(payload, "free_cash_flow")["value"])) == Decimal("800")


def test_fcf_ttm_con_capex_negativo_sin_cambio(db):  # noqa: F811
    company = _company(db, "CAPN")
    _annual(db, company, "operating_cash_flow", "1000")
    _annual(db, company, "capital_expenditure", "-200")
    db.commit()
    payload = build_company_ttm(db, company)
    assert Decimal(str(_metric(payload, "free_cash_flow")["value"])) == Decimal("800")


def test_fcf_modelo_largo_plazo_resta_capex_positivo():
    ocf = FinancialFact(metric="operating_cash_flow", value=Decimal("1000"))
    capex = FinancialFact(metric="capital_expenditure", value=Decimal("200"))
    assert _derived_fcf(ocf, capex) == Decimal("800")
    capex.value = Decimal("-200")
    assert _derived_fcf(ocf, capex) == Decimal("800")


def test_relleno_sec_de_la_tesis_guarda_el_capex_en_negativo(db, monkeypatch):  # noqa: F811
    company = _company(db, "CAPS")
    entry = {"val": 200, "end": "2025-12-31", "start": "2025-01-01", "form": "10-K",
             "filed": "2026-02-01", "fy": 2025, "fp": "FY"}
    payload = {"facts": {"us-gaap": {
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [entry]}},
    }}}
    service = ThesisEvidenceService()
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: payload)
    service._ingest_fundamentals(db, company, "0000000001")
    db.flush()
    values = db.scalars(select(FinancialFact.value).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "capital_expenditure",
    )).all()
    assert [Decimal(str(v)) for v in values] == [Decimal("-200")]
