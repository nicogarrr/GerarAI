"""PATCH /api/portfolio/prices con response_model.

Precio manual sobre una posicion: devuelve {ticker, market_price} medido.
DELETE /holdings/{ticker} (204 sin cuerpo) queda declarado en el PR como
sin wire que tipar. Servicio real, sin mock del payload.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.schemas.api import PortfolioPriceUpdateOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-prices-patch-test-secret-32"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-prices-patch-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio prices patch test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-prices-patch-user"


def _company_and_buy(client, tenant: str, user: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"PRC{uuid4().hex[:6].upper()}"
    db.add(Company(
        ticker=ticker, name="Prices patch test co", exchange="TEST",
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
    return ticker


def test_patch_price_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company_and_buy(client, tenant, user)

    res = signed_request(
        client, SECRET, tenant, user, "PATCH", "/api/portfolio/prices",
        json_body={"ticker": ticker, "price": "123.45"},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioPriceUpdateOut.model_validate(payload)
    assert payload["ticker"] == ticker
    assert payload["market_price"] == 123.45
    assert set(payload) == {"ticker", "market_price"}


def test_patch_price_unknown_ticker_404(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(
        client, SECRET, tenant, user, "PATCH", "/api/portfolio/prices",
        json_body={"ticker": f"ZZZ{uuid4().hex[:4].upper()}", "price": "10"},
    )

    assert res.status_code == 404, res.text
