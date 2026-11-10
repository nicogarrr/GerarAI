"""Lotes en la zona de tesis: dedup de documentos y cargas por empresa sin N+1.

Cada test cuenta las queries SQL reales (before_cursor_execute) sobre una BD
sqlite en memoria y fija el tope exacto que el barrido de rendimiento
garantiza, ademas del resultado funcional. Antes, cada candidato/empresa/fact
hacia su propia consulta: el coste crecia linealmente con empresas x pasadas.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.core.database  # noqa: F401 - registra los listeners de tenant
from app.models.entities import (
    Base,
    Company,
    Document,
    FinancialFact,
    Tenant,
    ThesisVersion,
)


@pytest.fixture
def db_counter():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.commit()
        yield session, counter
    engine.dispose()


def _company(db: Session, ticker: str = "ACME") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _filing(i: int, url: str | None = None) -> dict:
    return {
        "form": "10-Q",
        "document_url": url or f"https://sec.test/10q-{i}.htm",
        "index_url": None,
        "filing_date": f"2026-0{1 + (i % 9)}-15",
        "accession_number": f"0000000000-26-{i:06d}",
    }


# --- _ingest_filings: dedup de URLs en lote ---------------------------------


def test_resolve_fact_locators_batches_document_reads(db_counter):
    from app.services.thesis_deep_narrative import _resolve_fact_locators

    db, counter = db_counter
    company = _company(db, "LOC")
    docs = [
        Document(company_id=company.id, title=f"doc {i}", source_type="SEC",
                 source_url=f"https://sec.test/d{i}")
        for i in range(5)
    ]
    db.add_all(docs)
    db.flush()
    fact_ids = []
    for i, doc in enumerate(docs):
        fact = FinancialFact(
            company_id=company.id, metric="revenue", value=Decimal("10"), unit="USD",
            period=f"20{20 + i}-12-31:FY", fiscal_year=2020 + i,
            source_id=doc.id, source_type="SEC",
        )
        db.add(fact)
        db.flush()
        fact_ids.append(fact.id)
    db.commit()

    counter["n"] = 0
    locators = _resolve_fact_locators(
        db, {"driver_model": [{"source_fact_ids": fact_ids}]}
    )
    # 2 consultas (facts IN + documentos IN); antes 1 + N gets por driver.
    assert counter["n"] == 2, f"locators uso {counter['n']} queries (!=2)"
    assert locators == {fid: f"https://sec.test/d{i}" for i, fid in enumerate(fact_ids)}


# --- _annual_facts: fechas de documentos fuente en lote ----------------------


def test_annual_facts_prefetches_source_documents(db_counter):
    from app.services.thesis_projection_service import ThesisProjectionService

    db, counter = db_counter
    company = _company(db, "PROJ")
    docs = [
        Document(company_id=company.id, title=f"10-K {year}", source_type="SEC",
                 source_url=f"https://sec.test/10k-{year}", published_at=datetime(year, 3, 1))
        for year in range(2019, 2025)
    ]
    db.add_all(docs)
    db.flush()
    for i, year in enumerate(range(2019, 2025)):
        for metric in ("revenue", "net_income"):
            db.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal("100"), unit="USD",
                period=f"{year}-12-31:FY", fiscal_year=year,
                source_id=docs[i].id, source_type="SEC",
            ))
    db.commit()

    counter["n"] = 0
    out = ThesisProjectionService()._annual_facts(db, company, date(2026, 10, 8))
    # 2 consultas (facts + documentos IN); antes 1 + un get por fact anual.
    assert counter["n"] == 2, f"_annual_facts uso {counter['n']} queries (!=2)"
    assert set(out) == {"revenue", "net_income"}
    assert sorted(out["revenue"]) == list(range(2019, 2025))


# --- sync_all_thesis_rules: empresas en lote ---------------------------------


def test_sync_all_thesis_rules_loads_companies_in_one_query(db_counter, monkeypatch):
    from app.services import thesis_invalidation_rules as rules

    db, counter = db_counter
    companies = [_company(db, f"SYNC{i}") for i in range(8)]
    for company in companies:
        db.add(ThesisVersion(
            company_id=company.id, version=1, status="final",
            thesis_markdown="# T", executive_summary="R", rating="watch",
            invalidation_criteria=[], invalidation_rules=[],
        ))
    db.commit()

    synced: list[int] = []
    monkeypatch.setattr(rules, "sync_thesis_rules", lambda db, company: synced.append(company.id) or [])

    counter["n"] = 0
    rules.sync_all_thesis_rules(db)
    # 3 consultas fijas (ids con tesis + ids con reglas vivas + empresas IN),
    # independientes del numero de empresas; antes era 2 + N gets.
    assert counter["n"] == 3, f"sync_all uso {counter['n']} queries (!=3)"
    assert synced == sorted(company.id for company in companies)


# --- IN por lotes acotados (mas elementos que el limite) ---------------------


def test_annual_facts_chunks_source_document_reads(db_counter, monkeypatch):
    from app.core import sql_chunks
    from app.services.thesis_projection_service import ThesisProjectionService

    monkeypatch.setattr(sql_chunks, "SQL_IN_CHUNK_SIZE", 2)
    db, counter = db_counter
    company = _company(db, "CHUNK")
    docs = [
        Document(company_id=company.id, title=f"10-K {year}", source_type="SEC",
                 source_url=f"https://sec.test/chunk-{year}", published_at=datetime(year, 3, 1))
        for year in range(2020, 2025)
    ]
    db.add_all(docs)
    db.flush()
    for i, year in enumerate(range(2020, 2025)):
        db.add(FinancialFact(
            company_id=company.id, metric="revenue", value=Decimal("100"), unit="USD",
            period=f"{year}-12-31:FY", fiscal_year=year,
            source_id=docs[i].id, source_type="SEC",
        ))
    db.commit()

    counter["n"] = 0
    out = ThesisProjectionService()._annual_facts(db, company, date(2026, 10, 8))
    # 5 fuentes con lote de 2: 1 (facts) + 3 INs acotados; sin trocear seria
    # 1 IN sin cota (y con 33k facts, "too many SQL variables").
    assert counter["n"] == 4, f"_annual_facts uso {counter['n']} queries (!=4)"
    assert sorted(out["revenue"]) == list(range(2020, 2025))


def test_resolve_fact_locators_chunks_source_reads(db_counter, monkeypatch):
    from app.core import sql_chunks
    from app.services.thesis_deep_narrative import _resolve_fact_locators

    monkeypatch.setattr(sql_chunks, "SQL_IN_CHUNK_SIZE", 2)
    db, counter = db_counter
    company = _company(db, "CHLOC")
    docs = [
        Document(company_id=company.id, title=f"doc {i}", source_type="SEC",
                 source_url=f"https://sec.test/cl{i}")
        for i in range(5)
    ]
    db.add_all(docs)
    db.flush()
    fact_ids = []
    for i, doc in enumerate(docs):
        fact = FinancialFact(
            company_id=company.id, metric="revenue", value=Decimal("10"), unit="USD",
            period=f"20{20 + i}-12-31:FY", fiscal_year=2020 + i,
            source_id=doc.id, source_type="SEC",
        )
        db.add(fact)
        db.flush()
        fact_ids.append(fact.id)
    db.commit()

    counter["n"] = 0
    locators = _resolve_fact_locators(db, {"driver_model": [{"source_fact_ids": fact_ids}]})
    # 3 lotes de facts (2+2+1) + 3 lotes de documentos (2+2+1).
    assert counter["n"] == 6, f"locators uso {counter['n']} queries (!=6)"
    assert locators == {fid: f"https://sec.test/cl{i}" for i, fid in enumerate(fact_ids)}


def test_sync_all_thesis_rules_chunks_company_load(db_counter, monkeypatch):
    from app.core import sql_chunks
    from app.services import thesis_invalidation_rules as rules

    monkeypatch.setattr(sql_chunks, "SQL_IN_CHUNK_SIZE", 2)
    db, counter = db_counter
    companies = [_company(db, f"CHS{i}") for i in range(5)]
    for company in companies:
        db.add(ThesisVersion(
            company_id=company.id, version=1, status="final",
            thesis_markdown="# T", executive_summary="R", rating="watch",
            invalidation_criteria=[], invalidation_rules=[],
        ))
    db.commit()

    synced: list[int] = []
    monkeypatch.setattr(rules, "sync_thesis_rules", lambda db, company: synced.append(company.id) or [])

    counter["n"] = 0
    rules.sync_all_thesis_rules(db)
    # 2 (ids) + 3 lotes de empresas (2+2+1); un IN unico sin cota aborta en
    # SQLite con suficientes empresas.
    assert counter["n"] == 5, f"sync_all uso {counter['n']} queries (!=5)"
    assert synced == sorted(company.id for company in companies)


def test_resolve_fact_locators_chunks_fact_reads_too(db_counter, monkeypatch):
    """El IN de facts (preexistente) tambien va por lotes: un driver_model
    grande con un IN unico aborta en SQLite por variables."""
    from app.core import sql_chunks
    from app.services.thesis_deep_narrative import _resolve_fact_locators

    monkeypatch.setattr(sql_chunks, "SQL_IN_CHUNK_SIZE", 2)
    db, counter = db_counter
    company = _company(db, "CHF")
    docs = [
        Document(company_id=company.id, title=f"doc {i}", source_type="SEC",
                 source_url=f"https://sec.test/cf{i}")
        for i in range(5)
    ]
    db.add_all(docs)
    db.flush()
    fact_ids = []
    for i, doc in enumerate(docs):
        fact = FinancialFact(
            company_id=company.id, metric="revenue", value=Decimal("10"), unit="USD",
            period=f"20{20 + i}-12-31:FY", fiscal_year=2020 + i,
            source_id=doc.id, source_type="SEC",
        )
        db.add(fact)
        db.flush()
        fact_ids.append(fact.id)
    db.commit()

    counter["n"] = 0
    locators = _resolve_fact_locators(db, {"driver_model": [{"source_fact_ids": fact_ids}]})
    # 5 ids con lote de 2: 3 lotes de facts + 3 lotes de documentos.
    assert counter["n"] == 6, f"locators uso {counter['n']} queries (!=6)"
    assert locators == {fid: f"https://sec.test/cf{i}" for i, fid in enumerate(fact_ids)}
