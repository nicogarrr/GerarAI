"""SEC refresh conflict detection: batched FMP matching + honest conflicts.

The SEC/FMP reconciliation must flag material divergences (>5%) without one
query per SEC fact.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture
def db():
    # StaticPool + check_same_thread=False: el endpoint refresh/sec ejecuta
    # su trabajo en un hilo del pool (run_in_threadpool) y esta sesion debe
    # poder usarse secuencialmente desde ese hilo sin perder la BD en memoria.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAA", name="AAA", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _FakeSECClient:
    async def cik_for_ticker(self, ticker):
        return "0001234567"

    async def company_facts(self, cik):
        entries = [
            {"fy": year, "fp": "FY", "form": "10-K", "end": f"{year}-12-31", "val": value}
            for year, value in [(2024, 1000), (2023, 900)]
        ]
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": entries}},
                    "GrossProfit": {"units": {"USD": entries}},
                }
            }
        }


def _fmp_fact(db, company, metric, period, value):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="USD", period=period, fiscal_year=int(period[:4]), source_type="FMP",
    ))
    db.commit()


def test_conflicts_flagged_with_one_fmp_query(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClient)
    company = _company(db)
    # Matching period, >5% divergence on revenue; gross_profit matches.
    _fmp_fact(db, company, "revenue", "2024-12-31:FY", 1200)
    _fmp_fact(db, company, "gross_profit", "2024-12-31:FY", 1010)

    statements = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        result = asyncio.run(FinancialIngestionService().refresh_from_sec(db, company))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)

    assert result["status"] == "ingested"
    assert result["facts_imported"] == 5  # 4 brutos + revenue_growth derivado
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0].startswith("revenue:2024-12-31:FY FMP=1200 SEC=1000")
    # One SEC-facts read + one batched FMP lookup, not one query per SEC fact
    # (old code issued 1 + 4 for this fixture).
    fact_selects = [
        s for s in statements
        if s.lstrip().upper().startswith("SELECT") and "financial_facts" in s
    ]
    assert len(fact_selects) == 4  # batch conflictos + lectura de derivadas + sync de chunks RAG (1 query batched, sin N+1)


def test_refresh_sec_endpoint_encaja_con_response_model(db, monkeypatch):
    """La respuesta del endpoint refresh/sec debe validar contra
    FinancialRefreshResponse (bug: faltaban statements_imported,
    latest_periods y valuation_input_ready y devolvia 500 pese a ingerir)."""
    from app.api.routes.companies import refresh_sec_financials
    from app.schemas.api import FinancialRefreshResponse

    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClient)
    _company(db)

    result = asyncio.run(refresh_sec_financials("AAA", db))
    parsed = FinancialRefreshResponse(**result)
    assert parsed.provider == "SEC"
    assert parsed.facts_imported > 0
    assert parsed.statements_imported == 0
    assert "revenue" in parsed.latest_periods


class _FakeSECClientMultiyear:
    async def cik_for_ticker(self, ticker):
        return "0001234567"

    async def company_facts(self, cik):
        def entries(values_by_year):
            return [
                {"fy": year, "fp": "FY", "form": "10-K", "end": f"{year}-12-31", "val": value}
                for year, value in values_by_year.items()
            ]
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": entries({2023: 1000, 2024: 1200, 2025: 1500})}},
                    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": entries({2024: 300, 2025: 400})}},
                    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": entries({2024: 100, 2025: 120})}},
                    "LongTermDebt": {"units": {"USD": entries({2025: 500})}},
                    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": entries({2025: 200})}},
                    "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": entries({2025: 100})}},
                }
            }
        }


def test_sec_refresh_deriva_fcf_margen_crecimiento_y_deuda_neta(db, monkeypatch):
    """Sin metricas derivadas el snapshot de valoracion queda
    insufficient_data: FCF = OCF + capex(neg), margen, crecimiento, net debt."""
    from app.services.financial_ingestion_service import FinancialIngestionService as FIS

    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientMultiyear)
    company = _company(db)

    service = FIS()
    result = asyncio.run(service.refresh_from_sec(db, company))
    assert result["status"] == "ingested"

    facts = {
        (f.metric, f.fiscal_year): f
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type == "SEC",
            )
        )
    }
    fcf25 = facts[("free_cash_flow", 2025)]
    assert fcf25.value == Decimal("280")  # 400 - 120
    assert fcf25.is_reported is False
    assert fcf25.unit == "USD"
    assert facts[("free_cash_flow", 2024)].value == Decimal("200")
    assert abs(facts[("fcf_margin", 2025)].value - Decimal("280") / Decimal("1500")) < Decimal("0.000001")
    assert abs(facts[("revenue_growth", 2025)].value - (Decimal("1500") / Decimal("1200") - 1)) < Decimal("0.000001")
    assert ("revenue_growth", 2023) not in facts  # sin ano previo no hay crecimiento
    assert facts[("net_debt", 2025)].value == Decimal("300")  # 500 - 200
    # valuation_input_ready (revenue + FCF + shares) ya se satisface
    assert service.valuation_input_ready(db, company) is True


class _FakeSECClientFilingYear:
    """Simula el formato real companyfacts: fy = anio del filing, no del dato,
    con el mismo periodo re-presentado en varios 10-K."""

    async def cik_for_ticker(self, ticker):
        return "0001234567"

    async def company_facts(self, cik):
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [
                        {"fy": 2023, "fp": "FY", "form": "10-K", "end": "2023-12-31", "val": 1000, "filed": "2024-02-01"},
                        {"fy": 2024, "fp": "FY", "form": "10-K", "end": "2023-12-31", "val": 999, "filed": "2025-02-01"},
                        {"fy": 2024, "fp": "FY", "form": "10-K", "end": "2024-12-31", "val": 1200, "filed": "2025-02-01"},
                    ]}},
                }
            }
        }


def test_sec_fiscal_year_sale_del_end_y_manda_el_filed_reciente(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientFilingYear)
    company = _company(db)

    asyncio.run(FinancialIngestionService().refresh_from_sec(db, company))

    revenues = [
        f for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "revenue",
            )
        )
    ]
    by_year = {f.fiscal_year: f for f in revenues}
    assert set(by_year) == {2023, 2024}  # NO 2023-duplicado-como-2024
    assert by_year[2023].value == Decimal("999")  # re-presentacion mas reciente
    assert by_year[2023].period == "2023-12-31:FY"
    assert by_year[2024].value == Decimal("1200")
    # crecimiento derivado con los anos correctos
    growth = [
        f for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "revenue_growth",
            )
        )
    ]
    assert len(growth) == 1
    assert abs(growth[0].value - (Decimal("1200") / Decimal("999") - 1)) < Decimal("0.000001")


class _StaleAliasSECClient:
    """El tag antiguo (Revenues) quedo congelado en 2010; el revenue actual
    vive en RevenueFromContractWithCustomerExcludingAssessedTax (caso MSFT
    real, detectado en prod 24/9)."""

    async def cik_for_ticker(self, ticker):
        return "0000789019"

    async def company_facts(self, cik):
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"fy": 2010, "fp": "FY", "form": "10-K",
                                 "end": "2010-06-30", "val": 62484,
                                 "filed": "2010-07-30"},
                            ]
                        }
                    },
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {"fy": 2025, "fp": "FY", "form": "10-K",
                                 "end": "2025-06-30", "val": 281724,
                                 "filed": "2025-07-29"},
                                {"fy": 2024, "fp": "FY", "form": "10-K",
                                 "end": "2024-06-30", "val": 245122,
                                 "filed": "2024-07-30"},
                                # mismo periodo re-presentado en el 10-K de
                                # 2025 (recast): gana el filed mas reciente
                                {"fy": 2025, "fp": "FY", "form": "10-K",
                                 "end": "2024-06-30", "val": 245200,
                                 "filed": "2025-07-29"},
                            ]
                        }
                    },
                }
            }
        }


def test_alias_antiguo_no_tapa_datos_recientes(db, monkeypatch):
    """Fusion de alias por periodo: historia antigua conservada, periodos
    recientes importados, mismo periodo bajo dos tags una sola vez."""
    monkeypatch.setattr(ingestion, "SECClient", _StaleAliasSECClient)
    company = _company(db)

    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db, company))

    assert result["status"] == "ingested"
    revenue = db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
        )
    ).all()
    periods = {f.period: float(f.value) for f in revenue}
    assert periods["2010-06-30:FY"] == 62484      # historia del tag antiguo
    assert periods["2025-06-30:FY"] == 281724     # periodo reciente del tag nuevo
    assert periods["2024-06-30:FY"] == 245200     # recast: filed mas reciente
    assert len(revenue) == 3                      # sin duplicar el periodo


def _with_anchors(payload, close_month):
    """Plumbing de fixture para el filtro por ancla de filing (F353): asigna
    accn por 10-K (fy+filed, compartido por las filas TTM/segmentos que
    viajan en el mismo filing) y devuelve las anclas {accn: reportDate} de
    los cierres reales (flows 300-380d e instantaneos del mes del emisor)."""
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


_anchor_fake(_FakeSECClient, "12")
_anchor_fake(_FakeSECClientMultiyear, "12")
_anchor_fake(_FakeSECClientFilingYear, "12")
_anchor_fake(_StaleAliasSECClient, "06")
