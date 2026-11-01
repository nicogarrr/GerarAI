"""POST /api/portfolio/transactions con response_model: el wire es el contrato.

La ruta acepta seis acciones (buy/sell + dividend/interest/fee/cash_misc)
pero el schema del listado GET solo contempla buy/sell: la respuesta del
POST necesita su propio contrato (PortfolioTransactionCreateOut) o un
movimiento de caja daria 500 al validar. Servicio real, sin mock.
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

SECRET = "portfolio-tx-post-route-test-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-tx-post-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio tx post route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-tx-post-user"


def _company(tenant_ext: str, suffix: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"TXP{suffix}{uuid4().hex[:4].upper()}"
    db.add(Company(
        ticker=ticker, name="Tx post route test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    return ticker


def test_create_buy_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant, "B")

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "10", "price": "100",
            "trade_date": "2026-10-30", "fees": "1.5", "currency": "EUR",
            "notes": "compra de prueba",
        },
    )

    assert res.status_code == 201, res.text
    payload = res.json()
    PortfolioTransactionCreateOut.model_validate(payload)
    assert payload["ticker"] == ticker
    assert payload["action"] == "buy"
    assert payload["quantity"] == 10.0
    assert payload["price"] == 100.0
    assert payload["fees"] == 1.5
    assert payload["currency"] == "EUR"
    assert payload["trade_date"] == "2026-10-30"
    assert payload["notes"] == "compra de prueba"
    assert payload["review_flag"] is None
    assert payload["id"] > 0


def test_create_cash_action_wire(monkeypatch) -> None:
    # dividend es una accion de caja legitima en el POST: con el Literal
    # buy/sell del listado esta respuesta habria dado 500 al validar.
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant, "D")

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "dividend", "quantity": "0",
            "price": "2.5", "trade_date": "2026-10-30", "currency": "EUR",
        },
    )

    assert res.status_code == 201, res.text
    payload = res.json()
    PortfolioTransactionCreateOut.model_validate(payload)
    assert payload["action"] == "dividend"
    assert payload["quantity"] == 0.0
    assert payload["price"] == 2.5


def test_create_oversell_409(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant, "S")

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "sell", "quantity": "5",
            "price": "100", "trade_date": "2026-10-30", "currency": "EUR",
        },
    )

    assert res.status_code == 409, res.text
