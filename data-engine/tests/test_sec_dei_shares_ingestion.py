"""Pasada dei:EntityCommonStockSharesOutstanding (portada 10-K/10-Q).

El saldo de acciones en circulacion se reporta en la portada del filing
(namespace dei), no siempre como hecho us-gaap. Sin esta pasada UNH - con
todo lo demas reportado - salia N/D en dilucion. Los instantes de portada:
- period "<end>:DEI", fiscal_year/fiscal_quarter NULL (nunca compiten con
  el ejercicio anual; _replace_sec_data los re-autoriza en cada refresh).
- Dedup por `end` quedandose el `filed` mas reciente (10-K/A, 10-Q/A).
- Solo 10-K/10-Q/20-F/40-F; nada de 8-K.
- Provenance: capital_fact_provenance[shares_outstanding][<end>:DEI].
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
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


def _company(db, ticker="UNH"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _FakeSECDei:
    """UNH real: dei ECSO en portada 10-K/10-Q; una enmienda 10-Q/A actualiza
    el mismo `end` (manda el filed mas reciente); un 8-K queda fuera."""

    async def cik_for_ticker(self, ticker):
        return "0000731766"

    async def company_facts(self, cik):
        return {"facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"fy": 2025, "fp": "FY", "form": "10-K", "start": "2025-01-01",
                     "end": "2025-12-31", "val": 447600000000, "filed": "2026-03-02"},
                ]}},
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {"units": {"shares": [
                    {"fy": 2025, "fp": "FY", "form": "10-K",
                     "end": "2026-02-20", "val": 907675839, "filed": "2026-03-02"},
                    {"fy": 2026, "fp": "Q1", "form": "10-Q",
                     "end": "2026-04-30", "val": 908144404, "filed": "2026-05-05"},
                    {"fy": 2026, "fp": "Q2", "form": "10-Q",
                     "end": "2026-07-31", "val": 900000000, "filed": "2026-08-10"},
                    {"fy": 2026, "fp": "Q2", "form": "10-Q/A",
                     "end": "2026-07-31", "val": 897594847, "filed": "2026-08-20"},
                    {"fy": 2026, "fp": "FY", "form": "8-K",
                     "end": "2026-09-30", "val": 999999999, "filed": "2026-10-01"},
                ]}},
            },
        }}


def _shares(db, company):
    return list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "shares_outstanding",
        )
    ))


def test_dei_ecso_ingested_as_dei_instants(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECDei)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = {f.period: f for f in _shares(db, company)}
    assert set(facts) == {"2026-02-20:DEI", "2026-04-30:DEI", "2026-07-31:DEI"}
    # La enmienda (10-Q/A, filed posterior) gana sobre el 10-Q original:
    assert facts["2026-07-31:DEI"].value == Decimal("897594847")
    for fact in facts.values():
        assert fact.fiscal_year is None
        assert fact.fiscal_quarter is None
        assert fact.is_reported is True
        assert fact.unit == "shares"
        assert fact.source_type == "SEC"
    # El 8-K nunca entra:
    assert all(f.value != Decimal("999999999") for f in facts.values())

    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    prov = doc.metadata_["capital_fact_provenance"]["shares_outstanding"]
    assert prov["2026-07-31:DEI"]["filed"] == "2026-08-20"
    assert prov["2026-07-31:DEI"]["concept"] == "dei:EntityCommonStockSharesOutstanding"


def test_dei_refresh_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECDei)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))
    asyncio.run(service.refresh_from_sec(db=db, company=company))
    assert len(_shares(db, company)) == 3


def test_dei_respects_as_of(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECDei)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(
        db=db, company=company, as_of=date(2026, 5, 10)))
    facts = _shares(db, company)
    assert [f.period for f in facts] == ["2026-04-30:DEI"] or {
        f.period for f in facts
    } == {"2026-02-20:DEI", "2026-04-30:DEI"}
