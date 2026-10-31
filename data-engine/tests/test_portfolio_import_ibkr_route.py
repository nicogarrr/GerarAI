"""POST /api/portfolio/import/ibkr con response_model (union discriminada).

Dos variantes medidas en la ruta: sin credenciales Flex ->
{status: not_configured, message}; con credenciales delega en
import_flex_xml (misma rama confirmada de 23 claves que /import/ibkr/xml).
El cliente Flex se sustituye por un doble en el camino importado (frontera
de red, precedente en test_ibkr_owner_csv_gate); el servicio de importacion
es el real. Servicio real, sin mock del payload.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.api.routes import portfolio as portfolio_module
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import PortfolioIbkrImportOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-ibkr-route-test-secret--"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-ibkr-route-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio ibkr route test"))
    db.commit()
    tenant_id = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one().id
    db.close()
    monkeypatch.setattr(
        portfolio_module,
        "get_settings",
        lambda: SimpleNamespace(
            ibkr_flex_tenant_id=tenant_id, ibkr_flex_account_id="U1"
        ),
    )
    return TestClient(main.app), tenant_ext, "portfolio-ibkr-route-user"


def test_not_configured_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    class NotConfiguredClient:
        def configured(self) -> bool:
            return False

    monkeypatch.setattr(portfolio_module, "IBKRFlexClient", NotConfiguredClient)

    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/import/ibkr")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioIbkrImportOut.model_validate(payload)
    # La variante not_configured: exactamente dos claves, nada del importado.
    assert set(payload) == {"status", "message"}
    assert payload["status"] == "not_configured"
    assert payload["message"]


def test_imported_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    day = date.today().strftime("%Y%m%d")
    xml = (
        '<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" '
        f'toDate="{day}"><Trade symbol="AAPL" tradeID="X1" buySell="BUY" '
        f'quantity="1" tradePrice="10" tradeDate="{day}"/>'
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )

    class ConfiguredClient:
        def configured(self) -> bool:
            return True

        async def fetch_latest_xml(self) -> str:
            return xml

    monkeypatch.setattr(portfolio_module, "IBKRFlexClient", ConfiguredClient)

    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/import/ibkr")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioIbkrImportOut.model_validate(payload)
    assert payload["status"] == "imported"
    assert payload["trades_imported"] == 1
    assert payload["row_errors"] == []
    assert "message" not in payload  # la otra variante no se filtra
