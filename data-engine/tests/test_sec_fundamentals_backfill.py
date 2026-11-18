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


def test_freshness_map_batches_and_matches_scalar_semantics(db):
    """La lectura en lote equivale a last_sec_refresh por compania: fecha
    fresca, fecha invalida (=no fresco), sin Document (=no fresco) y, con
    varios Documents anomalos, gana el primero como el scalar original."""
    from app.services.sec_fundamentals_backfill import _freshness_map

    now = datetime.now(UTC)
    ok = _company(db, "FMOK")
    _sec_doc(db, ok, now - timedelta(days=2))
    bad = _company(db, "FMBAD")
    doc = _sec_doc(db, bad, now - timedelta(days=2))
    doc.metadata_ = {"last_refreshed_at": "no-es-una-fecha"}
    db.commit()
    missing = _company(db, "FMNONE")

    freshness = _freshness_map(db, [ok.id, bad.id, missing.id])
    assert freshness[ok.id] is not None
    assert freshness[bad.id] is None
    assert missing.id not in freshness

    # Universo sin elegibles: ni una consulta (guarda de lista vacia).
    assert _freshness_map(db, []) == {}


def test_batch_reuses_attempt_marks_without_extra_writes(db):
    """Con marca previa de FEED el lote la actualiza en memoria (sin SELECT
    por compania) y mantiene los contadores del estado."""
    now = datetime.now(UTC)
    reused = _company(db, "REUSE")
    _attempt(db, reused, now - timedelta(days=4), status="error", reason="boom")
    state = _attempt_state(db, reused)
    assert state.consecutive_errors is None or state.consecutive_errors >= 0

    async def fake_refresher(session, company):
        return {"status": "error", "reason": "sigue_roto"}

    stats = asyncio.run(backfill_sec_fundamentals_async(
        db, max_companies=10, refresher=fake_refresher, pause_s=0))
    assert stats["error"] == 1
    db.expire_all()
    state = _attempt_state(db, reused)
    assert state.consecutive_errors == 1
    assert state.metadata_["reason"] == "sigue_roto"
    # Una sola fila de marca por compania: la precargada se reutilizo.
    n_states = db.scalar(select(func.count()).select_from(ConnectorState).where(
        ConnectorState.connector == CONNECTOR, ConnectorState.company_id == reused.id))
    assert n_states == 1


def test_freshness_map_equals_last_sec_refresh_for_every_edge_case(db):
    """Oraculo: el lote devuelve lo mismo que last_sec_refresh por compania,
    tambien con titulo de otro ticker, documento de otra fuente, fecha naive,
    fecha invalida o no-string, y varios Documents con el titulo exacto."""
    from app.services.sec_fundamentals_backfill import _freshness_map
    from app.services.tracked_financial_refresh import last_sec_refresh

    now = datetime.now(UTC)

    def doc(company, title, meta, source="SEC"):
        db.add(Document(company_id=company.id, source_type=source, title=title,
                        source_url=f"https://example.test/{title}", metadata_=meta))
        db.commit()

    def stamp(days):
        return {"last_refreshed_at": (now - timedelta(days=days)).isoformat()}

    cases = {name: _company(db, name) for name in
             ("EXACT", "NAIVE", "BADDATE", "NONSTR", "NOMETA", "RENAMED", "WRONGFIRST",
              "OTHERSRC", "LOWER", "DUPFRESHFIRST")}
    doc(cases["EXACT"], "SEC XBRL facts - EXACT", stamp(2))
    doc(cases["NAIVE"], "SEC XBRL facts - NAIVE",
        {"last_refreshed_at": (now - timedelta(days=2)).replace(tzinfo=None).isoformat()})
    doc(cases["BADDATE"], "SEC XBRL facts - BADDATE", {"last_refreshed_at": "no-es-fecha"})
    doc(cases["NONSTR"], "SEC XBRL facts - NONSTR", {"last_refreshed_at": 12345})
    doc(cases["NOMETA"], "SEC XBRL facts - NOMETA", None)
    doc(cases["RENAMED"], "SEC XBRL facts - OLDTICKER", stamp(1))
    doc(cases["WRONGFIRST"], "SEC XBRL facts - OTHERTICKER", stamp(40))
    doc(cases["WRONGFIRST"], "SEC XBRL facts - WRONGFIRST", stamp(1))
    doc(cases["OTHERSRC"], "SEC XBRL facts - OTHERSRC", stamp(1), source="OTHER")
    doc(cases["LOWER"], "sec xbrl facts - LOWER", stamp(1))
    doc(cases["DUPFRESHFIRST"], "SEC XBRL facts - DUPFRESHFIRST", stamp(1))
    doc(cases["DUPFRESHFIRST"], "SEC XBRL facts - DUPFRESHFIRST", stamp(40))

    batch = _freshness_map(db, [c.id for c in cases.values()])
    for name, company in cases.items():
        assert batch.get(company.id) == last_sec_refresh(db, company), name


def test_batch_attempt_mark_from_another_feed_falls_back_to_query(db):
    """Una marca precargada de otro feed no se reutiliza: se consulta la del
    FEED y, si no existe, se crea (sin tocar la ajena)."""
    from app.services.sec_fundamentals_backfill import _record_attempt

    company = _company(db, "OTHERFEED")
    other = ConnectorState(tenant_id="tenant-test", connector=CONNECTOR,
                           company_id=company.id, feed_url="otro-feed",
                           metadata_={"status": "ok"})
    own_mark = ConnectorState(tenant_id="tenant-test", connector=CONNECTOR,
                              company_id=company.id, feed_url=FEED,
                              metadata_={"status": "skipped"})
    db.add_all([other, own_mark])
    db.commit()
    states = {company.id: other}
    _record_attempt(db, company, now=datetime.now(UTC), status="error", reason="x", states=states)
    assert other.metadata_ == {"status": "ok"} and not other.consecutive_errors
    own = db.scalar(select(ConnectorState).where(
        ConnectorState.connector == CONNECTOR, ConnectorState.company_id == company.id,
        ConnectorState.feed_url == FEED))
    assert own is own_mark and states[company.id] is own_mark and own.consecutive_errors == 1
    n = db.scalar(select(func.count()).select_from(ConnectorState).where(
        ConnectorState.connector == CONNECTOR, ConnectorState.company_id == company.id))
    assert n == 2  # sin fila duplicada para el FEED


def test_mark_survives_rollback_of_a_later_company(db):
    first = _company(db, "AAFIRST")
    _company(db, "BBLATER")

    async def refresher(session, company):
        if company.ticker == "BBLATER":
            raise RuntimeError("boom")
        return {"status": "ok"}

    asyncio.run(backfill_sec_fundamentals_async(db, max_companies=10, refresher=refresher, pause_s=0))
    db.expire_all()
    state = _attempt_state(db, first)
    assert state is not None and state.metadata_["status"] == "ok"
    assert state.last_success_at is not None
