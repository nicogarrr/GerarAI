"""PUT /api/portfolio/transactions/{id}: errores y persistencia real.

Complementa test_portfolio_transactions_put_route.py (wire 200, cash 400,
missing 404) con: edicion de una SELL (rama del guard buy/sell), 409 por
sobreventa y 422 por divisa mezclada, releyendo la persistencia despues de
cada respuesta. TestClient con firma ligada, servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-tx-put-errors-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-tx-put-err-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio tx put errors test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-tx-put-errors-user"


def _company(tenant_ext: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"TXE{uuid4().hex[:6].upper()}"
    db.add(Company(
        ticker=ticker, name="Tx put errors test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    return ticker


def _post(client, tenant, user, ticker, action, quantity, currency="EUR") -> int:
    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": action, "quantity": quantity, "price": "100",
            "trade_date": "2026-10-30", "fees": "0", "currency": currency,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _put(client, tenant, user, tx_id, ticker, action, quantity, currency="EUR"):
    return signed_request(
        client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tx_id}",
        json_body={
            "ticker": ticker, "action": action, "quantity": quantity, "price": "100",
            "trade_date": "2026-10-30", "currency": currency,
        },
    )


def _stored(client, tenant, user, tx_id: int) -> dict:
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/transactions")
    assert res.status_code == 200, res.text
    rows = res.json()["items"] if isinstance(res.json(), dict) else res.json()
    matches = [r for r in rows if r["id"] == tx_id]
    assert len(matches) == 1, rows
    return matches[0]


def test_put_sell_200_y_persistencia_releida(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    _post(client, tenant, user, ticker, "buy", "10")
    sell_id = _post(client, tenant, user, ticker, "sell", "4")

    res = _put(client, tenant, user, sell_id, ticker, "sell", "6")
    assert res.status_code == 200, res.text
    stored = _stored(client, tenant, user, sell_id)
    assert stored["action"] == "sell"
    assert stored["quantity"] == 6.0


def test_put_sobreventa_409_y_original_intacta(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    _post(client, tenant, user, ticker, "buy", "10")
    sell_id = _post(client, tenant, user, ticker, "sell", "6")

    res = _put(client, tenant, user, sell_id, ticker, "sell", "12")
    assert res.status_code == 409, res.text
    stored = _stored(client, tenant, user, sell_id)
    assert stored["quantity"] == 6.0


def test_put_divisa_mezclada_422_y_original_intacta(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    _post(client, tenant, user, ticker, "buy", "10")
    buy2_id = _post(client, tenant, user, ticker, "buy", "5")

    res = _put(client, tenant, user, buy2_id, ticker, "buy", "5", currency="USD")
    assert res.status_code == 422, res.text
    stored = _stored(client, tenant, user, buy2_id)
    assert stored["currency"] == "EUR"


def test_put_sin_firma_403_y_fila_completa_intacta(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    tx_id = _post(client, tenant, user, ticker, "buy", "10")
    antes = _stored(client, tenant, user, tx_id)

    res = client.put(
        f"/api/portfolio/transactions/{tx_id}",
        json={
            "ticker": ticker, "action": "buy", "quantity": "99", "price": "1",
            "trade_date": "2026-10-30", "currency": "EUR",
        },
    )
    assert res.status_code == 403
    assert _stored(client, tenant, user, tx_id) == antes


def test_put_de_otro_tenant_404_y_fila_completa_intacta(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    tx_id = _post(client, tenant, user, ticker, "buy", "10")
    antes = _stored(client, tenant, user, tx_id)

    db = SessionLocal()
    other_ext = f"portfolio-tx-put-other-{uuid4().hex[:8]}"
    db.add(Tenant(external_id=other_ext, name="Otro tenant"))
    db.commit()
    db.close()

    res = _put(client, other_ext, "intruso", tx_id, ticker, "buy", "99")
    assert res.status_code == 404
    assert _stored(client, tenant, user, tx_id) == antes
