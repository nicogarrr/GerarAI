"""GET /api/portfolio/intelligence con response_model: el wire es el contrato.

La ruta devolvia un schema free-form y el front tipaba a mano. Al modelar el
payload real del servicio aparecieron derivas: el front no conocia missing_fx,
twr_period, reconstruction, valuation_history, partial_trading_day,
spot_tail_positions, fx_known ni dividends_known, y tipaba
ledger_contribution.positions[].net_invested/income como number cuando la rama
de reconciliacion fallida del servicio emite None. Estos tests ejercitan la
respuesta HTTP real con el servicio real (sin mock del payload): si
response_model recorta un campo o rechaza un null legitimo, fallan.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import PortfolioIntelligenceOut, PortfolioLedgerPositionOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-intelligence-route-test-secret-32-chars"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-intel-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio intelligence route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-intel-user"


def test_intelligence_empty_portfolio_validates_full_wire(monkeypatch) -> None:
    """Cartera vacia con el servicio real: todas las secciones en su rama
    vacia deben validar contra el response_model (sin 500) y el wire conserva
    las claves que el front tipaba a mano."""
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/intelligence")

    assert res.status_code == 200, res.text
    payload = res.json()
    # Revalidacion completa: ningun null legitimo rechazado ni campo extra.
    PortfolioIntelligenceOut.model_validate(payload)
    # Claves que el tipo TS manuscrito no conocia (deriva silenciosa previa).
    assert "missing_fx" in payload
    assert payload["performance"]["twr_method"] == "static_current_weight_estimate"
    assert "twr_period" in payload["performance"]
    assert "reconstruction" in payload["performance"]
    assert "valuation_history" in payload["performance"]
    assert payload["coverage"]["partial_trading_day"] is False
    assert payload["coverage"]["spot_tail_positions"] == []
    assert payload["benchmark"]["status"] in {
        "calculated",
        "missing_benchmark",
        "insufficient_overlap",
    }
    # Sin posiciones no hay series: metricas null, nunca numeros inventados.
    assert payload["performance"]["twr"] is None
    assert payload["risk"]["max_drawdown"] is None
    assert payload["ledger_contribution"]["positions"] == []
    # Rama vacia: el servicio omite base_currency (ausente, no null).
    assert "base_currency" not in payload["ledger_contribution"]


def test_ledger_position_reconciliation_branch_emits_null_flows() -> None:
    """La rama de reconciliacion fallida del servicio (cantidades que no
    cuadran tras ajustes corporativos) emite contribution_pnl/end_value/
    start_value/net_invested/income en None con la razon. Literal medido en
    PortfolioIntelligenceService._ledger_contribution; el front tipaba
    net_invested e income como number."""
    PortfolioLedgerPositionOut.model_validate(
        {
            "ticker": "ASTS",
            "contribution_pnl": None,
            "contribution_share": None,
            "end_value": 1234.5,
            "start_value": None,
            "net_invested": None,
            "income": None,
            "reason": "quantity_mismatch_after_corporate_actions",
        }
    )
