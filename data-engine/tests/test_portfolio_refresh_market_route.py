"""POST /api/portfolio/refresh-market con response_model.

Envelope fijo (status/as_of/timestamps/order/stages) medido contra
MarketRefreshService.refresh; los stages varian claves por paso (la ruta
usa response_model_exclude_unset y el test comprueba ausencia/presencia).
Los bloques operativos internos (risk, alert_results, screen_results)
quedan free-form a proposito: tiparlos parcialmente borraria claves del
wire (response_model filtra lo no declarado). Servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import PortfolioRefreshMarketOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-refresh-market-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-refresh-market-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio refresh market test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-refresh-market-user"


def test_refresh_market_empty_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/refresh-market")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioRefreshMarketOut.model_validate(payload)
    assert payload["status"] in ("ok", "partial")
    assert payload["as_of"]
    assert payload["started_at"] <= payload["completed_at"]
    stages = {stage["name"]: stage for stage in payload["stages"]}
    assert payload["order"] == list(stages)
    # Claves por paso, medidas del servicio real:
    prices = stages["update_prices"]
    assert prices["step"] == 1
    assert prices["updated"] == 0
    assert "portfolio_snapshot_id" not in prices  # omision preservada
    revalue = stages["revalue_positions"]
    assert revalue["step"] == 3
    assert "portfolio_snapshot_id" in revalue
    assert "errors" not in revalue  # omision preservada
    risk_stage = stages["update_risk"]
    assert risk_stage["market_data_status"] in ("fresh", "stale")
    alerts = stages["evaluate_alerts"]
    assert alerts["alert_rules"] == 0
    assert alerts["saved_screens"] == 0
    # Bloques operativos free-form: presentes, contenido no filtrado.
    assert isinstance(payload["risk"], dict) and payload["risk"]
    assert payload["alert_results"] == []
    assert payload["screen_results"] == []
