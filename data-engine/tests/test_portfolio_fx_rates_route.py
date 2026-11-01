"""POST /api/portfolio/fx-rates con response_model.

Forma medida contra la ruta (dict literal de 6 claves, todas siempre
presentes): misma forma que FXRateOut del GET paginado, se reutiliza el
schema. Input medido contra FXRateInput y PortfolioFXService.upsert_rate
(divisas ISO de 3 letras, rate > 0, rate_date no futura). Servicio real,
sin mock.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import FXRateOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-fx-rates-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-fx-rates-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio fx rates test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-fx-rates-user"


def test_upsert_fx_rate_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    today = date.today().isoformat()

    res = signed_request(
        client,
        SECRET,
        tenant,
        user,
        "POST",
        "/api/portfolio/fx-rates",
        json_body={
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": 0.9,
            "rate_date": today,
            "source": "manual",
        },
    )

    assert res.status_code == 201, res.text
    payload = res.json()
    FXRateOut.model_validate(payload)
    # Las 6 claves del dict literal de la ruta, ni una mas ni una menos.
    assert set(payload) == {
        "id",
        "base_currency",
        "quote_currency",
        "rate",
        "rate_date",
        "source",
    }
    assert payload["base_currency"] == "USD"
    assert payload["quote_currency"] == "EUR"
    assert payload["rate"] == 0.9
    assert payload["rate_date"] == today
    assert payload["source"] == "manual"
