"""GET /api/portfolio/snapshots con response_model: el wire es el contrato.

La ruta devolvia schema free-form y el front tipaba un subconjunto a mano:
id, portfolio_id, positions_value_base, cash_value_base y source llegaban
sin tipo. La primera foto de la serie es base: daily_return y
cumulative_twr llegan como null. Servicio real, sin mock del payload.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Portfolio, PortfolioDailySnapshot, Tenant
from app.schemas.api import PortfolioSnapshotOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-snapshots-route-test-secret-32c"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-snapshots-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio snapshots route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-snapshots-user"


def test_snapshots_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/snapshots")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["items"] == []
    assert payload["page_info"]["total_items"] == 0


def test_snapshots_wire_with_null_return_base(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    portfolio = Portfolio(name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.commit()
    db.add_all([
        # Primera foto: base de la cadena TWR, sin retorno por diseno.
        PortfolioDailySnapshot(
            portfolio_id=portfolio.id, snapshot_date=date(2026, 10, 29),
            base_currency="EUR", positions_value_base=Decimal("100"),
            cash_value_base=Decimal("500"), total_value_base=Decimal("600"),
            net_external_flow_base=Decimal("600"), daily_return=None,
            cumulative_twr=None, pricing_coverage=Decimal("1"),
            source="market_refresh",
        ),
        PortfolioDailySnapshot(
            portfolio_id=portfolio.id, snapshot_date=date(2026, 10, 30),
            base_currency="EUR", positions_value_base=Decimal("110"),
            cash_value_base=Decimal("500"), total_value_base=Decimal("610"),
            net_external_flow_base=Decimal("0"), daily_return=Decimal("0.0167"),
            cumulative_twr=Decimal("0.0167"), pricing_coverage=Decimal("1"),
            source="market_refresh", metadata_={"twr_base_after_scope_change": False},
        ),
    ])
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/snapshots")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["page_info"]["total_items"] == 2
    items = {item["snapshot_date"]: item for item in payload["items"]}
    for item in items.values():
        PortfolioSnapshotOut.model_validate(item)

    base = items["2026-10-29"]
    assert base["daily_return"] is None
    assert base["cumulative_twr"] is None
    # Claves sin tipo en el front:
    assert base["positions_value_base"] == 100.0
    assert base["cash_value_base"] == 500.0
    assert base["source"] == "market_refresh"

    second = items["2026-10-30"]
    assert second["daily_return"] == 0.0167
    assert second["cumulative_twr"] == 0.0167
    assert second["metadata"] == {"twr_base_after_scope_change": False}
    assert second["portfolio_id"] == portfolio.id
