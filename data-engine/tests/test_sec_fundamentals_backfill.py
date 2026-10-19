"""Backfill programado de fundamentales SEC del universo US.

Anti-atasco (objecion del auditor): (1) candidatas prefiltradas por la
guarda de identidad sec_eligible (CIK o USD+bolsa US): las no-SEC no
cuentan para el lote; (2) cada intento deja marca persistida en
ConnectorState (NO en Document: un Document interno contaminaria el
conteo de cobertura del thesis graph y el listado de fuentes de la API)
y el lote rota por ultimo intento: skipped/error no se reintentan hasta
3d."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, ConnectorState, Document
from app.services.sec_fundamentals_backfill import (
    CONNECTOR,
    FEED,
    _attempt_state,
    _candidate_ids,
    backfill_sec_fundamentals_async,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, exchange="NASDAQ", currency="USD", cik=None):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency, cik=cik,
        sector="S", industry="I", company_type="research_candidate",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _sec_doc(db, company, refreshed_at):
    doc = Document(
        company_id=company.id, source_type="SEC",
        title=f"SEC XBRL facts - {company.ticker}",
        source_url=f"https://example.test/{company.ticker}",
        metadata_={"last_refreshed_at": refreshed_at.isoformat()},
    )
    db.add(doc)
    db.commit()
    return doc


def _attempt(db, company, attempted_at, status="skipped", reason="emisor_no_sec"):
    state = ConnectorState(
        tenant_id=db.info["tenant_id"], connector=CONNECTOR,
        company_id=company.id, feed_url=FEED,
        last_started_at=attempted_at,
        metadata_={"last_attempt_at": attempted_at.isoformat(),
                   "status": status, "reason": reason},
    )
    db.add(state)
    db.commit()
    return state


def test_candidates_prefilter_non_sec_identity(db):
    """Las europeas/no-SEC ni entran en candidatas (aunque sean 10.000)."""
    now = datetime.now(UTC)
    eu = _company(db, "SAN", exchange="BOLSA DE MADRID", currency="EUR")
    us = _company(db, "AAPL")
    ids = _candidate_ids(db, now=now, limit=1)
    assert [db.get(Company, i).ticker for i in ids] == ["AAPL"]
    assert eu.id not in ids and us.id in ids


def test_candidates_skip_fresh_facts(db):
    now = datetime.now(UTC)
    fresh = _company(db, "FRESH")
    _sec_doc(db, fresh, now - timedelta(days=2))
    stale = _company(db, "STALE")
    _sec_doc(db, stale, now - timedelta(days=30))
    never = _company(db, "NEVER")
    names = [db.get(Company, i).ticker for i in _candidate_ids(db, now=now, limit=100)]
    assert "FRESH" not in names and "STALE" in names and "NEVER" in names


def test_auditor_scenario_many_non_sec_ahead_do_not_block(db):
    """Caso del auditor: >limite no-SEC por delante en id; la US se procesa."""
    now = datetime.now(UTC)
    for i in range(150):
        _company(db, f"EU{i:03d}", exchange="BOLSA DE MADRID", currency="EUR")
    _company(db, "US1")
    names = [db.get(Company, i).ticker for i in _candidate_ids(db, now=now, limit=100)]
    assert names == ["US1"]


def test_attempt_mark_rotates_and_skips_retries(db):
    """Una skipped/error marcada hoy no vuelve hasta 3d; las nunca intentadas
    van primero aunque tengan id mayor."""
    now = datetime.now(UTC)
    skipped = _company(db, "SKIP1")
    _attempt(db, skipped, now - timedelta(days=1))
    _company(db, "ZZNEW")  # id mayor, nunca intentada
    names = [db.get(Company, i).ticker for i in _candidate_ids(db, now=now, limit=100)]
    assert "SKIP1" not in names and "ZZNEW" in names
    # A los 4 dias la marcada vuelve a ser candidata.
    later = now + timedelta(days=4)
    names_later = [db.get(Company, i).ticker for i in _candidate_ids(db, now=later, limit=100)]
    assert "SKIP1" in names_later


def test_backfill_counts_and_records_attempts(db):
    _company(db, "USOK")
    _company(db, "USFAIL")
    calls = []

    async def fake_refresher(session, company):
        calls.append(company.ticker)
        if company.ticker == "USFAIL":
            raise RuntimeError("provider down")
        return {"status": "ok", "facts_imported": 42}

    stats = asyncio.run(backfill_sec_fundamentals_async(
        db, max_companies=10, refresher=fake_refresher, pause_s=0))
    assert sorted(calls) == ["USFAIL", "USOK"]
    assert stats["ok"] == 1 and stats["error"] == 1
    ok_state = _attempt_state(db, db.scalar(select(Company).where(Company.ticker == "USOK")))
    fail_state = _attempt_state(db, db.scalar(select(Company).where(Company.ticker == "USFAIL")))
    assert ok_state.metadata_["status"] == "ok"
    assert ok_state.last_success_at is not None
    assert fail_state.metadata_["status"] == "error"
    assert fail_state.metadata_["reason"] == "excepcion"
    assert fail_state.consecutive_errors == 1


def test_attempt_marks_are_not_documents(db):
    """Regresion de la objecion del auditor: el marcador interno NO puede ser
    un Document (contaminaria thesis graph, agrupado por source_type y el
    listado de fuentes de la API)."""
    _company(db, "NODOC")

    async def fake_refresher(session, company):
        return {"status": "skipped", "reason": "emisor_no_sec"}

    asyncio.run(backfill_sec_fundamentals_async(
        db, max_companies=10, refresher=fake_refresher, pause_s=0))
    n_docs = db.scalar(select(func.count()).select_from(Document).where(
        Document.source_type.like("SEC_BACKFILL%")))
    assert n_docs == 0
    state = _attempt_state(db, db.scalar(select(Company).where(Company.ticker == "NODOC")))
    assert state is not None and state.metadata_["status"] == "skipped"
