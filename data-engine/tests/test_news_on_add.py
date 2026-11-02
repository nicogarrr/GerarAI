"""Noticias al añadir: la ficha dice «preparando» solo mientras la petición
de noticias del ticker recién añadido está pendiente (marca Redis propia que
pone el encolado y borra el job al terminar, salga como salga)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.models.entities import Base
from app.services import dca_on_add
from tests.auth_helpers import auth_settings, signed_request


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        self.ttl[key] = ex
        return True

    def delete(self, key):
        self.data.pop(key, None)

    def exists(self, key):
        return int(key in self.data)

    def close(self):
        pass


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.info["tenant_id"] = 1
        session.info["user_id"] = "u1"
        yield session
    engine.dispose()


def test_encolar_noticias_marca_el_ticker_como_preparando(db):
    client, sent = FakeRedis(), []
    dca_on_add.enqueue_news_on_add(db, " aaa ", client=client, news_sender=lambda t, u, s: sent.append((t, u, s)))
    assert sent == [(1, "u1", "AAA")]
    key = dca_on_add.news_mark_key(1, "AAA")
    assert key in client.data and client.ttl[key] == dca_on_add.MARK_TTL_SECONDS
    assert dca_on_add.is_news_preparing(db, "aaa", client=client) is True
    db.info["tenant_id"] = 2  # otro tenant no ve la marca ajena
    assert dca_on_add.is_news_preparing(db, "AAA", client=client) is False


def test_si_la_cola_falla_no_queda_marca_ni_rompe(db):
    client = FakeRedis()

    def broken(*_):
        raise RuntimeError("cola caída")

    dca_on_add.enqueue_news_on_add(db, "AAA", client=client, news_sender=broken)  # no lanza
    assert client.data == {}
    assert dca_on_add.is_news_preparing(db, "AAA", client=client) is False


def test_sin_tenant_no_encola_ni_marca(db):
    client, sent = FakeRedis(), []
    db.info.pop("tenant_id")
    dca_on_add.enqueue_news_on_add(db, "AAA", client=client, news_sender=lambda *a: sent.append(a))
    assert sent == [] and client.data == {}
    assert dca_on_add.is_news_preparing(db, "AAA", client=client) is False


def test_el_alta_en_watchlist_pide_noticias_con_marca(db, monkeypatch):
    calls = []
    monkeypatch.setattr(dca_on_add, "enqueue_news_on_add", lambda db, symbol, **_: calls.append(symbol))
    dca_on_add.enqueue_market_data_on_add(db, "hist", backfill=lambda *a, **k: 0)
    assert calls == ["HIST"]


def _run_skipped_news_job(monkeypatch, client, **kwargs):
    """El job de noticias sale por «copia fresca o en curso» sin trabajar."""
    from app.workers import dramatiq_app

    class Busy(FakeRedis):
        def set(self, key, value, nx=False, ex=None):
            if key.startswith("coalesce:"):
                return None  # claim ocupado: otra corrida reciente
            return super().set(key, value, nx=nx, ex=ex)

    busy = Busy()
    busy.data = client.data
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: busy)
    monkeypatch.setattr(dca_on_add, "redis_client", lambda: client)
    return dramatiq_app.refresh_ticker_news.fn(**kwargs)


def test_el_job_de_noticias_borra_la_marca_al_terminar_aunque_se_salte(monkeypatch):
    client = FakeRedis()
    client.set(dca_on_add.news_mark_key(1, "AAA"), "queued")
    client.set(dca_on_add.news_mark_key(1, "BBB"), "queued")
    result = _run_skipped_news_job(monkeypatch, client, tenant_id=1, user_id="u1", ticker="aaa", scope="tracked")
    assert result["reason"] == "fresh_or_running"
    assert dca_on_add.news_mark_key(1, "AAA") not in client.data
    assert dca_on_add.news_mark_key(1, "BBB") in client.data  # solo la de su ticker


def test_el_barrido_sin_ticker_no_toca_marcas(monkeypatch):
    client = FakeRedis()
    client.set(dca_on_add.news_mark_key(1, "AAA"), "queued")
    _run_skipped_news_job(monkeypatch, client, tenant_id=1, user_id="u1", scope="tracked")
    assert dca_on_add.news_mark_key(1, "AAA") in client.data


SECRET = "news-on-add-secret"


@pytest.fixture()
def call(monkeypatch):
    init_db()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    )
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def _call(method, path, json_body=None):
        return signed_request(client, SECRET, f"na-{suffix}", f"user-na-{suffix}", method, path, json_body=json_body)

    return _call


def test_la_ficha_pregunta_si_las_noticias_se_estan_preparando(call, monkeypatch):
    symbol = f"NP{uuid4().hex[:4].upper()}"
    monkeypatch.setattr("app.api.routes.watchlist.is_news_preparing", lambda db, key: key == symbol)
    response = call("GET", f"/api/watchlist/news-preparing/{symbol.lower()}")
    assert response.status_code == 200, response.text
    assert response.json() == {"symbol": symbol, "preparing": True}
    other = call("GET", "/api/watchlist/news-preparing/NOPREP")
    assert other.status_code == 200 and other.json() == {"symbol": "NOPREP", "preparing": False}


def test_comprar_pide_las_noticias_del_ticker(call, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.routes.portfolio.enqueue_tracked_analysis", lambda *a, **k: None)
    monkeypatch.setattr("app.services.market_close_sync.enqueue_price_backfills", lambda *a, **k: 0)
    monkeypatch.setattr("app.services.dca_on_add.enqueue_dca_on_add", lambda *a, **k: 0)
    monkeypatch.setattr("app.services.dca_on_add.enqueue_news_on_add",
                        lambda db, symbol, **_: calls.append((db.info.get("tenant_id") is not None, symbol)))
    symbol = f"NB{uuid4().hex[:4].upper()}"
    response = call("POST", "/api/portfolio/transactions", {
        "ticker": symbol, "action": "buy", "quantity": 2, "price": 10,
        "trade_date": "2026-10-01", "currency": "USD"})
    assert response.status_code == 201, response.text
    assert calls == [(True, symbol)]
    sell = call("POST", "/api/portfolio/transactions", {
        "ticker": symbol, "action": "sell", "quantity": 1, "price": 11,
        "trade_date": "2026-10-02", "currency": "USD"})
    assert sell.status_code == 201, sell.text
    assert calls == [(True, symbol)]  # vender no vuelve a pedir noticias
