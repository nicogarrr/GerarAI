"""Una transaccion en peniques (GBp) no puede guardarse como libras (GBP)."""

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-minor-unit-secret-at-least-32-chars"


def test_canonical_currency_code_keeps_minor_units():
    from app.valuation.currency import canonical_currency_code

    assert canonical_currency_code("GBp") == "GBp"
    assert canonical_currency_code(" ZAc ") == "ZAc"
    assert canonical_currency_code("ILa") == "ILa"
    assert canonical_currency_code("gbx") == "GBX"
    assert canonical_currency_code("usd") == "USD"
    assert canonical_currency_code("GBP") == "GBP"


def test_post_and_put_keep_pence(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    seed()
    s = uuid4().hex[:8]
    tenant, user, ticker = f"gbp-{s}", f"user-{s}", f"G{s[:5]}.L".upper()
    client = TestClient(main.app)
    base = {"ticker": ticker, "action": "buy", "quantity": 10, "price": 425.5,
            "trade_date": "2026-01-02", "currency": "GBp"}
    r = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
                       json_body=base)
    assert r.status_code == 201, r.text
    assert r.json()["currency"] == "GBp"
    tid = r.json()["id"]

    r = signed_request(client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}",
                       json_body={**base, "price": 430})
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "GBp"
