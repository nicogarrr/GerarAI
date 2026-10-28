"""Importes fuera de rango en una transacción no pueden envenenar la posición.

Encontrado con Schemathesis + sondas de entrada: ``price="1e400"`` pasaba la
validación (Decimal finito, >= 0), se guardaba como precio nulo/infinito en la
columna Numeric(20, 6) y, a partir de ahí, CADA transacción nueva del mismo
ticker respondía 500 (decimal.InvalidOperation al recalcular la posición).
En Postgres el mismo valor revienta al insertar. Los importes deben caber en la
columna: 422 antes de tocar la base de datos.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core.database import init_db


@pytest.fixture()
def client():
    init_db()
    return TestClient(main.app, raise_server_exceptions=False)


def _tx(ticker: str, **overrides):
    body = {"ticker": ticker, "action": "buy", "quantity": 3, "price": 100,
            "trade_date": "2024-01-15", "currency": "USD"}
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("field", "value"),
    [("price", "1e400"), ("price", "1e15"), ("quantity", "1e30"), ("quantity", "1e14"), ("fees", "1e40")],
)
def test_amount_that_does_not_fit_the_column_is_rejected(client, field, value):
    ticker = f"T{uuid4().hex[:6].upper()}"
    response = client.post("/api/portfolio/transactions", json=_tx(ticker, **{field: value}))
    assert response.status_code == 422, (response.status_code, response.text[:300])


def test_one_bad_amount_does_not_break_the_next_transactions(client):
    ticker = f"T{uuid4().hex[:6].upper()}"
    client.post("/api/portfolio/transactions", json=_tx(ticker, price="1e400"))
    ok = client.post("/api/portfolio/transactions", json=_tx(ticker))
    assert ok.status_code == 201, (ok.status_code, ok.text[:300])
    assert ok.json()["price"] == 100.0


def test_large_but_valid_amounts_still_work(client):
    ticker = f"T{uuid4().hex[:6].upper()}"
    response = client.post(
        "/api/portfolio/transactions",
        json=_tx(ticker, quantity="1000000", price="99999.123456", fees="12.5"),
    )
    assert response.status_code == 201, response.text[:300]


def test_update_applies_the_same_bounds(client):
    ticker = f"T{uuid4().hex[:6].upper()}"
    created = client.post("/api/portfolio/transactions", json=_tx(ticker))
    assert created.status_code == 201, created.text[:300]
    tx_id = created.json()["id"]
    response = client.put(f"/api/portfolio/transactions/{tx_id}", json=_tx(ticker, price="1e400"))
    assert response.status_code == 422, (response.status_code, response.text[:300])
