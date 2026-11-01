"""Precio manual y tipo de cambio: solo valores que la base puede guardar.

Las operaciones ya tenian topes (#numeric 20,6): «1e400» se guardaba como
precio nulo y rompia el recalculo. El precio manual (PATCH /prices) y el tipo
de cambio (POST /fx-rates) no los tenian:

- precio «1e400» -> 200, se guardaba nulo y GET /positions daba 500 para TODA
  la cartera;
- precio «0,0000001» o «1e-400» (> 0) -> se guardaba 0 y la posicion valia 0;
- tipo de cambio «1e400» -> rate null; «1e-400» -> rate 0.
"""

from fastapi.testclient import TestClient

from app.core.csrf import generate_csrf_token
from app.core.database import init_db
from main import app

CSRF = {"X-CSRF-Token": generate_csrf_token()}


def _client():
    init_db()
    return TestClient(app, raise_server_exceptions=False)


def _buy(client, ticker):
    response = client.post("/api/portfolio/transactions", json={
        "ticker": ticker, "action": "buy", "quantity": "2", "price": "10",
        "currency": "EUR", "trade_date": "2024-01-02",
    }, headers=CSRF)
    assert response.status_code == 201, response.text


def _positions(client):
    response = client.get("/api/portfolio/positions", params={"limit": 2000})
    assert response.status_code == 200, response.text
    return {p["ticker"]: p for p in response.json()["items"]}


def test_precio_manual_imposible_es_422_y_la_cartera_sigue_leyendose():
    client = _client()
    _buy(client, "MPLIMA")
    for price in ("1e400", "1e30", "100000000000000", "0.0000001", "1e-400"):
        response = client.patch("/api/portfolio/prices", json={"ticker": "MPLIMA", "price": price}, headers=CSRF)
        assert response.status_code == 422, (price, response.text)
    position = _positions(client)["MPLIMA"]
    assert position["market_price"] == 10.0  # sigue el precio de la compra


def test_precio_manual_en_el_limite_se_acepta():
    client = _client()
    _buy(client, "MPLIMB")
    for price in ("0.000001", "12.123456", "99999999999999.999999"):
        response = client.patch("/api/portfolio/prices", json={"ticker": "MPLIMB", "price": price}, headers=CSRF)
        assert response.status_code == 200, (price, response.text)
    assert _positions(client)["MPLIMB"]["market_price"] == 99999999999999.999999


def test_tipo_de_cambio_imposible_es_422():
    client = _client()
    body = {"base_currency": "EUR", "quote_currency": "NOK", "rate_date": "2024-01-03"}
    for rate in ("1e400", "1e-400", "0.00000000001", "100000000000"):
        response = client.post("/api/portfolio/fx-rates", json={**body, "rate": rate}, headers=CSRF)
        assert response.status_code == 422, (rate, response.text)
    ok = client.post("/api/portfolio/fx-rates", json={**body, "rate": "0.0870000001"}, headers=CSRF)
    assert ok.status_code == 201, ok.text
    assert ok.json()["rate"] == 0.0870000001
