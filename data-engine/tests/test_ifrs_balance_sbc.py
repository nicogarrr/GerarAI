"""Balance y SBC IFRS estándar de los 20-F/40-F (regla 23 de ingesta SEC).

CNQ (40-F 2025, CIK 0001017413, valores reales de companyfacts, M CAD): activo corriente 7.664, pasivo
corriente 8.063, reservas 32.726, SBC (ajuste del estado de flujos) 180. Antes no se ingerían y el F-score
de Piotroski y la Z de Altman salían sin liquidez ni fondo de maniobra («current_assets: N/D»).
"""
import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import (
    SEC_IFRS_METRIC_MAP,
    SEC_INGESTION_RULES_VERSION,
    FinancialIngestionService,
)

K26, F26 = "0001017413-26-000018", "2026-03-18"


def _flow(val, concept_year=2025):
    return {"fy": 2025, "fp": "FY", "form": "40-F", "start": f"{concept_year}-01-01", "end": f"{concept_year}-12-31",
            "val": val, "filed": F26, "accn": K26}


def _inst(val):
    return {"fy": 2025, "fp": "FY", "form": "40-F", "end": "2025-12-31", "val": val, "filed": F26, "accn": K26}


def _cad(*rows):
    return {"units": {"CAD": list(rows)}}


M = 1_000_000
CNQ_IFRS = {
    "Revenue": _cad(_flow(38_762 * M)),
    "ProfitLoss": _cad(_flow(10_820 * M)),
    "Assets": _cad(_inst(140_000 * M)),
    "CurrentAssets": _cad(_inst(7_664 * M)),
    "CurrentLiabilities": _cad(_inst(8_063 * M)),
    "RetainedEarnings": _cad(_inst(32_726 * M)),
    "AdjustmentsForSharebasedPayments": _cad(_flow(180 * M)),
    "ExpenseFromSharebasedPaymentTransactionsWithEmployees": _cad(_flow(180 * M)),
}


class _FakeSEC:
    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0001017413"

    async def annual_report_anchors(self, cik):
        return {K26: "2025-12-31"}

    async def index_accessions(self, cik):
        return {K26}

    async def company_facts(self, cik):
        return {"cik": 1017413, "facts": {"ifrs-full": CNQ_IFRS}}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _fy(db, company, metric):
    return {f.fiscal_year: float(f.value) for f in db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id, FinancialFact.metric == metric))
        if f.fiscal_quarter == "FY"}


def test_cnq_40f_balance_and_sbc_are_ingested(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSEC)
    company = Company(ticker="CNQ", name="Canadian Natural Resources", exchange="NYSE", currency="USD",
                      sector="Energy", industry="Energy", company_type="operating", valuation_model="unassigned",
                      special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _fy(db, company, "current_assets") == {2025: 7_664 * M}
    assert _fy(db, company, "current_liabilities") == {2025: 8_063 * M}
    assert _fy(db, company, "retained_earnings") == {2025: 32_726 * M}
    assert _fy(db, company, "stock_based_compensation") == {2025: 180 * M}


def test_map_carries_the_standard_ifrs_concepts():
    concepts = {m: cs for m, cs, _u in SEC_IFRS_METRIC_MAP}
    assert concepts["goodwill"] == ["Goodwill"]
    assert concepts["intangible_assets"] == ["IntangibleAssetsOtherThanGoodwill"]  # sin el fondo de comercio
    assert concepts["stock_based_compensation"][0] == "AdjustmentsForSharebasedPayments"
    assert "long_term_debt" not in concepts  # LongtermBorrowings IFRS no es «deuda a largo» homogénea (TSM)
    assert SEC_INGESTION_RULES_VERSION >= 23
