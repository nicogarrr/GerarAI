"""F28: hechos de flujo con fp="FY" pero duracion trimestral (segmentos que la
SEC incluye en los 10-K) NO deben entrar como ejercicio anual. Caso real AAPL
FY2020: revenue 2020-03-28 (91 dias, Q2) quedo grabado como :FY (58,31 mil M)
y desplazo/corrompio el FY2020 real (274,515 mil M) y sus derivados.
Regla: anual = duracion 300-380 dias (como la via ESEF)."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


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
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _FakeSECAAPL:
    """AAPL-like: el 10-K de FY2020 trae fp=FY con duraciones mezcladas:
    el ejercicio completo (363 dias) y segmentos de Q2 (91 d) y Q4 (90 d)."""

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0000320193"

    async def company_facts(self, cik):
        rev = "RevenueFromContractWithCustomerExcludingAssessedTax"
        return {"facts": {"us-gaap": {rev: {"units": {"USD": [
            {"fy": 2019, "fp": "FY", "form": "10-K", "start": "2018-09-30",
             "end": "2019-09-28", "val": 260_174_000_000, "filed": "2019-10-31"},
            {"fy": 2020, "fp": "FY", "form": "10-K", "start": "2019-09-29",
             "end": "2020-09-26", "val": 274_515_000_000, "filed": "2020-10-30"},
            {"fy": 2020, "fp": "FY", "form": "10-K", "start": "2019-12-29",
             "end": "2020-03-28", "val": 58_313_000_000, "filed": "2020-10-30"},
            {"fy": 2020, "fp": "FY", "form": "10-K", "start": "2020-06-28",
             "end": "2020-09-26", "val": 64_698_000_000, "filed": "2020-10-30"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2020-09-27",
             "end": "2021-09-25", "val": 365_817_000_000, "filed": "2021-10-29"},
        ]}}}}}


def test_quarterly_segments_with_fp_fy_are_not_ingested_as_annual(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECAAPL)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
            FinancialFact.is_reported.is_(True),
        )
    ))
    periods = {f.period: f.value for f in facts}
    assert periods.get("2019-09-28:FY") == Decimal("260174000000")
    assert periods.get("2020-09-26:FY") == Decimal("274515000000")
    assert periods.get("2021-09-25:FY") == Decimal("365817000000")
    # Los segmentos trimestrales etiquetados fp=FY quedan fuera:
    assert "2020-03-28:FY" not in periods
    # El ejercicio 2020 es el completo, no el segmento de Q4 (mismo `end`):
    by_year = {f.fiscal_year: f.value for f in facts}
    assert by_year[2020] == Decimal("274515000000")


class _FakeSECCalendarTTM:
    """Emisor de ano natural: el 10-K incluye acumulados TTM de ~365 dias que
    cierran en fin de trimestre (caso real AA/AAL 2020). Superan el filtro de
    duracion, pero su mes de cierre no es el modal del emisor (diciembre)."""

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0001675149"

    async def company_facts(self, cik):
        rev = "RevenueFromContractWithCustomerExcludingAssessedTax"
        return {"facts": {"us-gaap": {rev: {"units": {"USD": [
            {"fy": 2019, "fp": "FY", "form": "10-K", "start": "2018-01-01",
             "end": "2018-12-31", "val": 100, "filed": "2019-02-15"},
            {"fy": 2020, "fp": "FY", "form": "10-K", "start": "2019-01-01",
             "end": "2019-12-31", "val": 110, "filed": "2020-02-14"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2020-01-01",
             "end": "2020-12-31", "val": 120, "filed": "2021-02-12"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2019-04-01",
             "end": "2020-03-31", "val": 999, "filed": "2021-02-12"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2019-07-01",
             "end": "2020-06-30", "val": 998, "filed": "2021-02-12"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2019-10-01",
             "end": "2020-09-30", "val": 997, "filed": "2021-02-12"},
        ]}}}}}


def test_ttm_accumulates_ending_at_quarter_ends_are_rejected(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECCalendarTTM)
    company = _company(db, "AA")
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
            FinancialFact.is_reported.is_(True),
        )
    ))
    periods = {f.period for f in facts}
    assert periods == {"2018-12-31:FY", "2019-12-31:FY", "2020-12-31:FY"}
    assert not any(p.endswith(("03-31:FY", "06-30:FY", "09-30:FY")) for p in periods)


class _FakeSECWeekFiscal:
    """Ejercicio de 52/53 semanas (cierre el ultimo sabado de septiembre):
    el dia exacto del cierre varia cada ano; el filtro modal por MES debe
    conservarlos todos y rechazar el TTM de marzo."""

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0000320193"

    async def company_facts(self, cik):
        rev = "RevenueFromContractWithCustomerExcludingAssessedTax"
        return {"facts": {"us-gaap": {rev: {"units": {"USD": [
            {"fy": 2019, "fp": "FY", "form": "10-K", "start": "2017-10-01",
             "end": "2018-09-29", "val": 265, "filed": "2018-11-05"},
            {"fy": 2020, "fp": "FY", "form": "10-K", "start": "2018-09-30",
             "end": "2019-09-28", "val": 260, "filed": "2019-10-31"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2019-09-29",
             "end": "2020-09-26", "val": 274, "filed": "2020-10-30"},
            {"fy": 2021, "fp": "FY", "form": "10-K", "start": "2019-03-31",
             "end": "2020-03-28", "val": 999, "filed": "2020-10-30"},
        ]}}}}}


def test_52_53_week_fiscal_year_ends_are_all_kept(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECWeekFiscal)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
            FinancialFact.is_reported.is_(True),
        )
    ))
    periods = {f.period for f in facts}
    assert periods == {"2018-09-29:FY", "2019-09-28:FY", "2020-09-26:FY"}


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


_anchor_fake(_FakeSECAAPL, "09")
_anchor_fake(_FakeSECCalendarTTM, "12")
_anchor_fake(_FakeSECWeekFiscal, "09")
