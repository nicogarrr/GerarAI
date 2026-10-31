"""Cantidades y precios con más decimales de los que guarda la base.

Transaction.quantity y .price son Numeric(20, 6): una compra de 0,0000004
acciones pasaba la validación (> 0), se guardaba como 0,000000 y dejaba en el
libro una compra de cero acciones (o una venta que no vendía nada).
"""

from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, Transaction
from main import app
from tests.auth_helpers import csrf_client


def _post(client, **overrides):
    body = {
        "ticker": "SUBMICRO", "action": "buy", "quantity": "0.0000004",
        "price": "10", "currency": "USD", "trade_date": date(2025, 1, 2).isoformat(),
    }
    body.update(overrides)
    return client.post("/api/portfolio/transactions", json=body)


def _rows(ticker):
    with SessionLocal() as db:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            return []
        return list(db.scalars(select(Transaction).where(Transaction.company_id == company.id)))


def test_cantidad_que_redondea_a_cero_se_rechaza():
    init_db()
    client = csrf_client(app)
    response = _post(client)
    assert response.status_code == 422, response.text
    assert _rows("SUBMICRO") == []


def test_precio_que_redondea_a_cero_no_es_compra_gratis():
    init_db()
    client = csrf_client(app)
    response = _post(client, ticker="SUBMICRP", quantity="1", price="0.0000004")
    assert response.status_code == 422, response.text


def test_seis_decimales_siguen_valiendo():
    init_db()
    client = csrf_client(app)
    response = _post(client, ticker="MICROOK", quantity="0.000001")
    assert response.status_code == 201, response.text
    assert [row.quantity for row in _rows("MICROOK")] == [__import__("decimal").Decimal("0.000001")]
