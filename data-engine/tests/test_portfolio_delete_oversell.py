"""DELETE de una compra con una venta dependiente: debe rechazarse (409) y conservar ambas patas."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Transaction
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-delete-oversell-secret-at-least-32-chars"


def test_delete_buy_with_dependent_sell_is_rejected_and_rolled_back(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    tenant, user, ticker = f"del-{suffix}", f"user-{suffix}", f"D{suffix[:6]}".upper()
    client = TestClient(main.app, raise_server_exceptions=False)

    def post(action, qty, price, day):
        r = signed_request(
            client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
            json_body={"ticker": ticker, "action": action, "quantity": qty, "price": price,
                       "trade_date": day},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    buy_id = post("buy", 10, 5, "2026-01-02")
    post("sell", 6, 6, "2026-01-05")

    r = signed_request(client, SECRET, tenant, user, "DELETE",
                       f"/api/portfolio/transactions/{buy_id}")
    assert r.status_code == 409, (r.status_code, r.text[:200])

    db = SessionLocal()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    legs = db.scalar(select(func.count()).select_from(Transaction)
                     .where(Transaction.company_id == company.id))
    db.close()
    assert legs == 2
