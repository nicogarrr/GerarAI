"""POST /api/portfolio/transactions/batch con response_model.

La ruta devolvia {created, transaction_ids, transactions} free-form. Lote
atomico: si una transaccion falla, ninguna se persiste. Servicio real
contra SQLite, sin mock del payload.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, Transaction
from app.schemas.api import PortfolioTransactionBatchOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-tx-batch-route-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-tx-batch-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio tx batch route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-tx-batch-user"


def _company(tenant_ext: str, suffix: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"TXB{suffix}{uuid4().hex[:4].upper()}"
    db.add(Company(
        ticker=ticker, name="Tx batch route test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    return ticker


def test_batch_two_buys_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant, "B")

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions/batch",
        json_body={"transactions": [
            {"ticker": ticker, "action": "buy", "quantity": "10", "price": "100",
             "trade_date": "2026-10-28", "currency": "EUR"},
            {"ticker": ticker, "action": "buy", "quantity": "5", "price": "110",
             "trade_date": "2026-10-29", "currency": "EUR", "fees": "0.5"},
        ]},
    )

    assert res.status_code == 201, res.text
    payload = res.json()
    PortfolioTransactionBatchOut.model_validate(payload)
    assert payload["created"] == 2
    assert len(payload["transaction_ids"]) == 2
    assert len(payload["transactions"]) == 2
    assert payload["transaction_ids"] == [t["id"] for t in payload["transactions"]]
    first, second = payload["transactions"]
    assert first["quantity"] == 10.0 and first["price"] == 100.0
    assert second["quantity"] == 5.0 and second["fees"] == 0.5
    assert all(t["ticker"] == ticker for t in payload["transactions"])


def test_batch_atomic_rollback_on_oversell(monkeypatch) -> None:
    # La segunda venta excede lo mantenido: el lote entero hace rollback.
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant, "R")

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions/batch",
        json_body={"transactions": [
            {"ticker": ticker, "action": "buy", "quantity": "10", "price": "100",
             "trade_date": "2026-10-28", "currency": "EUR"},
            {"ticker": ticker, "action": "sell", "quantity": "99", "price": "100",
             "trade_date": "2026-10-29", "currency": "EUR"},
        ]},
    )

    assert res.status_code in (400, 409, 422), res.text
    # Atomicidad medida: la compra del lote tampoco quedo persistida.
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    company = db.query(Company).filter(Company.ticker == ticker).one()
    remaining = db.query(Transaction).filter(Transaction.company_id == company.id).count()
    db.close()
    assert remaining == 0
