"""Auditoría A3: sin cotización real, la plusvalía es desconocida, no 0.

rebuild_position valora con el precio de la última operación cuando nunca se
guardó una cotización. Con una sola compra eso daba una plusvalía de exactamente
0 que la ficha pintaba como dato («$0.00 en USD»). /positions lo marca ahora
con quote_missing y deja la plusvalía en null; el valor se conserva.

Contrato actual del endpoint: /api/portfolio/positions responde paginado
({items, page_info}) y las mutaciones exigen CSRF o firma interna Research OS
(VAL-SEC-001). Los tests firman con bound headers, como el resto de la suite.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-quote-missing-secret-at-least-32-chars"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    tenant, user = f"qm-{suffix}", f"user-{suffix}"
    return TestClient(main.app, raise_server_exceptions=False), tenant, user


def _buy(client, tenant, user, ticker, price="10"):
    response = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "2", "price": price,
            "currency": "EUR", "trade_date": "2024-01-02",
        },
    )
    assert response.status_code == 201, response.text


def _position(client, tenant, user, ticker):
    response = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "items" in data and "page_info" in data  # contrato paginado
    return {p["ticker"]: p for p in data["items"]}[ticker]


def test_sin_cotizacion_la_plusvalia_es_null_no_cero(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    _buy(client, tenant, user, "NOQUOTE")
    position = _position(client, tenant, user, "NOQUOTE")
    assert position["quote_missing"] is True
    assert position["market_value"] == 20.0  # el valor se conserva: mejor estimación
    for key in ("unrealized_pnl", "unrealized_pnl_native", "unrealized_pnl_base",
                "pnl_price_effect_base", "pnl_fx_effect_base"):
        assert position[key] is None, key


def test_con_precio_guardado_la_plusvalia_vuelve(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    _buy(client, tenant, user, "HASQUOTE")
    response = signed_request(
        client, SECRET, tenant, user, "PATCH", "/api/portfolio/prices",
        json_body={"ticker": "HASQUOTE", "price": "12"},
    )
    assert response.status_code == 200, response.text
    position = _position(client, tenant, user, "HASQUOTE")
    assert position["quote_missing"] is False
    assert position["unrealized_pnl"] == 4.0
    assert position["unrealized_pnl_base"] == 4.0
