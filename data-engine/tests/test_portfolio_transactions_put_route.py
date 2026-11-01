"""PUT /api/portfolio/transactions/{id} con response_model.

La edicion solo admite transacciones buy/sell (una accion de caja se
rechaza con 400 porque rebuild_position solo replaya buy/sell): la
respuesta encaja exactamente en PortfolioTransactionOut del listado.
Servicio real, sin mock del payload.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.schemas.api import PortfolioTransactionOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-tx-put-route-test-secret-32"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-tx-put-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio tx put route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-tx-put-user"


def _company_and_buy(client, tenant: str, user: str, suffix: str) -> tuple[str, int]:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"TXU{suffix}{uuid4().hex[:4].upper()}"
    db.add(Company(
        ticker=ticker, name="Tx put route test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "10", "price": "100",
            "trade_date": "2026-10-28", "currency": "EUR",
        },
    )
    assert res.status_code == 201, res.text
    return ticker, res.json()["id"]


def test_put_buy_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker, tx_id = _company_and_buy(client, tenant, user, "W")

    res = signed_request(
        client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tx_id}",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "12", "price": "101",
            "trade_date": "2026-10-29", "currency": "EUR", "fees": "2",
            "notes": "edicion",
        },
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioTransactionOut.model_validate(payload)
    assert payload["id"] == tx_id
    assert payload["action"] == "buy"
    assert payload["quantity"] == 12.0
    assert payload["price"] == 101.0
    assert payload["fees"] == 2.0
    assert payload["trade_date"] == "2026-10-29"
    assert payload["notes"] == "edicion"


def test_put_cash_action_rejected_400(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker, tx_id = _company_and_buy(client, tenant, user, "C")

    res = signed_request(
        client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tx_id}",
        json_body={
            "ticker": ticker, "action": "dividend", "quantity": "0", "price": "2",
            "trade_date": "2026-10-29", "currency": "EUR",
        },
    )

    assert res.status_code == 400, res.text


def test_put_missing_404(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(
        client, SECRET, tenant, user, "PUT", "/api/portfolio/transactions/999999999",
        json_body={
            "ticker": "ZZZZ", "action": "buy", "quantity": "1", "price": "1",
            "trade_date": "2026-10-29", "currency": "EUR",
        },
    )

    assert res.status_code == 404, res.text
