"""Rutas: dar de alta en watchlist o comprar encola la señal DCA; la ficha
dice «preparando» mientras tanto (en vez del 404 de «sin señal»)."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "dca-on-add-secret"


@pytest.fixture()
def call(monkeypatch):
    init_db()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    )
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_tracked_analysis", lambda *a, **k: None)
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_fundamentals_seed", lambda *a, **k: None)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def _call(method, path, json_body=None):
        return signed_request(client, SECRET, f"oa-{suffix}", f"user-oa-{suffix}", method, path, json_body=json_body)

    return _call


@pytest.fixture()
def enqueued(monkeypatch):
    calls: list[tuple[object, list[str]]] = []

    def fake(db, symbols, **_):
        calls.append((db.info.get("tenant_id"), list(symbols)))
        return 1

    monkeypatch.setattr("app.api.routes.watchlist.enqueue_dca_on_add", fake)
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_market_data_on_add",
                        lambda db, symbol: calls.append((db.info.get("tenant_id"), ["data:" + symbol])))
    monkeypatch.setattr("app.services.dca_on_add.enqueue_dca_on_add", fake)
    return calls


def test_alta_en_watchlist_encola_la_senal_dca_una_vez(call, enqueued):
    symbol = f"OA{uuid4().hex[:4].upper()}"
    assert call("POST", "/api/watchlist", {"symbol": symbol}).status_code == 201
    assert [s for _, s in enqueued] == [[symbol], ["data:" + symbol]] and enqueued[0][0] is not None
    # Cambiar la etiqueta no es un alta: no se vuelve a encolar.
    assert call("POST", "/api/watchlist", {"symbol": symbol, "company": "Otra"}).status_code == 201
    assert len(enqueued) == 2


def test_el_alta_responde_aunque_falle_el_encolado(call, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("cola caída")

    monkeypatch.setattr("app.services.dca_on_add._enqueue", broken)
    symbol = f"OB{uuid4().hex[:4].upper()}"
    assert call("POST", "/api/watchlist", {"symbol": symbol}).status_code == 201


def test_compra_encola_la_senal_dca(call, enqueued, monkeypatch):
    monkeypatch.setattr("app.api.routes.portfolio.enqueue_tracked_analysis", lambda *a, **k: None)
    monkeypatch.setattr("app.services.market_close_sync.enqueue_price_backfills", lambda *a, **k: 0)
    symbol = f"OC{uuid4().hex[:4].upper()}"
    response = call("POST", "/api/portfolio/transactions", {
        "ticker": symbol, "action": "buy", "quantity": 2, "price": 10,
        "trade_date": "2026-10-01", "currency": "USD"})
    assert response.status_code == 201, response.text
    assert [s for _, s in enqueued] == [[symbol]]


def test_ficha_dice_preparando_mientras_se_evalua(call, monkeypatch):
    symbol = f"OD{uuid4().hex[:4].upper()}"
    monkeypatch.setattr("app.api.routes.watchlist.is_preparing", lambda db, key: key == symbol)
    response = call("GET", f"/api/watchlist/dca-signals/{symbol.lower()}/hit-rates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preparing"] is True and body["available"] is False and body["symbol"] == symbol
    other = call("GET", "/api/watchlist/dca-signals/NOPREP/hit-rates")
    assert other.status_code == 404
