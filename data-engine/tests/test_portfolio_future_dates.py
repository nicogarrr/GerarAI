"""Precios manuales y tipos de cambio no pueden fecharse en el futuro.

Un tipo FX con rate_date 2062 (por 2026) quedaba invisible hasta esa fecha y
despues ganaba a los reales; un precio con as_of futuro dejaba la posicion
fechada en el futuro. Ademas, sin as_of, el precio manual tomaba el dia UTC del
servidor: entre las 00:00 y las 01:00/02:00 de Madrid quedaba fechado «ayer».
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.core.csrf import generate_csrf_token
from app.core.database import init_db
from app.core.local_date import local_today
from main import app


def _client():
    init_db()
    return TestClient(app)


# El middleware CSRF (VAL-SEC-001) exige token en todo mutante, como el frontend.
CSRF = {"X-CSRF-Token": generate_csrf_token()}


def _buy(client, ticker):
    response = client.post("/api/portfolio/transactions", json={
        "ticker": ticker, "action": "buy", "quantity": "2", "price": "10",
        "currency": "EUR", "trade_date": "2024-01-02",
    }, headers=CSRF)
    assert response.status_code == 201, response.text


def test_precio_manual_con_fecha_futura_es_422():
    client = _client()
    _buy(client, "FUTPRC")
    tomorrow = (local_today() + timedelta(days=1)).isoformat()
    response = client.patch("/api/portfolio/prices", json={"ticker": "FUTPRC", "price": "12", "as_of": tomorrow}, headers=CSRF)
    assert response.status_code == 422, response.text
    ok = client.patch("/api/portfolio/prices", json={"ticker": "FUTPRC", "price": "12", "as_of": local_today().isoformat()}, headers=CSRF)
    assert ok.status_code == 200, ok.text


def test_tipo_de_cambio_con_fecha_futura_es_422():
    client = _client()
    body = {"base_currency": "EUR", "quote_currency": "SEK", "rate": "0.087",
            "rate_date": (local_today() + timedelta(days=1)).isoformat()}
    assert client.post("/api/portfolio/fx-rates", json=body, headers=CSRF).status_code == 422
    body["rate_date"] = local_today().isoformat()
    assert client.post("/api/portfolio/fx-rates", json=body, headers=CSRF).status_code == 201


def test_precio_manual_sin_fecha_usa_el_dia_de_madrid(monkeypatch):
    client = _client()
    _buy(client, "MADDAY")
    madrid_day = date.today() + timedelta(days=1)  # 00:30 en Madrid, aun «ayer» en UTC
    monkeypatch.setattr("app.services.portfolio_ledger_service.local_today", lambda: madrid_day)
    response = client.patch("/api/portfolio/prices", json={"ticker": "MADDAY", "price": "11"}, headers=CSRF)
    assert response.status_code == 200, response.text
    positions = {p["ticker"]: p for p in client.get("/api/portfolio/positions").json()["items"]}
    assert positions["MADDAY"]["as_of"] == madrid_day.isoformat()
