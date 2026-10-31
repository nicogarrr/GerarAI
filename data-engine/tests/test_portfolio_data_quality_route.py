"""GET /api/portfolio/data-quality con response_model: el wire es el contrato.

La ruta devolvia schema free-form y el front tipaba a mano:
cost_review_positions, cost_unverified_positions y twr_chain llegaban sin
tipo. La rama sin cartera OMITE las dos claves de conciliacion: el wire
conserva la omision (response_model_exclude_unset=True). Servicio real,
sin mock del payload.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import (
    CashBalance,
    Company,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    Tenant,
)
from app.schemas.api import PortfolioDataQualityOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-data-quality-route-test-secret-32c"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-data-quality-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio data-quality route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-data-quality-user"


def test_data_quality_without_portfolio_omits_cost_keys(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/data-quality")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDataQualityOut.model_validate(payload)
    assert payload["status"] == "no_portfolio"
    assert payload["positions"] == 0
    assert payload["reasons"] == ["no_portfolio"]
    assert payload["twr_chain"]["status"] == "no_snapshots"
    # La rama sin cartera omite las claves de conciliacion: el wire NO las
    # rellena con null.
    assert "cost_review_positions" not in payload
    assert "cost_unverified_positions" not in payload


def test_data_quality_populated_portfolio(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    portfolio = Portfolio(name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    ticker = f"DQ{tenant[-2:].upper()}"
    db.add(Company(
        ticker=ticker, name="DQ Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    ))
    db.commit()
    company = db.query(Company).filter(Company.ticker == ticker).one()
    db.add(Position(
        company_id=company.id, portfolio_id=portfolio.id, quantity=Decimal("10"),
        currency="EUR", average_cost=Decimal("8"), market_price=Decimal("10"),
        market_value=Decimal("100"), unrealized_pnl=Decimal("20"),
        realized_pnl=Decimal("0"), cost_basis_native=Decimal("80"),
        cost_basis_base=Decimal("80"), market_value_base=Decimal("100"),
        as_of=date(2026, 10, 30),
    ))
    db.add(CashBalance(
        currency="EUR", balance=Decimal("500"), settled_cash=Decimal("500"),
        interest_rate=Decimal("0"), source="manual", as_of=date(2026, 10, 30),
    ))
    db.add(PortfolioDailySnapshot(
        portfolio_id=portfolio.id, snapshot_date=date(2026, 10, 30),
        base_currency="EUR", positions_value_base=Decimal("100"),
        cash_value_base=Decimal("500"), total_value_base=Decimal("600"),
        net_external_flow_base=Decimal("600"), daily_return=Decimal("0"),
        cumulative_twr=Decimal("0"), pricing_coverage=Decimal("1"),
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/data-quality")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDataQualityOut.model_validate(payload)
    assert payload["positions"] == 1
    assert payload["missing_cost_positions"] == 0
    # Claves sin tipo en el front, presentes con cartera:
    assert payload["cost_review_positions"] == 0
    assert payload["cost_unverified_positions"] == 0
    assert payload["twr_chain"] == {
        "status": "linked", "unlinked_snapshots": 0, "first_unlinked_date": None,
    }
    assert payload["cash_native"] == {"EUR": 500.0}
    assert payload["latest_snapshot_date"] == "2026-10-30"
    assert payload["latest_pricing_coverage"] == 1.0
    # Una sola foto no basta para una serie de retornos verificada.
    assert payload["status"] == "incomplete"
    assert "insufficient_verified_returns" in payload["reasons"]
