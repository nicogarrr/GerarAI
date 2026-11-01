"""Antigüedad de la posición: tras venderlo todo y volver a comprar, cuenta desde la nueva compra.

/api/portfolio/positions («Desde», «Largo plazo · 1034d») y la ficha de la
empresa («Primera compra», gráfico «Desde la compra») tomaban la primera compra
registrada del ticker aunque esa posición se hubiera cerrado del todo: una
posición reabierta en febrero de 2025 salía «desde 02/01/2024», con 1034 días y
«largo plazo».
"""

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.core.local_date import local_today
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-holding-start-reopen-secret-32chars"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    return TestClient(main.app, raise_server_exceptions=False), f"hs-{suffix}", f"user-{suffix}"


def _trade(client, tenant, user, ticker, action, quantity, price, trade_date):
    response = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={"ticker": ticker, "action": action, "quantity": quantity, "price": price,
                   "currency": "EUR", "trade_date": trade_date},
    )
    assert response.status_code == 201, response.text


def _position(client, tenant, user, ticker):
    response = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")
    assert response.status_code == 200, response.text
    return {p["ticker"]: p for p in response.json()["items"]}[ticker]


def test_posicion_reabierta_cuenta_desde_la_nueva_compra(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"HS{uuid4().hex[:6]}".upper()
    _trade(client, tenant, user, ticker, "buy", "10", "10", "2024-01-02")
    _trade(client, tenant, user, ticker, "sell", "10", "12", "2024-03-01")
    _trade(client, tenant, user, ticker, "buy", "5", "20", "2025-02-03")
    position = _position(client, tenant, user, ticker)
    assert position["first_buy_date"] == "2025-02-03"
    assert position["holding_days"] == (local_today() - date(2025, 2, 3)).days

    response = signed_request(client, SECRET, tenant, user, "GET",
                              f"/api/companies/{ticker}/events/timeline")
    assert response.status_code == 200, response.text
    assert response.json()["holding"]["first_buy_date"] == "2025-02-03"


def test_venta_parcial_no_mueve_la_fecha(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"HP{uuid4().hex[:6]}".upper()
    _trade(client, tenant, user, ticker, "buy", "10", "10", "2024-01-02")
    _trade(client, tenant, user, ticker, "sell", "4", "12", "2024-03-01")
    _trade(client, tenant, user, ticker, "buy", "5", "20", "2025-02-03")
    position = _position(client, tenant, user, ticker)
    assert position["first_buy_date"] == "2024-01-02"
    assert position["fiscal_bucket"] == "largo_plazo"
