"""Tag neto de intereses no operativos (CHTR) y coste de deuda reportado.

CHTR dejo de usar ``InterestExpense`` en 2015 y desde Q3-2024 reporta el
gasto financiero en ``InterestIncomeExpenseNonoperatingNet`` con signo
NEGATIVO (-5.042 M$ FY2025, 10-K filed 2026-01-30); ademas reporta
``DebtWeightedAverageInterestRate`` (0,051 FY2025, unidad "pure"). Sin
mapear ninguno de los dos, el gasto ingerido mas reciente era FY2013 y el
WACC se calculaba con 12 anos de desfase (test_wacc_gasto_financiero_desfasado).

Reglas generales que fijan estos tests (cualquier emisor):
- el tag neto solo aporta ``interest_expense`` cuando es NEGATIVO (gasto),
  y se guarda en positivo; POSITIVO es ingreso financiero neto, no es
  gasto y se descarta (sin dato = N/D, nunca se convierte ingreso en gasto);
- ``DebtWeightedAverageInterestRate`` se ingiere como ``cost_of_debt``
  reportado y el motor lo toma como ``reported_cost_of_debt``.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.metric_calculation_service import MetricCalculationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="CABLERA"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NMS", currency="USD",
        sector="Communication Services", industry="Telecom Services",
        company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fy(start_year, val, filed, form="10-K"):
    return {
        "fy": start_year, "fp": "FY", "form": form,
        "start": f"{start_year}-01-01", "end": f"{start_year}-12-31",
        "val": val, "filed": filed,
    }


def _annotate_anchors(payload):
    """Accn por 10-K y anclas {accn: cierre} sobre EL MISMO objeto payload:
    el servicio ingiere el objeto que company_facts devuelve, asi que la
    anotacion tiene que quedar en esa misma instancia (patron de
    test_sec_cash_fallback._anchor_fake)."""
    anchors = {}
    for concept in payload["facts"]["us-gaap"].values():
        for entries in concept["units"].values():
            for e in entries:
                if not str(e.get("form", "")).startswith(("10-K", "20-F")):
                    continue
                accn = f"K{e.get('fy')}-{e.get('filed')}"
                e["accn"] = accn
                if str(e.get("end") or "")[5:7] == "12":
                    anchors[accn] = e["end"]
    return anchors


class _FakeSECClientBase:
    _payload = None
    _anchors = None

    async def company_facts(self, cik):
        if type(self)._payload is None:
            type(self)._payload = self._build_payload()
            type(self)._anchors = _annotate_anchors(type(self)._payload)
        return type(self)._payload

    async def annual_report_anchors(self, cik):
        await self.company_facts(cik)
        return type(self)._anchors


class _FakeSECClientCable(_FakeSECClientBase):
    """Tipo CHTR: InterestExpense muerto en FY2013; desde FY2024 el gasto
    viaja en InterestIncomeExpenseNonoperatingNet (negativo) y reporta
    DebtWeightedAverageInterestRate. FY2012 con el tag neto POSITIVO
    (ingreso neto): no debe generar interest_expense."""

    async def cik_for_ticker(self, ticker):
        return "0001091667"

    def _build_payload(self):
        return {
            "facts": {
                "us-gaap": {
                    "InterestExpense": {"units": {"USD": [
                        _fy(2013, 846000000, "2014-02-14"),
                    ]}},
                    "InterestIncomeExpenseNonoperatingNet": {"units": {"USD": [
                        _fy(2012, 50000000, "2013-02-15"),
                        _fy(2024, -5229000000, "2025-01-31"),
                        _fy(2025, -5042000000, "2026-01-30"),
                        {"fy": 2026, "fp": "Q1", "form": "10-Q",
                         "start": "2026-01-01", "end": "2026-03-31",
                         "val": -1256000000, "filed": "2026-04-24"},
                    ]}},
                    # Sonda de divisa de reporte: sin un concepto sonda
                    # (Assets, Revenues, ...) la divisa no resuelve y el
                    # servicio salta TODAS las metricas monetarias.
                    "Assets": {"units": {"USD": [
                        {"fy": 2024, "fp": "FY", "form": "10-K",
                         "end": "2024-12-31", "val": 150000000000, "filed": "2025-01-31"},
                        {"fy": 2025, "fp": "FY", "form": "10-K",
                         "end": "2025-12-31", "val": 151000000000, "filed": "2026-01-30"},
                    ]}},
                    "DebtWeightedAverageInterestRate": {"units": {"pure": [
                        {"fy": 2025, "fp": "FY", "form": "10-K",
                         "end": "2025-12-31", "val": 0.051, "filed": "2026-01-30"},
                    ]}},
                }
            }
        }


def _refresh(db, company, client_cls):
    import unittest.mock as mock

    with mock.patch.object(ingestion, "SECClient", client_cls):
        service = FinancialIngestionService()
        asyncio.run(service.refresh_from_sec(db=db, company=company))


def _facts(db, company, metric):
    return list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == metric,
        )
    ))


def test_tag_neto_negativo_entra_como_gasto_en_positivo(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientCable)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    by_year = {f.fiscal_year: f for f in _facts(db, company, "interest_expense")}
    assert by_year[2013].value == Decimal("846000000")     # tag viejo, historia intacta
    assert by_year[2024].value == Decimal("5229000000")    # neto negativo -> gasto positivo
    assert by_year[2025].value == Decimal("5042000000")
    assert 2012 not in by_year                             # neto POSITIVO: ingreso, no gasto


def test_tag_neto_trimestral_tambien_pasa_la_puerta(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientCable)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    quarterlies = [f for f in _facts(db, company, "interest_expense") if f.fiscal_quarter != "FY"]
    assert any(f.value == Decimal("1256000000") for f in quarterlies)


def test_coste_de_deuda_reportado_se_ingiere_como_cost_of_debt(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientCable)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = _facts(db, company, "cost_of_debt")
    assert len(facts) == 1
    assert facts[0].value == Decimal("0.051")
    assert facts[0].unit == "pure"
    assert facts[0].fiscal_year == 2025


class _FakeSECClientSoloIngresoNeto(_FakeSECClientBase):
    """Emisor con el tag neto siempre POSITIVO (ingreso financiero neto):
    no hay gasto que ingerir y no se inventa."""

    async def cik_for_ticker(self, ticker):
        return "0009999999"

    def _build_payload(self):
        return {"facts": {"us-gaap": {
            "Assets": {"units": {"USD": [
                {"fy": 2025, "fp": "FY", "form": "10-K",
                 "end": "2025-12-31", "val": 1000000000, "filed": "2026-01-30"},
            ]}},
            "InterestIncomeExpenseNonoperatingNet": {"units": {"USD": [
                _fy(2024, 300000000, "2025-02-01"),
                _fy(2025, 350000000, "2026-01-30"),
            ]}},
        }}}


def test_tag_neto_positivo_no_genera_gasto(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientSoloIngresoNeto)
    company = _company(db, ticker="NETINC")
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    assert _facts(db, company, "interest_expense") == []


def _fact(company, metric, value, *, year=2025, source_type="wacc_test", unit="pure"):
    return FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(value),
        unit=unit,
        period=f"{year}-12-31:FY",
        fiscal_year=year,
        fiscal_quarter="FY",
        source_type=source_type,
        is_reported=True,
        confidence=Decimal("0.90"),
    )


def test_wacc_usa_el_coste_de_deuda_reportado(db):
    """Con cost_of_debt reportado el WACC no deriva gasto/deuda."""
    company = _company(db, ticker="CABWACC")
    rows = [
        _fact(company, "risk_free_rate", "0.0511"),
        _fact(company, "beta", "0.687"),
        _fact(company, "equity_risk_premium", "0.0433"),
        _fact(company, "country_risk_premium", "0"),
        _fact(company, "effective_tax_rate", "0.227"),
        _fact(company, "total_debt", "94756000000", source_type="SEC", unit="USD"),
        _fact(company, "market_cap", "15276516352", source_type="yfinance", unit="USD"),
        _fact(company, "cost_of_debt", "0.051", source_type="SEC"),
    ]
    db.add_all(rows)
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "ok"
    trace = result.calculation_trace
    assert trace["cost_of_debt_source"] == "reported_cost_of_debt"
    assert Decimal(trace["cost_of_debt"]) == pytest.approx(Decimal("0.051"))


class _FakeSECClientBanco(_FakeSECClientBase):
    """Tipo MS (bank_like): su InterestExpense real es FY2023 (42.051 M$) y
    el tag neto no operativo FY2024/25 (-109 M$) es un residuo de otro
    alcance. La guarda bank_like lo excluye: los anos sin tag estricto
    quedan N/D, no se rellenan con el residuo."""

    async def cik_for_ticker(self, ticker):
        return "0000895421"

    def _build_payload(self):
        return {"facts": {"us-gaap": {
            "Assets": {"units": {"USD": [
                {"fy": 2025, "fp": "FY", "form": "10-K",
                 "end": "2025-12-31", "val": 1300000000000, "filed": "2026-02-01"},
            ]}},
            "InterestExpense": {"units": {"USD": [
                _fy(2023, 42051000000, "2024-02-01"),
            ]}},
            "InterestIncomeExpenseNonoperatingNet": {"units": {"USD": [
                _fy(2024, -109000000, "2025-02-01"),
                _fy(2025, -109000000, "2026-02-01"),
            ]}},
        }}}


def test_banco_no_rellena_gasto_con_el_residuo_neto_no_operativo(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientBanco)
    company = _company(db, ticker="BANX")
    company.industry = "Capital Markets"
    db.commit()
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    by_year = {f.fiscal_year: f for f in _facts(db, company, "interest_expense")}
    assert by_year[2023].value == Decimal("42051000000")
    assert 2024 not in by_year and 2025 not in by_year  # N/D, nunca el residuo
