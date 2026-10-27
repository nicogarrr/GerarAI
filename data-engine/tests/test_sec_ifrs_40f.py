"""Filers SEC en IFRS (40-F): Brookfield (BN) pasaba de 0 hechos a tener tesis.

Prueba real (27 oct 2026): BN presenta 40-F con XBRL en ``ifrs-full``; la
ingesta SEC solo leia ``us-gaap`` y la tesis salia «sin datos suficientes».
Valores de companyfacts de la SEC (CIK 0001001085), 40-F presentados el
2025-03-24 (FY2024) y el 2026-03-18 (FY2025):
- Revenue 86.006 M$ (2024) / 75.100 M$ (2025);
- ProfitLossAttributableToOwnersOfParent 641 M$ / 1.307 M$ (NO ProfitLoss,
  1.853 / 3.235 M$, que incluye minoritarios);
- AdjustedWeightedAverageShares (diluidas, IAS 33): FY2024 reexpresado en el
  40-F de 2026 tras el split 3x2 -> 2.376,8 M (el de 2025 decia 1.584,6 M);
  FY2025 2.367,8 M;
- CashAndCashEquivalents 15.051 / 16.242 M$; flujo operativo 7.569 / 10.958 M$;
- Borrowings 14.232 / 14.301 M$ (señal de deuda: la deuda neta NO es -caja).
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService

K25, K26 = "0001001085-25-000007", "0001001085-26-000006"
F25, F26 = "2025-03-24", "2026-03-18"


def _flow(val, year, accn, filed, fy):
    return {"fy": fy, "fp": "FY", "form": "40-F", "start": f"{year}-01-01",
            "end": f"{year}-12-31", "val": val, "filed": filed, "accn": accn}


def _inst(val, year, accn, filed, fy):
    return {"fy": fy, "fp": "FY", "form": "40-F", "end": f"{year}-12-31",
            "val": val, "filed": filed, "accn": accn}


def _usd(rows):
    return {"units": {"USD": rows}}


def _series(kind, v24_old, v24_new, v25):
    return [kind(v24_old, 2024, K25, F25, 2024), kind(v24_new, 2024, K26, F26, 2025),
            kind(v25, 2025, K26, F26, 2025)]


BN_IFRS = {
    "Revenue": _usd(_series(_flow, 86_006_000_000, 86_006_000_000, 75_100_000_000)),
    "ProfitLoss": _usd(_series(_flow, 1_853_000_000, 1_853_000_000, 3_235_000_000)),
    "ProfitLossAttributableToOwnersOfParent": _usd(
        _series(_flow, 641_000_000, 641_000_000, 1_307_000_000)
    ),
    "AdjustedWeightedAverageShares": {"units": {"shares": _series(
        _flow, 1_584_600_000, 2_376_800_000, 2_367_800_000
    )}},
    "CashAndCashEquivalents": _usd(_series(_inst, 15_051_000_000, 15_051_000_000, 16_242_000_000)),
    "CashFlowsFromUsedInOperatingActivities": _usd(
        _series(_flow, 7_569_000_000, 7_569_000_000, 10_958_000_000)
    ),
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": _usd(
        _series(_flow, 11_172_000_000, 11_172_000_000, 14_752_000_000)
    ),
    "Assets": _usd(_series(_inst, 490_424_000_000, 490_424_000_000, 518_971_000_000)),
    "Equity": _usd(_series(_inst, 165_383_000_000, 165_383_000_000, 166_194_000_000)),
    "Borrowings": _usd(_series(_inst, 14_232_000_000, 14_232_000_000, 14_301_000_000)),
}


class _FakeSECBrookfield:
    async def cik_for_ticker(self, ticker):
        return "0001001085"

    async def annual_report_anchors(self, cik):
        return {K25: "2024-12-31", K26: "2025-12-31"}

    async def index_accessions(self, cik):
        return {K25, K26}

    async def company_facts(self, cik):
        return {"cik": 1001085, "facts": {"ifrs-full": BN_IFRS}}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _annual(db, company, metric):
    return {
        f.fiscal_year: float(f.value)
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id, FinancialFact.metric == metric
            )
        )
        if f.fiscal_quarter == "FY"
    }


def test_bn_40f_ifrs_se_ingiere_con_semantica_us_gaap(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECBrookfield)
    company = Company(
        ticker="BN", name="Brookfield Corporation", exchange="NYSE", currency="USD",
        sector="Financial Services", industry="Asset Management",
        company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()

    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert result["facts_imported"] > 0

    assert _annual(db, company, "revenue") == {2024: 86_006_000_000.0, 2025: 75_100_000_000.0}
    # Atribuible a la dominante, no el total con minoritarios.
    assert _annual(db, company, "net_income") == {2024: 641_000_000.0, 2025: 1_307_000_000.0}
    # FY2024 reexpresado tras el split (gana el 40-F mas reciente).
    assert _annual(db, company, "shares_diluted") == {2024: 2_376_800_000.0, 2025: 2_367_800_000.0}
    assert _annual(db, company, "cash_and_equivalents")[2025] == 16_242_000_000.0
    assert _annual(db, company, "operating_cash_flow")[2025] == 10_958_000_000.0
    # Patrimonio total con minoritarios NO se usa como patrimonio de la dominante.
    assert _annual(db, company, "total_equity") == {}
    # Hay prestamos: la deuda neta no se publica como -caja.
    assert _annual(db, company, "net_debt") == {}

    document = db.scalars(
        select(Document).where(Document.company_id == company.id, Document.source_type == "SEC")
    ).first()
    assert document is not None
    assert (document.metadata_ or {}).get("xbrl_taxonomy") == "ifrs-full"


def test_filer_us_gaap_no_cambia_de_taxonomia(db, monkeypatch):
    class _UsGaapAndIfrs(_FakeSECBrookfield):
        async def company_facts(self, cik):
            return {"cik": 1001085, "facts": {
                "us-gaap": {"Revenues": _usd([_flow(10, 2025, K26, F26, 2025)])},
                "ifrs-full": BN_IFRS,
            }}

    monkeypatch.setattr(ingestion, "SECClient", _UsGaapAndIfrs)
    company = Company(
        ticker="XUS", name="Dual Co", exchange="NYSE", currency="USD", sector="Unknown",
        industry="Unknown", company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    # Con us-gaap presente no se mezcla ifrs-full.
    assert _annual(db, company, "net_income") == {}
