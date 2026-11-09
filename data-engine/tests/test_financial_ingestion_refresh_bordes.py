"""Bordes de financial_ingestion_service.py (lote A4): flujos refresh.

Flujos completos refresh_from_fmp / refresh_from_sec / refresh_from_esef con
fakes de cliente (precedente: tests/test_ingest_service_guards.py) y SQLite
real en memoria. Datos sinteticos, sin red.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="ACME", name=None, exchange="NASDAQ", currency="USD"):
    company = Company(
        ticker=ticker,
        name=name or ticker,
        exchange=exchange,
        currency=currency,
        sector="Technology",
        industry="Software",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


# --- refresh_from_fmp (1913-1914 fillingDate, 1920-1926 published_at) ---


class _FakeFMPConFechasDePublicacion:
    """Dos filas con fillingDate distintas: la publicacion del documento es
    el MAXIMO (un hecho no puede apuntar a un documento publicado antes que
    el propio hecho)."""

    async def income_statement(self, ticker, limit=5):
        return [
            {
                "symbol": "ACME",
                "date": "2025-12-31",
                "period": "FY",
                "calendarYear": 2025,
                "revenue": 100,
                "fillingDate": "2026-02-15",
            },
            {
                "symbol": "ACME",
                "date": "2024-12-31",
                "period": "FY",
                "calendarYear": 2024,
                "revenue": 90,
                "fillingDate": "2026-03-10",
            },
        ]

    async def balance_sheet(self, ticker, limit=5):
        return []

    async def cash_flow(self, ticker, limit=5):
        return []

    async def ratios(self, ticker, limit=5):
        return []

    async def company_profile(self, ticker):
        return []

    async def quote(self, ticker):
        return []


def test_refresh_from_fmp_publica_el_documento_en_el_filling_mas_reciente(db):
    """1913-1914 y 1920-1926: con fillingDates parseables, published_at es el
    maximo a medianoche UTC (el eje de publicacion del guard point-in-time)."""
    company = _company(db)
    asyncio.run(
        FinancialIngestionService().refresh_from_fmp(db, company, client=_FakeFMPConFechasDePublicacion())
    )
    document = db.scalar(
        select(Document).where(Document.company_id == company.id, Document.source_type == "FMP")
    )
    assert document is not None
    # SQLite devuelve el DateTime sin tzinfo (mismo instante, representacion naive).
    assert document.published_at.replace(tzinfo=UTC) == datetime(2026, 3, 10, tzinfo=UTC)


# --- refresh_from_sec (bucles trimestral/anual, dei, hooks best-effort) ---


class _FakeSECBordes:
    """Un solo companyfacts que ejercita los guards de los bucles SEC:
    valores no decimales (2299/2364), caja con tag combinado que anula las
    inversiones a corto plazo del mismo cierre (2303/2368), capex trimestral
    con signo negado (2305) y portada dei con tres guards (2450, 2452->2438,
    2460)."""

    async def cik_for_ticker(self, ticker):
        return "0000000001"

    async def company_facts(self, cik):
        return {
            "cik": 1,
            "entityName": "ACME",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "val": "no-numero",
                                    "filed": "2026-02-10",
                                    "accn": "0000000001-25-000001",
                                },
                                {
                                    "fy": 2025,
                                    "fp": "Q3",
                                    "form": "10-Q",
                                    "start": "2025-07-01",
                                    "end": "2025-09-30",
                                    "val": "no-numero",
                                    "filed": "2025-11-05",
                                    "accn": "0000000001-25-000002",
                                },
                            ]
                        }
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {
                                    "fy": 2025,
                                    "fp": "Q3",
                                    "form": "10-Q",
                                    "start": "2025-07-01",
                                    "end": "2025-09-30",
                                    "val": 20,
                                    "filed": "2025-11-05",
                                    "accn": "0000000001-25-000002",
                                },
                            ]
                        }
                    },
                    "CashCashEquivalentsAndShortTermInvestments": {
                        "units": {
                            "USD": [
                                {
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "end": "2025-12-31",
                                    "val": 1000,
                                    "filed": "2026-02-10",
                                    "accn": "0000000001-25-000001",
                                },
                                {
                                    "fy": 2025,
                                    "fp": "Q3",
                                    "form": "10-Q",
                                    "end": "2025-09-30",
                                    "val": 900,
                                    "filed": "2025-11-05",
                                    "accn": "0000000001-25-000002",
                                },
                            ]
                        }
                    },
                    "ShortTermInvestments": {
                        "units": {
                            "USD": [
                                {
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "end": "2025-12-31",
                                    "val": 400,
                                    "filed": "2026-02-10",
                                    "accn": "0000000001-25-000001",
                                },
                                {
                                    "fy": 2025,
                                    "fp": "Q3",
                                    "form": "10-Q",
                                    "end": "2025-09-30",
                                    "val": 300,
                                    "filed": "2025-11-05",
                                    "accn": "0000000001-25-000002",
                                },
                            ]
                        }
                    },
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                # Sin end: 2450 (tras pasar forma e indice).
                                {
                                    "form": "10-K",
                                    "accn": "0000000001-25-000010",
                                    "val": 100,
                                    "filed": "2025-11-01",
                                },
                                # Mismo end: el filed mas reciente gana; el otro toma el arco
                                # 2452->2438.
                                {
                                    "form": "10-K",
                                    "accn": "0000000001-25-000010",
                                    "end": "2025-11-15",
                                    "val": 200,
                                    "filed": "2025-11-20",
                                },
                                {
                                    "form": "10-K",
                                    "accn": "0000000001-25-000010",
                                    "end": "2025-11-15",
                                    "val": 100,
                                    "filed": "2025-11-10",
                                },
                                # val <= 0: 2460.
                                {
                                    "form": "10-K",
                                    "accn": "0000000001-25-000010",
                                    "end": "2025-11-16",
                                    "val": -3,
                                    "filed": "2025-11-21",
                                },
                            ]
                        }
                    },
                },
            },
        }

    async def annual_report_anchors(self, cik):
        return {"0000000001-25-000001": "2025-12-31"}

    async def index_accessions(self, cik):
        return {"0000000001-25-000001", "0000000001-25-000002", "0000000001-25-000010"}


def _facts(db, company, metric):
    return list(
        db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id, FinancialFact.metric == metric
            )
        )
    )


def test_refresh_from_sec_guards_de_los_bucles_y_hooks(db, monkeypatch):
    """Guards de los bucles SEC en un solo refresh; hooks best-effort:
    2561-2562 (jev mark_only lanza: la ingesta sigue) y 2575-2576
    (_free_data_snapshot lanza: fallback "unavailable")."""
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECBordes)

    async def _free_data_que_falla(ticker, cik):
        raise RuntimeError("hook caido")

    monkeypatch.setattr(ingestion, "_free_data_snapshot", _free_data_que_falla)

    def _mark_only_que_falla(*args, **kwargs):
        raise RuntimeError("jev caido")

    monkeypatch.setattr("app.services.jev_gates.mark_only", _mark_only_que_falla)

    company = _company(db)
    # Conflicto SEC vs FMP (>5% en la misma metrica y periodo) para que el
    # hook jev tenga algo que marcar (y falle: 2561-2562).
    db.add(
        FinancialFact(
            company_id=company.id,
            metric="cash_and_equivalents",
            value=Decimal("500"),
            unit="USD",
            period="2025-12-31:FY",
            fiscal_year=2025,
            fiscal_quarter="FY",
            source_type="FMP",
            is_reported=True,
            confidence=Decimal("0.9"),
        )
    )
    db.commit()

    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert result["status"] == "ingested"

    # 2305: el capex trimestral se persiste NEGADO (signo de salida de caja).
    capex = _facts(db, company, "capital_expenditure")
    assert [(f.period, f.value) for f in capex] == [("2025-09-30:Q3", Decimal("-20"))]
    # 2303/2368: la caja salio del tag combinado en ambos cierres: las
    # inversiones a corto plazo de esos cierres no se emiten (irian dobles).
    assert _facts(db, company, "short_term_investments") == []
    # La caja si entro, por los dos carriles.
    assert {f.period for f in _facts(db, company, "cash_and_equivalents")} == {
        "2025-12-31:FY",
        "2025-09-30:Q3",
    }
    # 2299/2364: valores no decimales no entran ni al trimestre ni al FY.
    assert _facts(db, company, "revenue") == []
    # dei: gana el filed mas reciente (200), sin duplicar por end.
    shares = _facts(db, company, "shares_outstanding")
    assert [(f.period, f.value) for f in shares] == [("2025-11-15:DEI", Decimal("200"))]

    document = db.scalar(
        select(Document).where(Document.company_id == company.id, Document.source_type == "SEC")
    )
    assert document is not None
    # Conflicto registrado, jev fallo sin romper: no hay jev_anomaly.
    assert document.metadata_["conflicts"]
    assert "jev_anomaly" not in document.metadata_
    # 2575-2576: hook gratuito caido -> fallback declarado.
    assert document.metadata_["free_data"]["status"] == "unavailable"


# --- refresh_from_esef (2783 coverage declarada, 2787 val no decimal) ---


_SNAPSHOT_BORDES = {
    "lei": "L",
    "ticker": "ITX",
    "entity_name": "INDUSTRIA DE DISENO TEXTIL, S.A.",
    "period_end": "2025-01-31",
    "fxo_id": "fxo-1",
    "fetched_at": "2026-09-24",
    "facts": {
        # 2787: instante con val no decimal -> no se publica total_assets.
        "ifrs-full:Assets": {
            "iso4217:EUR": [
                {"instant": "2025-01-31", "val": "no-numero", "decimals": 0, "lei": "L", "dims": []},
            ]
        },
        # 2783: la MISMA parte de capex con DOS valores distintos para el mismo
        # periodo no se puede ranquear sin fecha de filing: periodo ambiguo,
        # se rechaza y queda declarado en esef_coverage.
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": {
            "iso4217:EUR": [
                {
                    "start": "2024-02-01",
                    "end": "2025-01-31",
                    "val": "100",
                    "decimals": 0,
                    "lei": "L",
                    "dims": [],
                },
                {
                    "start": "2024-02-01",
                    "end": "2025-01-31",
                    "val": "200",
                    "decimals": 0,
                    "lei": "L",
                    "dims": [],
                },
            ]
        },
        "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": {
            "iso4217:EUR": [
                {
                    "start": "2024-02-01",
                    "end": "2025-01-31",
                    "val": "50",
                    "decimals": 0,
                    "lei": "L",
                    "dims": [],
                },
            ]
        },
    },
}


def test_refresh_from_esef_declara_periodo_ambiguo_y_salta_valor_no_decimal(db, monkeypatch):
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: _SNAPSHOT_BORDES)
    company = _company(db, ticker="ITX", name="Inditex", exchange="BME", currency="EUR")
    result = asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    assert result["provider"] == "ESEF"
    # 2787: nada de total_assets con un instante no decimal.
    assert _facts(db, company, "total_assets") == []
    # 2783: el periodo ambiguo de capex no se publica y queda declarado.
    assert _facts(db, company, "capital_expenditure") == []
    document = db.scalar(
        select(Document).where(Document.company_id == company.id, Document.source_type == "ESEF")
    )
    assert document is not None
    assert document.metadata_["esef_coverage"]["capital_expenditure"]["ambiguous"] == {
        "2025-01-31": {
            "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": [
                "100",
                "200",
            ]
        }
    }
