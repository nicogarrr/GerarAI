"""Ingesta SEC para el motor insurer (caso CB/Chubb, medido 19 oct 2026):

- book_value: el motor acepta ``total_equity`` (StockholdersEquity, hecho
  reportado) como alias en vez de pedir una copia con otro nombre.
- roe = net_income / patrimonio medio y book_value_growth = YoY de equity se
  derivan en _derive_sec_metrics (is_reported=False), con los valores reales
  del 10-K de Chubb como fixture.
- combined_ratio queda N/D a proposito: el derivado consolidado XBRL
  (1 - UnderwritingIncomeLoss/PremiumsEarnedNet = 87,5% en 2023) sesga +0,7pp
  contra el titular P&C que publica Chubb (86,9%). Regla: N/D, no sesgo.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService

# Valores reales del 10-K de Chubb (SEC companyfacts CIK 0000896159), USD.
EQ_2022, EQ_2023 = 50_500_000_000, 59_500_000_000
NI_2023 = 9_030_000_000
ROE_2023 = NI_2023 / ((EQ_2022 + EQ_2023) / 2)  # 16,4%
BVG_2023 = EQ_2023 / EQ_2022 - 1  # 17,8%


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="CB"):
    company = Company(
        ticker=ticker, name="Chubb Ltd", exchange="NYSE", currency="USD",
        sector="Financials", industry="Insurance - Property & Casualty",
        company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


K22, K23 = "0000896159-23-000010", "0000896159-24-000008"


class _FakeSECChubb:
    """10-Ks de 2022 y 2023 con los valores reales de Chubb. La ingesta anual
    es fail-closed: cada hecho entra solo si su `accn` esta anclado a la fecha
    de portada del 10-K (annual_report_anchors) y el mes de cierre coincide."""

    async def cik_for_ticker(self, ticker):
        return "0000896159"

    async def annual_report_anchors(self, cik):
        return {K22: "2022-12-31", K23: "2023-12-31"}

    async def index_accessions(self, cik):
        return {K22, K23}

    async def company_facts(self, cik):
        return {"facts": {"us-gaap": {
            "StockholdersEquity": {"units": {"USD": [
                {"fy": 2022, "fp": "FY", "form": "10-K", "end": "2022-12-31", "val": EQ_2022, "filed": "2023-02-24", "accn": K22},
                {"fy": 2023, "fp": "FY", "form": "10-K", "end": "2023-12-31", "val": EQ_2023, "filed": "2024-02-23", "accn": K23},
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                {"fy": 2023, "fp": "FY", "form": "10-K", "start": "2023-01-01", "end": "2023-12-31", "val": NI_2023, "filed": "2024-02-23", "accn": K23},
            ]}},
            "PremiumsEarnedNet": {"units": {"USD": [
                {"fy": 2023, "fp": "FY", "form": "10-K", "start": "2023-01-01", "end": "2023-12-31", "val": 45_700_000_000, "filed": "2024-02-23", "accn": K23},
            ]}},
            "UnderwritingIncomeLoss": {"units": {"USD": [
                {"fy": 2023, "fp": "FY", "form": "10-K", "start": "2023-01-01", "end": "2023-12-31", "val": 5_700_000_000, "filed": "2024-02-23", "accn": K23},
            ]}},
        }}}


def test_sec_derives_roe_and_book_value_growth_not_combined_ratio(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECChubb)
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))

    facts = {f.metric: f for f in db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id)
    )}
    assert facts["total_equity"].is_reported is True  # el hecho SEC, sin copia
    roe = facts["roe"]
    assert roe.is_reported is False and roe.source_type == "SEC"
    assert roe.fiscal_year == 2023 and float(roe.value) == pytest.approx(ROE_2023, rel=1e-5)
    bvg = facts["book_value_growth"]
    assert bvg.is_reported is False and float(bvg.value) == pytest.approx(BVG_2023, rel=1e-5)
    # Decision registrada: el derivado consolidado sesga +0,7pp vs el titular
    # P&C publicado; el motor lo declara faltante (N/D), no lo inventa.
    assert "combined_ratio" not in facts


def test_insurer_engine_resolves_book_value_from_total_equity_alias(db):
    from app.valuation.engines.sector_specific import _resolve_inputs

    company = _company(db)
    for metric, value, unit in (
        ("total_equity", EQ_2023, "USD"),
        ("shares_diluted", 400_000_000, "shares"),
        ("roe", ROE_2023, "decimal"),
        ("cost_of_equity", 0.09, "decimal"),
        ("book_value_growth", BVG_2023, "decimal"),
    ):
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
            period="2023-12-31:FY", fiscal_year=2023, fiscal_quarter="FY",
            source_type="SEC", is_reported=metric == "total_equity", confidence=Decimal("0.9"),
        ))
    db.commit()

    resolved = _resolve_inputs(
        context=type("Ctx", (), {"db": db, "company": company})(),
        anchor_metrics=("book_value", "common_equity", "total_equity"),
        inputs=dict(engine_inputs := {
            "book_value": ("book_value", "common_equity", "total_equity"),
            "shares_diluted": ("shares_diluted",),
            "roe": ("roe",),
            "cost_of_equity": ("cost_of_equity",),
            "combined_ratio": ("combined_ratio",),
            "book_value_growth": ("book_value_growth",),
        }),
        market_rates=("cost_of_equity",),
    )
    assert resolved.values["book_value"] is not None
    assert float(resolved.values["book_value"].value) == EQ_2023
    assert resolved.values["roe"] is not None and resolved.values["book_value_growth"] is not None
    missing = [k for k in engine_inputs if resolved.values[k] is None]
    assert missing == ["combined_ratio"]  # N/D declarado, nada mas


def test_sec_derives_equity_ratios_only_for_insurer_bank_engines(db, monkeypatch):
    """Objeción del auditor: book_value_growth es alias de dividend_growth en
    ddm_fcfe.py (sin filtrar is_reported). Derivarla para toda la empresa
    cambiaría valoraciones DDM/FCFE ya publicadas: solo insurer/bank derivan."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECChubb)
    company = Company(
        ticker="UTIL", name="Utility", exchange="NYSE", currency="USD",
        sector="Utilities", industry="Utilities - Regulated Electric",
        company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    metrics = {f.metric for f in db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id)
    )}
    assert "total_equity" in metrics  # el hecho reportado sí entra siempre
    assert "roe" not in metrics and "book_value_growth" not in metrics
