"""Auditoría A3: sin cotización real, la plusvalía es desconocida, no 0.

rebuild_position valora con el precio de la última operación cuando nunca se
guardó una cotización. Con una sola compra eso daba una plusvalía de exactamente
0 que la ficha pintaba como dato («$0.00 en USD»). /positions lo marca ahora
con quote_missing y deja la plusvalía en null; el valor se conserva.
"""

from fastapi.testclient import TestClient

from app.core.database import init_db
from main import app


def _client():
    init_db()
    client = TestClient(app)
    # VAL-SEC-001: los POST exigen token CSRF; el frontend lo pide en
    # /api/csrf-token y lo manda como x-csrf-token. El test hace lo mismo.
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})
    return client


def _buy(client, ticker, price="10"):
    response = client.post("/api/portfolio/transactions", json={
        "ticker": ticker, "action": "buy", "quantity": "2", "price": price,
        "currency": "EUR", "trade_date": "2024-01-02",
    })
    assert response.status_code == 201, response.text


def _position(client, ticker):
    # /positions devuelve sobre paginado {"items": [...], "page_info": {...}}.
    payload = client.get("/api/portfolio/positions").json()
    return {p["ticker"]: p for p in payload["items"]}[ticker]


def test_sin_cotizacion_la_plusvalia_es_null_no_cero():
    client = _client()
    _buy(client, "NOQUOTE")
    position = _position(client, "NOQUOTE")
    assert position["quote_missing"] is True
    assert position["market_value"] == 20.0  # el valor se conserva: mejor estimación
    for key in ("unrealized_pnl", "unrealized_pnl_native", "unrealized_pnl_base",
                "pnl_price_effect_base", "pnl_fx_effect_base"):
        assert position[key] is None, key


def test_con_precio_guardado_la_plusvalia_vuelve():
    client = _client()
    _buy(client, "HASQUOTE")
    response = client.patch("/api/portfolio/prices", json={"ticker": "HASQUOTE", "price": "12"})
    assert response.status_code == 200, response.text
    position = _position(client, "HASQUOTE")
    assert position["quote_missing"] is False
    assert position["unrealized_pnl"] == 4.0
    assert position["unrealized_pnl_base"] == 4.0
