"""ingest_corporate_splits y split_sync_tickers con sesion SQLite real:
scope tracked (cartera + watchlist, dedup y mayusculas), scope universo
con chunks auto-encolados, un ticker que falla no corta el chunk, lo
transitorio relanza para que Dramatiq reintente, y recuento por estado."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.split_ingestion_service as sis
from app.models.entities import Base, Company, Position, WatchItem
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    e = SimpleNamespace(db=db, sends=[], outcomes={})
    # El coalescer libera su claim via Redis al terminar con error: fail-open.
    monkeypatch.setattr(worker, "_redis_client", lambda: None)

    class FakeService:
        async def sync_company(self, db_, *, ticker):
            outcome = e.outcomes.get(ticker, {"status": "ok", "inserted": 1, "existing": 0})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(sis, "SplitIngestionService", FakeService)
    original = worker.ingest_corporate_splits
    monkeypatch.setattr(worker, "ingest_corporate_splits", SimpleNamespace(
        fn=original.fn, send=lambda *a, **kw: e.sends.append((a, kw))))
    e.original = original
    return e


def _company(db, ticker):
    c = Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                sector="T", industry="T", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[],
                factor_tags=[])
    db.add(c)
    db.flush()
    return c


def test_scope_tracked_cartera_mas_watchlist(env):
    a = _company(env.db, "ACME")
    _company(env.db, "FUERA")
    env.db.add(Position(tenant_id=1, company_id=a.id, quantity=1))
    env.db.add(WatchItem(tenant_id=1, symbol="beta"))  # minusculas: se normaliza
    env.db.commit()
    out = env.original.fn(tenant_id=1, user_id="u", scope="tracked")
    assert out["status"] == "ok" and out["companies"] == 2
    assert out["synced"] == 2 and out["next_cursor"] is None
    # ACME por posicion, BETA por watchlist; FUERA no entra.
    assert env.sends == []


def test_scope_universo_se_autoencola_por_chunks(env, monkeypatch):
    monkeypatch.setattr(worker, "SPLIT_SYNC_UNIVERSE_CHUNK", 2)
    for t in ("A", "B", "C"):
        _company(env.db, t)
    env.db.commit()
    out = env.original.fn(tenant_id=1, user_id="u", scope="universe", cursor=0)
    assert out["companies"] == 2 and out["next_cursor"] == 2
    assert env.sends[0][1] == {"scope": "universe", "cursor": 2}
    out2 = env.original.fn(tenant_id=1, user_id="u", scope="universe", cursor=2)
    assert out2["companies"] == 1 and out2["next_cursor"] is None


def test_ticker_que_falla_no_corta_el_chunk(env):
    for t in ("A", "B", "C"):
        _company(env.db, t)
    env.db.commit()
    env.outcomes = {
        "A": {"status": "ok", "inserted": 1, "existing": 0},
        "B": ValueError("fila corrupta"),  # no transitorio
        "C": {"status": "unavailable"},
    }
    out = env.original.fn(tenant_id=1, user_id="u", scope="universe")
    assert out["synced"] == 1 and out["unavailable"] == 1
    assert out["failed"] == ["B"] and out["inserted"] == 1


def test_error_transitorio_relanza_para_reintento(env):
    _company(env.db, "A")
    env.db.commit()
    env.outcomes = {"A": ConnectionError("pg caido")}  # transitorio
    # Lo transitorio RELANZA crudo: solo asi max_retries/backoff de dramatiq
    # son reales (un error permanente devuelve payload sin quemar reintentos).
    with pytest.raises(ConnectionError):
        env.original.fn(tenant_id=1, user_id="u", scope="universe")


def test_error_de_sesion_devuelve_payload(env, monkeypatch):
    monkeypatch.setattr(worker, "_session",
                        lambda t, u: (_ for _ in ()).throw(ValueError("sin db")))
    out = env.original.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "ingest_corporate_splits"
