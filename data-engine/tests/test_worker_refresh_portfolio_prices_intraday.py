"""refresh_portfolio_prices_intraday con sesion SQLite real: skip sin
posiciones, refresco de las empresas en cartera (dedup por id, orden por
ticker), lease held, sesion cerrada si el lease lanza, y payload de
error con lease liberado."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.market_refresh_service as mrs
from app.models.entities import Base, Company, Position
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    e = SimpleNamespace(db=db, released=[], refreshed=None,
                        result={"status": "ok", "updated": 2})
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: "LEASE")
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(mrs, "YahooIntradayPriceProvider", lambda: SimpleNamespace())

    class FakeRefresh:
        def __init__(self, price_provider=None):
            pass

        async def refresh(self, db_, companies=None):
            e.refreshed = [c.ticker for c in companies]
            if isinstance(e.result, Exception):
                raise e.result
            return e.result

    monkeypatch.setattr(mrs, "MarketRefreshService", FakeRefresh)
    # El actor importa ambos dentro de la funcion.
    import app.workers.dramatiq_app as w

    monkeypatch.setattr(w, "MarketRefreshService", FakeRefresh, raising=False)
    monkeypatch.setattr(w, "YahooIntradayPriceProvider",
                        lambda: SimpleNamespace(), raising=False)
    return e


def _company(db, ticker):
    c = Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                sector="T", industry="T", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[],
                factor_tags=[])
    db.add(c)
    db.flush()  # id disponible para las posiciones
    return c


def test_sin_posiciones_skips(env):
    out = worker.refresh_portfolio_prices_intraday.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped" and out["reason"] == "no_positions"
    assert env.refreshed is None and env.released  # lease liberado en skip


def test_refresca_las_empresas_en_cartera_ordenadas(env):
    a = _company(env.db, "ACME")
    b = _company(env.db, "BETA")
    _company(env.db, "FUERA")  # sin posicion: no se refresca
    env.db.add(Position(tenant_id=1, company_id=b.id, quantity=1))
    env.db.add(Position(tenant_id=1, company_id=a.id, quantity=1))
    env.db.add(Position(tenant_id=1, company_id=a.id, quantity=2))  # duplicada: dedup
    env.db.commit()
    out = worker.refresh_portfolio_prices_intraday.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["updated"] == 2
    assert env.refreshed == ["ACME", "BETA"]


def test_lease_en_curso_skips(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: None)
    out = worker.refresh_portfolio_prices_intraday.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "lease_held"


def test_lease_que_lanza_cierra_la_sesion(env, monkeypatch):
    cerrada = []
    monkeypatch.setattr(env.db, "close", lambda: cerrada.append(1))
    monkeypatch.setattr(worker, "acquire_job_lease",
                        lambda key, **kw: (_ for _ in ()).throw(RuntimeError("redis caido")))
    with pytest.raises(RuntimeError):
        worker.refresh_portfolio_prices_intraday.fn(tenant_id=1, user_id="u")
    assert cerrada == [1]  # la sesion no queda abierta


def test_error_del_servicio_rollback_y_lease_liberado(env):
    a = _company(env.db, "ACME")
    env.db.add(Position(tenant_id=1, company_id=a.id, quantity=1))
    env.db.commit()
    env.result = RuntimeError("yahoo caido")
    out = worker.refresh_portfolio_prices_intraday.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert out["actor"] == "refresh_portfolio_prices_intraday"
    assert env.released
