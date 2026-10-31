"""Editar una operacion sin enviar `fees` no debe borrar la comision registrada."""

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-edit-fees-secret-at-least-32-chars"


def test_put_without_fees_preserves_recorded_fee(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    seed()
    s = uuid4().hex[:8]
    tenant, user, ticker = f"fee-{s}", f"user-{s}", f"F{s[:6]}".upper()
    client = TestClient(main.app)
    base = {"ticker": ticker, "action": "buy", "quantity": 4, "price": 25,
            "trade_date": "2026-01-02", "currency": "USD"}
    r = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
                       json_body={**base, "fees": 5})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["fees"] == 5

    r = signed_request(client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}",
                       json_body={**base, "price": 26})
    assert r.status_code == 200, r.text
    assert r.json()["price"] == 26
    assert r.json()["fees"] == 5

    r = signed_request(client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}",
                       json_body={**base, "price": 26, "fees": 2})
    assert r.json()["fees"] == 2



def test_put_with_future_trade_date_is_rejected_like_create(monkeypatch):
    """La fecha futura la rechaza el validador compartido del input (422) en
    create y en update. Este test fija el contrato en el PUT y que el rechazo
    no escribe nada."""
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    seed()
    s = uuid4().hex[:8]
    tenant, user, ticker = f"fut-{s}", f"user-{s}", f"U{s[:6]}".upper()
    client = TestClient(main.app)
    base = {"ticker": ticker, "action": "buy", "quantity": 4, "price": 25,
            "trade_date": "2026-01-02", "currency": "USD"}
    r = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
                       json_body=base)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = signed_request(client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}",
                       json_body={**base, "trade_date": "2999-01-02"})
    assert r.status_code == 422, r.text
    assert "trade_date" in str(r.json()["detail"])

    # La operacion conserva su fecha original: el 400 no escribio nada.
    r = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/transactions")
    mine = [row for row in r.json()["items"] if row["id"] == tid]
    assert mine and mine[0]["trade_date"] == "2026-01-02"
