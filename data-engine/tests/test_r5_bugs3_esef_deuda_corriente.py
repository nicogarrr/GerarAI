"""Deuda corriente ESEF desde sus partes (r5-bugs3, 11-nov-2026).

Antes: ``financial_liabilities_current`` solo leía ``CurrentFinancialLiabilities`` o el total
``CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings``. Un emisor que etiqueta solo sus partes
(``ShorttermBorrowings`` / ``CurrentPortionOfLongtermBorrowings``) quedaba sin deuda corriente y, como
``total_debt`` solo se deriva con las dos componentes, sin deuda total ni valor razonable. Intertek FY2025
(filings.xbrl.org) etiqueta ``ShorttermBorrowings`` = 163,6 M£ y ``LongtermBorrowings`` = 1.162,4 M£.
Nunca se supone 0: si falta una parte que el emisor sí etiqueta otro año, el ejercicio queda sin deuda.
"""
import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService

GBP = "iso4217:GBP"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _inst(val, instant):
    return {"instant": instant, "val": str(val), "decimals": 0, "lei": "L", "dims": []}


def _dur(val, y):
    return {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": str(val), "decimals": 0, "lei": "L", "dims": []}


def _snapshot(balance: dict[str, dict[int, float]]):
    facts: dict = {}
    for y in (2025, 2024):
        for concept, value in (("ifrs-full:Revenue", 3400), ("ifrs-full:ProfitLoss", 400)):
            facts.setdefault(concept, {}).setdefault(GBP, []).append(_dur(value, y))
        facts.setdefault("ifrs-full:CashAndCashEquivalents", {}).setdefault(GBP, []).append(_inst(330, f"{y}-12-31"))
    for concept, by_year in balance.items():
        for y, value in by_year.items():
            facts.setdefault(concept, {}).setdefault(GBP, []).append(_inst(value, f"{y}-12-31"))
    return {"lei": "2138003GAT25WW1RN369", "ticker": "EU1.L", "entity_name": "EU1 PLC", "period_end": "2025-12-31",
            "fxo_id": "fxo-eu1", "fetched_at": "2026-11-11", "facts": facts}


def _ingest(db, monkeypatch, balance):
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: _snapshot(balance))
    company = Company(ticker="EU1.L", name="EU1 plc", exchange="LSE", currency="GBP", sector="Industrials",
                      industry="I", company_type="operating", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    return {(f.metric, f.period): f.value for f in db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id))}


def test_solo_prestamos_a_corto_da_deuda_corriente_y_total(db, monkeypatch):
    got = _ingest(db, monkeypatch, {"ifrs-full:ShorttermBorrowings": {2025: 163.6, 2024: 101.3},
                                    "ifrs-full:LongtermBorrowings": {2025: 1162.4, 2024: 741.5}})
    assert got[("financial_liabilities_current", "2025-12-31:FY")] == Decimal("163.6")
    assert got[("total_debt", "2025-12-31:FY")] == Decimal("1326.0")
    assert got[("total_debt", "2024-12-31:FY")] == Decimal("842.8")


def test_las_dos_partes_se_suman(db, monkeypatch):
    got = _ingest(db, monkeypatch, {"ifrs-full:ShorttermBorrowings": {2025: 100, 2024: 90},
                                    "ifrs-full:CurrentPortionOfLongtermBorrowings": {2025: 50, 2024: 40},
                                    "ifrs-full:LongtermBorrowings": {2025: 800, 2024: 700}})
    assert got[("financial_liabilities_current", "2025-12-31:FY")] == Decimal("150")
    assert got[("total_debt", "2025-12-31:FY")] == Decimal("950")


def test_el_total_etiquetado_manda_sobre_sus_partes(db, monkeypatch):
    got = _ingest(db, monkeypatch, {"ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings": {2025: 150, 2024: 130},
                                    "ifrs-full:ShorttermBorrowings": {2025: 100, 2024: 90},
                                    "ifrs-full:LongtermBorrowings": {2025: 800, 2024: 700}})
    assert got[("financial_liabilities_current", "2025-12-31:FY")] == Decimal("150")
    assert got[("total_debt", "2025-12-31:FY")] == Decimal("950")


def test_parte_que_falta_ese_ano_no_se_supone_cero(db, monkeypatch):
    got = _ingest(db, monkeypatch, {"ifrs-full:ShorttermBorrowings": {2025: 100, 2024: 90},
                                    "ifrs-full:CurrentPortionOfLongtermBorrowings": {2024: 40},
                                    "ifrs-full:LongtermBorrowings": {2025: 800, 2024: 700}})
    assert ("financial_liabilities_current", "2025-12-31:FY") not in got
    assert ("total_debt", "2025-12-31:FY") not in got
    assert got[("total_debt", "2024-12-31:FY")] == Decimal("830")


def test_sube_la_version_de_reglas_esef():
    assert ingestion.ESEF_INGESTION_RULES_VERSION >= 8
