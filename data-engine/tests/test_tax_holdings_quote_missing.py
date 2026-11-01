"""Impuestos → posiciones: sin cotización real, la plusvalía latente es «sin dato», no 0.

/api/portfolio/positions ya deja la plusvalía en null cuando el precio es el de
la última operación (auditoría A3), pero /api/taxes/holdings leía la columna tal
cual: con una sola compra sin cotizar la tabla de Impuestos mostraba «0,00 €» de
plusvalía latente, un dato que parece medido y no lo es.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-tax-holdings-quote-missing-32-chars"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    return TestClient(main.app, raise_server_exceptions=False), f"th-{suffix}", f"user-{suffix}"


def _buy(client, tenant, user, ticker, price, trade_date):
    response = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={"ticker": ticker, "action": "buy", "quantity": "2", "price": price,
                   "currency": "EUR", "trade_date": trade_date},
    )
    assert response.status_code == 201, response.text


def _holding(client, tenant, user, ticker):
    response = signed_request(client, SECRET, tenant, user, "GET", "/api/taxes/holdings")
    assert response.status_code == 200, response.text
    return {row["ticker"]: row for row in response.json()}[ticker]


def test_sin_cotizacion_la_plusvalia_de_impuestos_es_null(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"TH{uuid4().hex[:6]}".upper()
    _buy(client, tenant, user, ticker, "10", "2024-01-02")
    row = _holding(client, tenant, user, ticker)
    assert row["unrealized_pnl"] is None
    assert row["market_value"] == 20.0
    assert row["cost_basis"] == 20.0


def test_dos_compras_sin_cotizacion_tampoco_inventan_plusvalia(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"TH{uuid4().hex[:6]}".upper()
    _buy(client, tenant, user, ticker, "10", "2024-01-02")
    _buy(client, tenant, user, ticker, "14", "2024-06-03")
    assert _holding(client, tenant, user, ticker)["unrealized_pnl"] is None


def test_con_precio_guardado_la_plusvalia_vuelve(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"TH{uuid4().hex[:6]}".upper()
    _buy(client, tenant, user, ticker, "10", "2024-01-02")
    response = signed_request(
        client, SECRET, tenant, user, "PATCH", "/api/portfolio/prices",
        json_body={"ticker": ticker, "price": "12"},
    )
    assert response.status_code == 200, response.text
    assert _holding(client, tenant, user, ticker)["unrealized_pnl"] == 4.0
