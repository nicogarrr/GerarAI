"""Ingesta SEC: trimestres derivados de acumulados YTD (Apple, AAPL).

Apple presenta el estado de flujos de efectivo de sus 10-Q solo ACUMULADO
(3, 6 y 9 meses). La ingesta debe guardar Q2 y Q3 como YTD(t) − YTD(t−1),
marcados no reportados (INFERIDO), y con eso el TTM sale bien.

Cifras reales (tests/fixtures/aapl_ttm.json, copiadas del companyfacts de la
SEC: 10-K FY2025 y 10-Q Q1-Q3 FY2025/FY2026). Sin red: el companyfacts es un
dict mínimo con el formato real de la SEC.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.ttm_fundamentals import PeriodValue, trailing_twelve_months


class _Fixture:
    """Cifras reales de Apple: tests/fixtures/aapl_ttm.json (ver «_fuente»)."""

    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)


aapl = _Fixture(json.loads((Path(__file__).parent / "fixtures" / "aapl_ttm.json").read_text("utf-8")))
M = 1_000_000


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="AAPL"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="quality",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _entry(start, end, val, fp, form="10-Q", filed="2026-07-31", accn="0000320193-26-000001"):
    row = {"end": end, "val": val, "fp": fp, "form": form, "filed": filed, "accn": accn,
           "fy": int(end[:4])}
    if start:
        row["start"] = start
    return row


class _FakeSEC:
    facts: dict = {}

    async def cik_for_ticker(self, ticker):
        return "0000320193"

    async def company_facts(self, cik):
        return self.facts

    async def annual_report_anchors(self, cik):
        return {"0000320193-25-000079": aapl.FY25_END}

    async def index_accessions(self, cik):
        return None


def test_ingesta_sec_deriva_trimestres_del_flujo_operativo_aapl(db):
    """Apple solo presenta el flujo operativo acumulado en sus 10-Q. La ingesta
    debe guardar Q2 y Q3 derivados (YTD − YTD anterior) como no reportados, y
    el TTM sale 146.724 (= 111.482 + 116.996 − 81.754)."""
    fps = ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3"]
    ocf = [
        _entry(start, end, val * M, fp)
        for (start, end, val), fp in zip(aapl.OPERATING_CASH_FLOW_YTD, fps, strict=True)
    ]
    ocf.append(_entry(aapl.FY2025_START, aapl.FY25_END, 111_482 * M, "FY", form="10-K",
                      filed="2025-10-31", accn="0000320193-25-000079"))
    facts = {
        "cik": 320193,
        "facts": {"us-gaap": {
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
        }},
    }
    monkey = type("FakeSECInstance", (_FakeSEC,), {"facts": facts})()
    original = ingestion.SECClient
    ingestion.SECClient = lambda *a, **k: monkey
    try:
        company = _company(db)
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    finally:
        ingestion.SECClient = original
    db.commit()

    rows = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "operating_cash_flow",
    )).all()
    by_period = {r.period: r for r in rows}
    q3 = by_period[f"{aapl.Q3_FY26}:Q3"]
    assert q3.value == Decimal(34_369 * M)
    assert q3.is_reported is False
    q1 = by_period[f"{aapl.Q1_FY26}:Q1"]
    assert q1.value == Decimal(53_925 * M)
    assert q1.is_reported is True
    assert by_period[f"{aapl.Q2_FY25}:Q2"].value == Decimal(23_952 * M)

    # TTM con las filas guardadas (Q4 FY25 = FY − 9M = 111.482 − 81.754):
    # 29.728 + 53.925 + 28.702 + 34.369 = 146.724
    quarters = [
        PeriodValue(end=date.fromisoformat(r.period[:10]), value=r.value, reported=r.is_reported)
        for r in rows if r.fiscal_quarter != "FY"
    ]
    annuals = [
        PeriodValue(end=date.fromisoformat(r.period[:10]), value=r.value)
        for r in rows if r.fiscal_quarter == "FY"
    ]
    ttm = trailing_twelve_months("operating_cash_flow", quarters, annuals)
    assert ttm.basis == "TTM"
    assert ttm.value == Decimal(146_724 * M)
    assert ttm.provenance == "INFERIDO"


def test_ingesta_sec_trimestre_presentado_no_se_sustituye(db):
    """Si el 10-Q trae el trimestre de 3 meses, se guarda ese (reportado) y
    no el derivado del acumulado."""
    ocf = [
        _entry(aapl.FY2026_START, aapl.Q1_FY26, 53_925 * M, "Q1"),
        _entry(aapl.FY2026_START, aapl.Q2_FY26, 82_627 * M, "Q2"),
        _entry("2025-12-28", aapl.Q2_FY26, 28_000 * M, "Q2"),
    ]
    facts = {"cik": 320193, "facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
    }}}
    monkey = type("FakeSECInstance", (_FakeSEC,), {"facts": facts})()
    original = ingestion.SECClient
    ingestion.SECClient = lambda *a, **k: monkey
    try:
        company = _company(db)
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    finally:
        ingestion.SECClient = original
    row = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.period == f"{aapl.Q2_FY26}:Q2",
    )).one()
    assert row.value == Decimal(28_000 * M)
    assert row.is_reported is True
