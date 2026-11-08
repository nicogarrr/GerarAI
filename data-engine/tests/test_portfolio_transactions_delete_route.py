"""DELETE /api/portfolio/transactions/{id} con auth real: contrato HTTP.

204 al borrar compraventa propia (buy y sell), 404 si no existe, si es un
movimiento de caja (solo buy/sell son borrables) o si es de otro tenant, y
403 sin firma. Servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-tx-delete-route-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-tx-del-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio tx delete route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-tx-delete-user"


def _company(tenant_ext: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"TXD{uuid4().hex[:6].upper()}"
    db.add(Company(
        ticker=ticker, name="Tx delete route test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    return ticker


def _post_tx(client, tenant, user, ticker, action="buy", quantity="10") -> int:
    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": action, "quantity": quantity, "price": "100",
            "trade_date": "2026-10-30", "fees": "0", "currency": "EUR",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _delete(client, tenant, user, tx_id: int):
    return signed_request(
        client, SECRET, tenant, user, "DELETE",
        f"/api/portfolio/transactions/{tx_id}",
    )


def test_delete_buy_y_sell_204_y_desaparecen(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    buy_id = _post_tx(client, tenant, user, ticker)
    sell_id = _post_tx(client, tenant, user, ticker, action="sell", quantity="4")

    assert _delete(client, tenant, user, sell_id).status_code == 204
    assert _delete(client, tenant, user, buy_id).status_code == 204
    # Ya no estan: un segundo DELETE da 404.
    assert _delete(client, tenant, user, buy_id).status_code == 404


def test_delete_inexistente_404(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    assert _delete(client, tenant, user, 99999999).status_code == 404


def test_delete_movimiento_de_caja_404(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    dividend_id = _post_tx(client, tenant, user, ticker, action="dividend", quantity="1")
    assert _delete(client, tenant, user, dividend_id).status_code == 404


def test_delete_sin_firma_403(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    tx_id = _post_tx(client, tenant, user, ticker)
    res = client.delete(f"/api/portfolio/transactions/{tx_id}")
    assert res.status_code == 403
    # Sigue ahi: con firma se puede borrar.
    assert _delete(client, tenant, user, tx_id).status_code == 204


def test_delete_de_otro_tenant_404(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _company(tenant)
    tx_id = _post_tx(client, tenant, user, ticker)

    db = SessionLocal()
    other_ext = f"portfolio-tx-del-other-{uuid4().hex[:8]}"
    db.add(Tenant(external_id=other_ext, name="Otro tenant"))
    db.commit()
    db.close()

    assert _delete(client, other_ext, "intruso", tx_id).status_code == 404
    # El original sigue intacto para su dueno.
    assert _delete(client, tenant, user, tx_id).status_code == 204
