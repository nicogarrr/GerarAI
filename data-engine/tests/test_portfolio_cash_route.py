"""GET /api/portfolio/cash con response_model: el wire es el contrato.

La ruta devolvia una lista free-form (SELECT CashBalance directo, sin
servicio). Sin consumidor en el front: el contrato lo fija el
response_model. Servicio real contra SQLite, sin mock del payload.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import CashBalance, Tenant
from app.schemas.api import CashBalanceOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-cash-route-test-secret-32ch"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-cash-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio cash route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-cash-user"


def test_cash_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/cash")

    assert res.status_code == 200, res.text
    assert res.json() == []


def test_cash_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(CashBalance(
        currency="EUR", balance=Decimal("1234.56"), settled_cash=Decimal("1200.00"),
        interest_rate=Decimal("0.015"), source="ibkr",
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/cash")

    assert res.status_code == 200, res.text
    payload = res.json()
    mine = [row for row in payload if row["currency"] == "EUR" and row["source"] == "ibkr"]
    assert len(mine) == 1
    row = mine[0]
    CashBalanceOut.model_validate(row)
    assert row["balance"] == 1234.56
    assert row["settled_cash"] == 1200.0
    assert row["interest_rate"] == 0.015
    assert set(row) == {"currency", "balance", "settled_cash", "interest_rate", "source"}
