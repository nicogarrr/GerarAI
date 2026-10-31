"""GET /api/portfolio/fx-rates con response_model: el wire es el contrato.

La ruta devolvia schema free-form sin tipo en el front ni verificacion de
contrato. Servicio real, sin mock del payload.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import FXRate, Tenant
from app.schemas.api import FXRateOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-fx-rates-route-test-secret-32c"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-fx-rates-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio fx-rates route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-fx-rates-user"


def test_fx_rates_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/fx-rates")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["items"] == []
    assert payload["page_info"]["total_items"] == 0


def test_fx_rates_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(FXRate(
        base_currency="EUR", quote_currency="USD", rate=Decimal("1.08"),
        rate_date=date(2026, 10, 30), source="BCE",
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/fx-rates")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["page_info"]["total_items"] == 1
    item = payload["items"][0]
    FXRateOut.model_validate(item)
    assert item["base_currency"] == "EUR"
    assert item["quote_currency"] == "USD"
    assert item["rate"] == 1.08
    assert item["rate_date"] == "2026-10-30"
    assert item["source"] == "BCE"
