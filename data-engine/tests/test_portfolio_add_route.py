"""POST /api/portfolio/add con response_model: alias de /transactions.

Medido contra la ruta: /add delega en create_transaction, que ya tiene
response_model=PortfolioTransactionCreateOut; el alias hereda el mismo
contrato (201 + mismo payload). Servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.schemas.api import PortfolioTransactionCreateOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-add-route-test-secret--"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-add-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio add route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-add-user"


def test_add_alias_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"ADD{uuid4().hex[:4].upper()}"
    db.add(Company(
        ticker=ticker, name="Add route test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/add",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "5", "price": "20",
            "trade_date": "2026-10-30", "fees": "0", "currency": "EUR",
        },
    )

    assert res.status_code == 201, res.text
    payload = res.json()
    PortfolioTransactionCreateOut.model_validate(payload)
    assert payload["ticker"] == ticker
    assert payload["action"] == "buy"
    assert payload["quantity"] == 5.0
    assert payload["price"] == 20.0
    assert payload["trade_date"] == "2026-10-30"
    assert payload["id"] > 0
