"""Comisiones con 4 decimales (IBKR cobra fracciones de céntimo, p. ej. 0,355 USD).

transactions.fees era Numeric(20, 2): 0,355 se guardaba como 0,36 en silencio y
el coste fiscal de la compra quedaba inflado/redondeado. Ahora Numeric(20, 4)
(migración 0103) y más de 4 decimales -> 422 en vez de redondear.
"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, Transaction
from main import app


def _post(client, **overrides):
    body = {
        "ticker": "FEE4DP", "action": "buy", "quantity": "10", "price": "100",
        "fees": "0.355", "currency": "USD", "trade_date": date(2025, 3, 3).isoformat(),
    }
    body.update(overrides)
    return client.post("/api/portfolio/transactions", json=body)


def _fees(ticker):
    with SessionLocal() as db:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            return []
        return [
            row.fees
            for row in db.scalars(select(Transaction).where(Transaction.company_id == company.id))
        ]


def test_comision_de_fraccion_de_centimo_se_guarda_exacta():
    init_db()
    client = TestClient(app)
    response = _post(client)
    assert response.status_code == 201, response.text
    assert response.json()["fees"] == 0.355
    assert _fees("FEE4DP") == [Decimal("0.3550")]
    listed = client.get("/api/portfolio/transactions").json()
    rows = listed if isinstance(listed, list) else listed.get("items", listed.get("transactions", []))
    assert [r["fees"] for r in rows if r["ticker"] == "FEE4DP"] == [0.355]


def test_mas_de_cuatro_decimales_se_rechaza_en_vez_de_redondear():
    init_db()
    client = TestClient(app)
    response = _post(client, ticker="FEE5DP", fees="0.35501")
    assert response.status_code == 422, response.text
    assert _fees("FEE5DP") == []
