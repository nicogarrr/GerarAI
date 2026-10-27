"""Punto 3/6: ingesta de trimestres desde los 10-Q. Reglas:
- fp Q1-Q4 + form 10-Q; flujo = 70-110 dias (trimestre real). Los acumulados
  YTD (~180 dias), los TTM (~365 dias) y cualquier cosa en form 10-K quedan
  fuera. Los instantaneos de balance (sin start) pasan.
- fiscal_year=NULL deliberado: los consumidores anuales seleccionan por
  fiscal_year (u ordenan con nullslast), asi una fila :Q2 nunca compite con
  el ejercicio anual. period = "<end>:Q<n>", fiscal_quarter = Q1-Q4."""

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


def _company(db, ticker="ACME"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _FakeSECQuarterly:
    """10-K con el FY2024 y 10-Q con: Q1 real (90d), Q2 real (91d) duplicado
    en dos filings (manda el filed mas reciente), YTD de Q2 (181d, fuera),
    TTM (365d, fuera), segmento mensual (31d, fuera) y balance instantaneo."""

    async def cik_for_ticker(self, ticker):
        return "0009999999"

    async def company_facts(self, cik):
        rev = "RevenueFromContractWithCustomerExcludingAssessedTax"
        eq = "StockholdersEquity"
        return {"facts": {"us-gaap": {
            rev: {"units": {"USD": [
                {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2024-01-01",
                 "end": "2024-12-31", "val": 1000, "filed": "2025-02-10"},
                {"fy": 2025, "fp": "Q1", "form": "10-Q", "start": "2025-01-01",
                 "end": "2025-03-31", "val": 260, "filed": "2025-05-01"},
                {"fy": 2025, "fp": "Q2", "form": "10-Q", "start": "2025-04-01",
                 "end": "2025-06-30", "val": 270, "filed": "2025-08-01"},
                {"fy": 2025, "fp": "Q2", "form": "10-Q", "start": "2025-04-01",
                 "end": "2025-06-30", "val": 275, "filed": "2025-08-15"},
                {"fy": 2025, "fp": "Q2", "form": "10-Q", "start": "2025-01-01",
                 "end": "2025-06-30", "val": 530, "filed": "2025-08-01"},
                {"fy": 2025, "fp": "Q2", "form": "10-Q", "start": "2024-07-01",
                 "end": "2025-06-30", "val": 9999, "filed": "2025-08-01"},
                {"fy": 2025, "fp": "Q2", "form": "10-Q", "start": "2025-05-01",
                 "end": "2025-05-31", "val": 90, "filed": "2025-08-01"},
                {"fy": 2025, "fp": "Q2", "form": "10-K", "start": "2025-04-01",
                 "end": "2025-06-30", "val": 8888, "filed": "2026-02-10"},
            ]}},
            eq: {"units": {"USD": [
                {"fy": 2025, "fp": "Q2", "form": "10-Q",
                 "end": "2025-06-30", "val": 5000, "filed": "2025-08-01"},
            ]}},
        }}}


def _facts(db, company, metric):
    return list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == metric,
            FinancialFact.is_reported.is_(True),
        )
    ))


def test_quarters_ingested_with_null_fiscal_year(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECQuarterly)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    revenue = _facts(db, company, "revenue")
    quarterly = {f.period: f for f in revenue if f.period.endswith((":Q1", ":Q2", ":Q3", ":Q4"))}
    assert set(quarterly) == {"2025-03-31:Q1", "2025-06-30:Q2"}
    # Manda el filed mas reciente (275, no 270):
    assert quarterly["2025-06-30:Q2"].value == Decimal("275")
    for fact in quarterly.values():
        assert fact.fiscal_year is None
        assert fact.fiscal_quarter in {"Q1", "Q2"}
    # El anual sigue igual:
    annual = [f for f in revenue if f.period.endswith(":FY")]
    assert len(annual) == 1 and annual[0].value == Decimal("1000")
    assert annual[0].fiscal_year == 2024
    # Balance instantaneo trimestral:
    equity = _facts(db, company, "total_equity")
    assert [f.period for f in equity] == ["2025-06-30:Q2"]
    assert equity[0].fiscal_year is None


