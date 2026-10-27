"""F352: el extractor de revenue solo conocia "Revenues",
"RevenueFromContractWithCustomerExcludingAssessedTax" y "SalesRevenueNet".
Emisores vivos cuyo revenue reciente vive bajo otras etiquetas quedaban
anclados al pasado incluso tras un backfill completo. Casos reales (28/09/2026,
32 companies vivas de tenant 2):
- AKAM y otras 14: RevenueFromContractWithCustomerIncludingAssessedTax (FY2025)
- DTE y XEL (utilities): RegulatedAndUnregulatedOperatingRevenue (FY2025)
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.thesis_evidence_service import ThesisEvidenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fy(year, end, val, filed, form="10-K"):
    return {"fy": year, "fp": "FY", "form": form, "start": f"{year - 1}-12-30",
            "end": end, "val": val, "filed": filed}


class _FakeSECAKAM:
    """AKAM: "Revenues" muere en FY2017; el revenue reciente (FY2025) vive
    bajo la variante IncludingAssessedTax."""

    async def cik_for_ticker(self, ticker):
        return "0001086222"

    async def company_facts(self, cik):
        return {"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                _fy(2016, "2016-12-31", 2_340_049_000, "2017-03-01"),
                _fy(2017, "2017-12-31", 2_502_996_000, "2018-03-01"),
            ]}},
            "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": [
                _fy(2024, "2024-12-31", 3_991_000_000, "2025-02-20"),
                _fy(2025, "2025-12-31", 4_200_000_000, "2026-02-19"),
            ]}},
        }}}


class _FakeSECDTE:
    """DTE (utility): solo informa RegulatedAndUnregulatedOperatingRevenue."""

    async def cik_for_ticker(self, ticker):
        return "0000936340"

    async def company_facts(self, cik):
        return {"facts": {"us-gaap": {
            "RegulatedAndUnregulatedOperatingRevenue": {"units": {"USD": [
                _fy(2024, "2024-12-31", 12_459_000_000, "2025-02-13"),
                _fy(2025, "2025-12-31", 13_000_000_000, "2026-02-12"),
            ]}},
            # #2384: sin evidencia de divisa (Assets/Liabilities/Equity) la
            # divisa de reporte es desconocida y no se guardan hechos en USD.
            # Todo 10-K real trae Assets; el fake tambien.
            "Assets": {"units": {"USD": [
                _fy(2025, "2025-12-31", 50_000_000_000, "2026-02-12"),
            ]}},
        }}}


def test_ingesta_akam_variante_including_assessed_tax(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECAKAM)
    company = _company(db, "AKAM")
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
            FinancialFact.is_reported.is_(True),
            FinancialFact.fiscal_quarter == "FY",
        )
    ))
    by_year = {f.fiscal_year: f.value for f in facts}
    assert by_year[2017] == Decimal("2502996000")
    assert by_year[2025] == Decimal("4200000000")
    assert max(by_year) == 2025


def test_ingesta_utility_regulated_operating_revenue(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECDTE)
    company = _company(db, "DTE")
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
            FinancialFact.is_reported.is_(True),
            FinancialFact.fiscal_quarter == "FY",
        )
    ))
    by_year = {f.fiscal_year: f.value for f in facts}
    assert by_year == {2024: Decimal("12459000000"), 2025: Decimal("13000000000")}


def test_evidencia_prefiere_including_reciente_sobre_revenues_viejo():
    us_gaap = {
        "Revenues": {"units": {"USD": [
            {"form": "10-K", "val": 2502996000, "start": "2017-01-01",
             "end": "2017-12-31", "filed": "2018-03-01"},
        ]}},
        "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": [
            {"form": "10-K", "val": 4200000000, "start": "2025-01-01",
             "end": "2025-12-31", "filed": "2026-02-19"},
        ]}},
    }
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 4200000000
    assert out["revenue"]["fiscal_year"] == 2025
    assert out["revenue"]["concept"] == "RevenueFromContractWithCustomerIncludingAssessedTax"


def test_evidencia_utility_regulated_operating_revenue():
    us_gaap = {
        "RegulatedAndUnregulatedOperatingRevenue": {"units": {"USD": [
            {"form": "10-K", "val": 13000000000, "start": "2025-01-01",
             "end": "2025-12-31", "filed": "2026-02-12"},
        ]}},
    }
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 13000000000
    assert out["revenue"]["fiscal_year"] == 2025
    assert out["revenue"]["concept"] == "RegulatedAndUnregulatedOperatingRevenue"


def test_contrato_lista_tags_revenue_ambos_servicios():
    """La lista de candidatos de revenue debe ser identica en la ingesta
    principal y en la ruta de evidencia, e incluir las variantes F352."""
    from app.services.financial_ingestion_service import SEC_METRIC_MAP
    from app.services.thesis_evidence_service import SEC_EVIDENCE_TAGS

    main_tags = {m: tags for m, tags, _unit in SEC_METRIC_MAP}["revenue"]
    evidence_tags, _unit = SEC_EVIDENCE_TAGS["revenue"]
    assert main_tags == evidence_tags
    assert "RevenueFromContractWithCustomerIncludingAssessedTax" in main_tags
    assert "RegulatedAndUnregulatedOperatingRevenue" in main_tags


def _with_anchors(payload, close_month):
    """Plumbing de fixture para el filtro por ancla de filing (F353): asigna
    accn por 10-K (fy+filed, compartido por las filas TTM/segmentos que
    viajan en el mismo filing) y devuelve las anclas {accn: reportDate} de
    los cierres reales (filas 300-380d del mes de cierre del emisor)."""
    anchors = {}
    for concept in payload["facts"]["us-gaap"].values():
        for entries in concept["units"].values():
            for e in entries:
                if not str(e.get("form", "")).startswith(("10-K", "20-F")):
                    continue
                accn = f"K{e.get('fy')}-{e.get('filed')}"
                e["accn"] = accn
                start, end = e.get("start"), str(e.get("end") or "")
                if len(end) < 10:
                    continue
                if not start:
                    # Instantaneo (balance): ancla si cierra en el mes real.
                    if end[5:7] == close_month:
                        anchors[accn] = end
                    continue
                try:
                    span = (date.fromisoformat(end) - date.fromisoformat(str(start))).days
                except ValueError:
                    continue
                if 300 <= span <= 380 and end[5:7] == close_month:
                    anchors[accn] = end
    return payload, anchors


def _anchor_fake(cls, close_month):
    """Dota al fake de annual_report_anchors con cache compartida: el payload
    que ve el servicio es el MISMO objeto anotado con accn."""
    original = cls.company_facts

    async def company_facts(self, cik):
        payload = getattr(self, "_cached_payload", None)
        if payload is None:
            payload = await original(self, cik)
            self._cached_payload = payload
        return payload

    async def annual_report_anchors(self, cik):
        anchors = getattr(self, "_cached_anchors", None)
        if anchors is None:
            _, anchors = _with_anchors(await self.company_facts(cik), close_month)
            self._cached_anchors = anchors
        return anchors

    cls.company_facts = company_facts
    cls.annual_report_anchors = annual_report_anchors
    return cls


_anchor_fake(_FakeSECAKAM, "12")
_anchor_fake(_FakeSECDTE, "12")
