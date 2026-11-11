"""Fallback de caja SEC: cuando el emisor deja de reportar caja estricta
(p.ej. WWW), se usa el tag combinado caja+restringida como ultimo alias,
con nota de cobertura en el documento."""

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


def _company(db, ticker="WWW"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _FakeSECClientWWW:
    """WWW-like: caja estricta hasta FY2022; desde FY2023 solo el tag
    combinado (caja + restringida), con `filed` mas reciente."""

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0001104711"

    async def company_facts(self, cik):
        return {
            "facts": {
                "us-gaap": {
                    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                        {"fy": 2022, "fp": "FY", "form": "10-K", "end": "2022-12-31",
                         "val": 1000, "filed": "2023-03-01"},
                    ]}},
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": {
                        "units": {"USD": [
                            {"fy": 2023, "fp": "FY", "form": "10-K", "end": "2023-12-31",
                             "val": 1200, "filed": "2024-03-01"},
                            {"fy": 2024, "fp": "FY", "form": "10-K", "end": "2024-12-31",
                             "val": 1400, "filed": "2025-03-01"},
                        ]}
                    },
                }
            }
        }


def test_cash_fallback_to_restricted_tag_with_coverage_note(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientWWW)
    company = _company(db)
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))

    facts = list(db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "cash_and_equivalents",
        )
    ))
    by_year = {f.fiscal_year: f for f in facts}
    assert by_year[2022].value == Decimal("1000")  # caja estricta historica
    assert by_year[2023].value == Decimal("1200")  # fallback combinado
    assert by_year[2024].value == Decimal("1400")  # fallback combinado

    document = db.scalar(
        select(Document).where(
            Document.company_id == company.id, Document.source_type == "SEC"
        )
    )
    note = (document.metadata_ or {}).get("cash_includes_restricted_periods")
    assert note == [2023, 2024]  # 2022 estricto: NO anotado


def test_no_note_when_strict_cash_reported(db, monkeypatch):
    class _FakeSECClientStrict:
        async def cik_for_ticker(self, ticker, entity_name=None):
            return "0001234567"

        async def company_facts(self, cik):
            return {"facts": {"us-gaap": {
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                    {"fy": 2024, "fp": "FY", "form": "10-K", "end": "2024-12-31",
                     "val": 500, "filed": "2025-03-01"},
                ]}},
            }}}

    monkeypatch.setattr(ingestion, "SECClient", _FakeSECClientStrict)
    company = _company(db, ticker="AAA")
    service = FinancialIngestionService()
    asyncio.run(service.refresh_from_sec(db=db, company=company))
    document = db.scalar(
        select(Document).where(
            Document.company_id == company.id, Document.source_type == "SEC"
        )
    )
    assert "cash_includes_restricted_periods" not in (document.metadata_ or {})


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


_anchor_fake(_FakeSECClientWWW, "12")