def test_annual_consumers_do_not_see_quarters(db, monkeypatch):
    """_derive_sec_metrics indexa por fiscal_year: con NULL las filas :Qn
    no entran en derivados anuales (FCF, crecimiento, deuda neta)."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECQuarterly)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    derived = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.is_reported.is_(False),
        )
    ))
    for fact in derived:
        assert fact.period.endswith(":FY")


class _FakeSECFilingPeriodFp:
    """Caso real AAPL (F157): el `fp` de companyfacts es el periodo fiscal DE
    LA PRESENTACION, no del dato. Las comparativas trimestrales dentro del 10-Q
    de Q1 del FY2018 llevan fp=Q1 aunque el dividendo se pago en abril (Q2
    fiscal de Apple, ejercicio cerrando en septiembre). La copia mas reciente
    (`filed` mayor) es la que sobrevive la deduplicacion, asi que confiar en
    fp etiqueta TODOS los trimestres como Q1. La etiqueta se deriva del cierre
    del periodo contra el mes modal de cierre de ejercicio (septiembre)."""

    async def cik_for_ticker(self, ticker):
        return "0000320193"

    async def company_facts(self, cik):
        div = "PaymentsOfDividendsCommonStock"
        return {"facts": {"us-gaap": {
            # Evidencia explicita de divisa de reporte, no fallback por ticker.
            "Assets": {"units": {"USD": [{"val": 1}]}},
            div: {"units": {"USD": [
                {"fy": 2017, "fp": "FY", "form": "10-K", "start": "2016-09-25",
                 "end": "2017-09-30", "val": 12769000000, "filed": "2017-11-03"},
                # Trimestre pagado en abril: fiscal Q2 de Apple. La copia del
                # 10-Q de Q3 FY2017 (fp=Q3) pierde contra la comparativa del
                # 10-Q de Q1 FY2018 (fp=Q1, filed posterior): ambas describen
                # el mismo dividendo; fp no es la etiqueta del periodo.
                {"fy": 2017, "fp": "Q3", "form": "10-Q", "start": "2017-01-01",
                 "end": "2017-04-01", "val": 2988000000, "filed": "2017-08-02"},
                {"fy": 2018, "fp": "Q1", "form": "10-Q", "start": "2017-01-01",
                 "end": "2017-04-01", "val": 2988000000, "filed": "2018-02-02"},
                # Julio: fiscal Q3.
                {"fy": 2018, "fp": "Q1", "form": "10-Q", "start": "2017-04-02",
                 "end": "2017-07-01", "val": 3281000000, "filed": "2018-02-02"},
                # Diciembre: fiscal Q1 (unico que fp acertaba por casualidad).
                {"fy": 2018, "fp": "Q1", "form": "10-Q", "start": "2017-10-01",
                 "end": "2017-12-30", "val": 3339000000, "filed": "2018-02-02"},
            ]}},
        }}}


def test_quarter_label_comes_from_fiscal_calendar_not_filing_fp(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECFilingPeriodFp)
    company = _company(db, "AAPL")
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))
    rows = _facts(db, company, "dividends_paid")
    by_period = {r.period: r for r in rows}
    assert "2017-04-01:Q2" in by_period
    assert "2017-07-01:Q3" in by_period
    assert "2017-12-30:Q1" in by_period
    assert not any(p.endswith(":Q1") and not p.startswith("2017-12-30") for p in by_period if ":Q" in p)
    assert by_period["2017-04-01:Q2"].fiscal_quarter == "Q2"
    assert by_period["2017-04-01:Q2"].value == Decimal("2988000000")


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


_anchor_fake(_FakeSECQuarterly, "12")
_anchor_fake(_FakeSECFilingPeriodFp, "12")


def test_ambiguous_sec_currency_does_not_create_monetary_facts(db, monkeypatch):
    class AmbiguousSEC(_FakeSECQuarterly):
        async def company_facts(self, cik):
            payload = await super().company_facts(cik)
            gaap = payload["facts"]["us-gaap"]
            for concept in gaap.values():
                units = concept.get("units", {})
                if "USD" in units:
                    units["EUR"] = [dict(row) for row in units["USD"]]
            return payload

    monkeypatch.setattr(ingestion, "SECClient", AmbiguousSEC)
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    rows = list(db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)))
    assert not any(f.unit in {"USD", "EUR", "USD/share", "EUR/share"} for f in rows)
