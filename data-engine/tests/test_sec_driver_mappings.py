"""Drivers obligatorios que SI estan en us-gaap y la ingesta SEC no leia.

Prueba real (27 oct 2026): la tesis de CB pedia «primas devengadas» y la de
RKLB «backlog» como drivers ausentes, con el dato en el 10-K:
- Chubb: PremiumsEarnedNet FY2024 49.846 M$, FY2025 53.014 M$
  (CIK 0000896159, 10-K presentado el 2026-02-27).
- Rocket Lab: RevenueRemainingPerformanceObligation (ASC 606, lo que Rocket
  Lab publica como backlog) FY2024 1.067,0 M$, FY2025 1.847,3 M$
  (CIK 0001819994, 10-K presentado el 2026-02-26).
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.long_term_model_service import LongTermModelService

CB_K24, CB_K25 = "0000896159-25-000004", "0000896159-26-000005"
RKLB_K24, RKLB_K25 = "0001628280-25-008724", "0001819994-26-000013"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker, name=name, exchange="NYSE", currency="USD",
        sector="Unknown", industry="Unknown", company_type="research_candidate",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _flow(val, year, accn, filed):
    return {"fy": year, "fp": "FY", "form": "10-K", "start": f"{year}-01-01", "end": f"{year}-12-31",
            "val": val, "filed": filed, "accn": accn}


def _instant(val, year, accn, filed):
    return {"fy": year, "fp": "FY", "form": "10-K", "end": f"{year}-12-31", "val": val, "filed": filed, "accn": accn}


class _FakeSECChubb:
    async def cik_for_ticker(self, ticker):
        return "0000896159"

    async def annual_report_anchors(self, cik):
        return {CB_K24: "2024-12-31", CB_K25: "2025-12-31"}

    async def index_accessions(self, cik):
        return {CB_K24, CB_K25}

    async def company_facts(self, cik):
        return {"cik": 896159, "facts": {"us-gaap": {
            "PremiumsEarnedNet": {"units": {"USD": [
                _flow(49_846_000_000, 2024, CB_K24, "2025-02-27"),
                _flow(53_014_000_000, 2025, CB_K25, "2026-02-27"),
            ]}},
            "Revenues": {"units": {"USD": [
                _flow(55_753_000_000, 2024, CB_K24, "2025-02-27"),
                _flow(59_402_000_000, 2025, CB_K25, "2026-02-27"),
            ]}},
        }}}


class _FakeSECRocketLab:
    async def cik_for_ticker(self, ticker):
        return "0001819994"

    async def annual_report_anchors(self, cik):
        return {RKLB_K24: "2024-12-31", RKLB_K25: "2025-12-31"}

    async def index_accessions(self, cik):
        return {RKLB_K24, RKLB_K25}

    async def company_facts(self, cik):
        return {"cik": 1819994, "facts": {"us-gaap": {
            "RevenueRemainingPerformanceObligation": {"units": {"USD": [
                _instant(1_067_037_000, 2024, RKLB_K24, "2025-02-27"),
                _instant(1_847_322_000, 2025, RKLB_K25, "2026-02-26"),
            ]}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                _flow(436_214_000, 2024, RKLB_K24, "2025-02-27"),
                _flow(601_799_000, 2025, RKLB_K25, "2026-02-26"),
            ]}},
        }}}


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


def _driver(model: dict, key: str) -> dict:
    return next(d for d in model["driver_model"] if d["key"] == key)


def test_cb_primas_devengadas_se_ingieren_y_el_driver_deja_de_faltar(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECChubb)
    company = _company(db, "CB", "Chubb Ltd")
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))

    assert _annual(db, company, "earned_premiums") == {2024: 49_846_000_000.0, 2025: 53_014_000_000.0}
    model = LongTermModelService().build(db, company, commit=False)
    premiums = _driver(model, "earned_premiums")
    assert premiums["status"] == "sourced" and premiums["value"] == 53_014_000_000.0
    assert "earned_premiums" not in model["missing_mandatory_drivers"]
    # El combined ratio sigue N/D a proposito (sesgo del derivado XBRL).
    assert "combined_ratio" in model["missing_mandatory_drivers"]


def test_rklb_backlog_es_la_obligacion_de_desempeno_pendiente(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECRocketLab)
    company = _company(db, "RKLB", "Rocket Lab")
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))

    assert _annual(db, company, "backlog") == {2024: 1_067_037_000.0, 2025: 1_847_322_000.0}
    model = LongTermModelService().build(db, company, commit=False)
    backlog = _driver(model, "backlog")
    assert backlog["status"] == "sourced" and backlog["value"] == 1_847_322_000.0
    assert "backlog" not in model["missing_mandatory_drivers"]
