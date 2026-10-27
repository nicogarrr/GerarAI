"""Derivados deterministas en el modelo fundamental, con hechos reales.

Prueba real (27 oct 2026), a partir de las tesis de Nico:
- CPT (Camden): la tesis pedia «NOI» como driver obligatorio ausente. El NOI
  no es un concepto us-gaap, pero sale por identidad de tres hechos del 10-K:
  OperatingLeaseLeaseIncome − DirectCostsOfLeasedAndRentedPropertyOrEquipment
  − RealEstateTaxExpense. FY2025: 1.573.544.000 − 369.889.000 − 196.821.000
  = 1.006.834.000 $ (CIK 0000906345, 10-K presentado el 2026-02-12).
- KKR: la tesis decia «faltan acciones diluidas». KKR no etiqueta la media
  ponderada diluida en us-gaap desde 2018; solo CommonStockSharesOutstanding
  (FY2025: 891.451.844; 10-K presentado el 2026-02-27).
Cada derivado se marca «derivado» con su formula y sus fact_ids.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.long_term_model_service import LongTermModelService
from app.services.thesis_provenance import build_inputs_provenance

CPT_K24, CPT_K25 = "0000906345-25-000008", "0001628280-26-007697"
NOI_FY2025 = 1_573_544_000 - 369_889_000 - 196_821_000  # 1.006.834.000
KKR_SHARES_FY2025 = 891_451_844


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


class _FakeSECCamden:
    async def cik_for_ticker(self, ticker):
        return "0000906345"

    async def annual_report_anchors(self, cik):
        return {CPT_K24: "2024-12-31", CPT_K25: "2025-12-31"}

    async def index_accessions(self, cik):
        return {CPT_K24, CPT_K25}

    async def company_facts(self, cik):
        def two(v24, v25):
            return {"units": {"USD": [_flow(v24, 2024, CPT_K24, "2025-02-20"), _flow(v25, 2025, CPT_K25, "2026-02-12")]}}

        return {"cik": 906345, "facts": {"us-gaap": {
            "OperatingLeaseLeaseIncome": two(1_543_842_000, 1_573_544_000),
            "DirectCostsOfLeasedAndRentedPropertyOrEquipment": two(365_681_000, 369_889_000),
            "RealEstateTaxExpense": two(193_124_000, 196_821_000),
        }}}


def _driver(model: dict, key: str) -> dict:
    return next(d for d in model["driver_model"] if d["key"] == key)


def test_cpt_noi_derivado_de_tres_hechos_del_10k(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECCamden)
    company = _company(db, "CPT", "Camden Property Trust")
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))

    model = LongTermModelService().build(db, company, commit=False)
    assert model["framework"]["key"] == "reit"
    noi = _driver(model, "net_operating_income")
    assert noi["status"] == "derived"
    assert noi["value"] == pytest.approx(NOI_FY2025)
    assert noi["derivation"]["label"] == "derivado"
    assert noi["derivation"]["fiscal_year"] == 2025
    assert "lease_income" in noi["derivation"]["formula"]
    assert len(noi["source_fact_ids"]) == 3
    assert "net_operating_income" not in model["missing_mandatory_drivers"]

    provenance = {item["key"]: item for item in build_inputs_provenance(model)}
    assert provenance["net_operating_income"]["label"] == "derivado"


def test_noi_sin_todas_las_entradas_sigue_sin_dato(db):
    company = _company(db, "CPT", "Camden Property Trust")
    db.add(FinancialFact(
        company_id=company.id, metric="lease_income", value=Decimal(1_573_544_000), unit="USD",
        period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    ))
    db.commit()
    model = LongTermModelService().build(db, company, commit=False)
    assert _driver(model, "net_operating_income")["status"] == "missing"
    assert "net_operating_income" in model["missing_mandatory_drivers"]


def _fact(company, metric, value, year, unit="USD"):
    return FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
        period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    )


def test_kkr_acciones_al_cierre_cubren_la_media_diluida_que_no_etiqueta(db):
    company = _company(db, "KKR", "KKR & Co. Inc.")
    db.add_all([
        _fact(company, "revenue", 21_878_698_000, 2024),
        _fact(company, "revenue", 19_464_307_000, 2025),
        _fact(company, "shares_outstanding", 888_232_174, 2024, "shares"),
        _fact(company, "shares_outstanding", KKR_SHARES_FY2025, 2025, "shares"),
    ])
    db.commit()

    model = LongTermModelService().build(db, company, commit=False)
    assert "shares_diluted" not in model["missing_inputs"]
    row = model["historical_review"]["rows"][-1]
    shares = row["metrics"]["shares_diluted"]
    assert shares["value"] == KKR_SHARES_FY2025
    assert shares["status"] == "calculated"
    assert "derivado" in shares["basis"]


def test_media_diluida_reportada_nunca_se_sustituye(db):
    company = _company(db, "AAPL", "Apple Inc.")
    db.add_all([
        _fact(company, "revenue", 391_035_000_000, 2024),
        _fact(company, "revenue", 416_161_000_000, 2025),
        _fact(company, "shares_diluted", 15_004_697_000, 2025, "shares"),
        _fact(company, "shares_outstanding", 14_776_353_000, 2025, "shares"),
    ])
    db.commit()
    model = LongTermModelService().build(db, company, commit=False)
    shares = model["historical_review"]["rows"][-1]["metrics"]["shares_diluted"]
    assert shares["value"] == 15_004_697_000
    assert shares["status"] == "reported"
