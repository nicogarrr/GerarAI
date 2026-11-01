"""GET/PUT /api/portfolio/configuration con response_model: el wire es el
contrato.

Las rutas devolvian schema free-form y el front tipaba a mano: id, name,
is_default y el contenido de fx_source llegaban sin tipo estricto, y el
PUT devolvia un payload distinto (sin tax_currency ni fx_source) que el
front tipaba con el mismo tipo del GET. Servicio real, sin mock del
payload.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Portfolio, Tenant
from app.schemas.api import PortfolioConfigurationOut, PortfolioConfigurationUpdateOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-configuration-route-test-32ch"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-configuration-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio configuration route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-configuration-user"


def test_configuration_defaults_without_portfolio(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/configuration")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioConfigurationOut.model_validate(payload)
    assert payload["id"] is None
    assert payload["name"] == "Main"
    assert payload["base_currency"] == "EUR"
    assert payload["is_default"] is True
    assert payload["tax_currency"] == "EUR"
    # Sin tipos de cambio cargados: la fuente se declara vacia, no inventada.
    assert payload["fx_source"] == {
        "source": None, "latest_rate_date": None, "base_currency": "EUR",
    }


def test_configuration_put_returns_update_shape(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()
    db.close()

    res = signed_request(
        client, SECRET, tenant, user, "PUT", "/api/portfolio/configuration",
        json_body={"base_currency": "USD"},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioConfigurationUpdateOut.model_validate(payload)
    assert payload["base_currency"] == "USD"
    assert payload["name"] == "Main"
    # El PUT no devuelve tax_currency ni fx_source (shape distinta del GET).
    assert "tax_currency" not in payload
    assert "fx_source" not in payload

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/configuration")
    assert res.status_code == 200, res.text
    assert res.json()["base_currency"] == "USD"
