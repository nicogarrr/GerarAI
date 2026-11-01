"""Filas «vacías» que la API aceptaba por las puertas laterales.

``POST /transactions`` ya rechazaba una compra/venta de 0 acciones (lo hace
``PortfolioLedgerService.create_transaction``), pero el lote
(``/transactions/batch``) y la edición (``PUT /transactions/{id}``) escriben
la fila sin pasar por ese servicio: una compra de 0 acciones o una venta de 0
quedaban en el libro (una «venta» de 0 aparece como venta en el informe
fiscal). Y un dividendo o un interés de importe 0 se guardaba en todas las
puertas: «Dividendos (nº)» lo cuenta como un cobro que no existió.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Portfolio, Position, Tenant, Transaction
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "zero-amount-rows-secret-at-least-32-chars"


@pytest.fixture
def book(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    tenant = f"zero-rows-{suffix}"
    ticker = f"Z{suffix[:6]}".upper()
    client = TestClient(main.app)
    created = signed_request(
        client, SECRET, tenant, f"user-{suffix}", "POST", "/api/portfolio/transactions",
        json_body={"ticker": ticker, "action": "buy", "quantity": 4, "price": 25,
                   "trade_date": "2026-01-02", "currency": "EUR"},
    )
    assert created.status_code == 201, created.text
    yield {"client": client, "tenant": tenant, "user": f"user-{suffix}",
           "ticker": ticker, "transaction_id": created.json()["id"]}
    db = SessionLocal()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is not None:
        db.execute(delete(Transaction).where(Transaction.company_id == company.id))
        db.execute(delete(Position).where(Position.company_id == company.id))
        db.execute(delete(Company).where(Company.id == company.id))
    tenant_row = db.scalar(select(Tenant).where(Tenant.external_id == tenant))
    if tenant_row is not None:
        db.execute(delete(Portfolio).where(Portfolio.tenant_id == tenant_row.id))
        db.execute(delete(Tenant).where(Tenant.id == tenant_row.id))
    db.commit()
    db.close()


def _call(book: dict, method: str, path: str, body: dict):
    return signed_request(book["client"], SECRET, book["tenant"], book["user"],
                          method, path, json_body=body)


def _rows(book: dict) -> list[tuple[str, float, float]]:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == book["ticker"]))
        assert company is not None
        return [
            (row.action, float(row.quantity), float(row.price))
            for row in db.scalars(
                select(Transaction).where(Transaction.company_id == company.id)
                .order_by(Transaction.id)
            )
        ]
    finally:
        db.close()


def _row(book: dict, action: str, quantity, price) -> dict:
    return {"ticker": book["ticker"], "action": action, "quantity": quantity,
            "price": price, "trade_date": "2026-02-02", "currency": "EUR"}


@pytest.mark.parametrize("action", ["buy", "sell"])
def test_batch_rejects_a_zero_share_buy_or_sell(book, action):
    response = _call(book, "POST", "/api/portfolio/transactions/batch",
                     {"transactions": [_row(book, action, 0, 30)]})
    assert response.status_code == 400, response.text
    assert "quantity" in response.text
    assert _rows(book) == [("buy", 4.0, 25.0)]


@pytest.mark.parametrize("action", ["buy", "sell"])
def test_edit_rejects_a_zero_share_buy_or_sell(book, action):
    response = _call(book, "PUT", f"/api/portfolio/transactions/{book['transaction_id']}",
                     _row(book, action, 0, 30))
    assert response.status_code == 400, response.text
    assert _rows(book) == [("buy", 4.0, 25.0)]


@pytest.mark.parametrize("action", ["dividend", "interest"])
@pytest.mark.parametrize("quantity", [0, 1])
def test_create_rejects_a_zero_amount_dividend_or_interest(book, action, quantity):
    response = _call(book, "POST", "/api/portfolio/transactions",
                     _row(book, action, quantity, 0))
    assert response.status_code == 400, response.text
    assert "amount" in response.text
    assert _rows(book) == [("buy", 4.0, 25.0)]


def test_batch_rejects_a_zero_amount_dividend_and_keeps_nothing(book):
    response = _call(book, "POST", "/api/portfolio/transactions/batch", {"transactions": [
        _row(book, "dividend", 0, "1.20"),
        _row(book, "dividend", 0, 0),
    ]})
    assert response.status_code == 400, response.text
    assert "Transaction 1" in response.text
    assert _rows(book) == [("buy", 4.0, 25.0)]


def test_real_rows_still_pass(book):
    """Lo legítimo sigue entrando: dividendo con importe, compra a precio 0
    (acciones recibidas gratis / escisión) y venta a 0 (títulos sin valor)."""
    assert _call(book, "POST", "/api/portfolio/transactions",
                 _row(book, "dividend", 0, "1.20")).status_code == 201
    batch = _call(book, "POST", "/api/portfolio/transactions/batch", {"transactions": [
        _row(book, "buy", 2, 0), _row(book, "sell", 1, 0),
    ]})
    assert batch.status_code == 201, batch.text
    edit = _call(book, "PUT", f"/api/portfolio/transactions/{book['transaction_id']}",
                 _row(book, "buy", 5, 25))
    assert edit.status_code == 200, edit.text
