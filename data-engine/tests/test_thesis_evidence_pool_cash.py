"""Ingesta rapida de la tesis (ThesisEvidenceService) con hechos reales de POOL.

Caso real (prueba de usuario, 27 oct 2026): la tesis de POOL salia bloqueada
por «falta deuda neta» porque la caja guardada se cortaba en 2018. POOL dejo de
presentar CashAndCashEquivalentsAtCarryingValue tras FY2018 (ASU 2016-18) y solo
publica el tag combinado con caja restringida; la ingesta rapida no lo leia.
Ademas tomaba LongTermDebtNoncurrent antes que el total (largo + corto plazo).

Valores de SEC companyfacts de Pool Corp (CIK 0000945841), 10-K presentado el
2026-02-26, USD.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.financial_ingestion_service import SEC_METRIC_MAP
from app.services.thesis_evidence_service import SEC_EVIDENCE_TAGS, ThesisEvidenceService

CASH_FY2025 = 104_963_000  # CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents
CASH_FY2024 = 77_862_000
DEBT_FY2025 = 1_199_453_000  # DebtLongtermAndShorttermCombinedAmount
DEBT_FY2025_NONCURRENT = 1_186_424_000  # LongTermDebtNoncurrent (sin la parte corriente)
NET_DEBT_FY2025 = DEBT_FY2025 - CASH_FY2025  # 1.094.490.000


def _e(val, end, filed, fy):
    return {"form": "10-K", "val": val, "end": end, "fy": fy, "fp": "FY", "filed": filed}


POOL_US_GAAP = {
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _e(29_940_000, "2017-12-31", "2019-02-27", 2018),
        _e(16_358_000, "2018-12-31", "2019-02-27", 2018),
    ]}},
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": {"units": {"USD": [
        _e(29_940_000, "2017-12-31", "2021-02-25", 2020),
        _e(16_358_000, "2018-12-31", "2022-02-25", 2021),
        _e(CASH_FY2024, "2024-12-31", "2026-02-26", 2025),
        _e(CASH_FY2025, "2025-12-31", "2026-02-26", 2025),
    ]}},
    "LongTermDebtNoncurrent": {"units": {"USD": [
        _e(900_883_000, "2024-12-31", "2026-02-26", 2025),
        _e(DEBT_FY2025_NONCURRENT, "2025-12-31", "2026-02-26", 2025),
    ]}},
    "DebtLongtermAndShorttermCombinedAmount": {"units": {"USD": [
        _e(950_356_000, "2024-12-31", "2026-02-26", 2025),
        _e(DEBT_FY2025, "2025-12-31", "2026-02-26", 2025),
    ]}},
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _pool(db: Session) -> Company:
    company = Company(
        ticker="POOL", name="Pool Corporation", exchange="NASDAQ", currency="USD",
        sector="Consumer", industry="Distribution", company_type="compounder",
        valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_caja_de_pool_llega_a_2025_con_el_tag_combinado():
    extracted = ThesisEvidenceService()._extract_recent_annuals(POOL_US_GAAP)
    cash = {info["fiscal_year"]: info for info in extracted["cash_and_equivalents"]}
    assert sorted(cash) == [2018, 2024, 2025]
    assert cash[2025]["value"] == CASH_FY2025
    assert cash[2025]["concept"] == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    # A igual periodo manda la caja sin restringida (preferencia declarada).
    assert cash[2018]["concept"] == "CashAndCashEquivalentsAtCarryingValue"


def test_deuda_total_incluye_la_parte_corriente():
    extracted = ThesisEvidenceService()._extract_recent_annuals(POOL_US_GAAP)
    debt = {info["fiscal_year"]: info for info in extracted["total_debt"]}
    assert debt[2025]["value"] == DEBT_FY2025
    assert debt[2025]["value"] != DEBT_FY2025_NONCURRENT


def test_ingesta_rapida_deja_caja_y_deuda_del_mismo_ejercicio(db, monkeypatch):
    company = _pool(db)
    service = ThesisEvidenceService()
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: {"facts": {"us-gaap": POOL_US_GAAP}})

    result = service._ingest_fundamentals(db, company, "0000945841")
    assert result["status"] == "ok"

    def value(metric: str, year: int) -> Decimal | None:
        return db.scalar(
            select(FinancialFact.value).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
                FinancialFact.fiscal_year == year,
            )
        )

    cash, debt = value("cash_and_equivalents", 2025), value("total_debt", 2025)
    assert cash is not None and debt is not None
    assert cash == Decimal(CASH_FY2025)
    assert debt == Decimal(DEBT_FY2025)
    assert debt - cash == Decimal(NET_DEBT_FY2025)


def test_alias_de_caja_y_deuda_son_los_de_la_ingesta_completa():
    """Las dos ingestas no pueden volver a divergir en los alias de caja/deuda."""
    canonical = {metric: set(tags) for metric, tags, _unit in SEC_METRIC_MAP}
    for metric in ("cash_and_equivalents", "total_debt"):
        quick_tags, _unit = SEC_EVIDENCE_TAGS[metric]
        assert set(quick_tags) <= canonical[metric], metric
    assert set(SEC_EVIDENCE_TAGS["cash_and_equivalents"][0]) == canonical["cash_and_equivalents"]
