"""GET /api/portfolio/tearsheet con response_model: el wire es el contrato.

La ruta devolvia schema free-form y el front tipaba a mano un SUBCONJUNTO
(sin qualification, sin trace y con exposure recortado). La rama
no_portfolio omite n_snapshots/n_returns de trace: la ruta usa
response_model_exclude_unset=True y aqui se comprueba la ausencia.
Servicio real contra SQLite, sin mock del payload.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Portfolio, PortfolioDailySnapshot, Tenant
from app.schemas.api import PortfolioTearsheetOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-tearsheet-route-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-tearsheet-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio tearsheet route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-tearsheet-user"


def _portfolio_with_history(tenant_ext: str, returns: list[str | None]) -> None:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    portfolio = Portfolio(name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.commit()
    base = date(2026, 10, 27)
    for i, ret in enumerate(returns):
        day = date.fromordinal(base.toordinal() + i)
        db.add(PortfolioDailySnapshot(
            portfolio_id=portfolio.id, snapshot_date=day,
            base_currency="EUR", positions_value_base=Decimal("600"),
            cash_value_base=Decimal("400"), total_value_base=Decimal("1000"),
            net_external_flow_base=Decimal("0"),
            daily_return=(Decimal(ret) if ret is not None else None),
            cumulative_twr=None, pricing_coverage=Decimal("1"),
            source="market_refresh",
        ))
    db.commit()
    db.close()


def test_tearsheet_no_portfolio_omits_trace_counts(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/tearsheet")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioTearsheetOut.model_validate(payload)
    assert payload["status"] == "no_portfolio"
    assert payload["metrics"] is None
    assert payload["qualification"] is None
    assert payload["exposure"] is None
    assert payload["trace"]["method"] == "tearsheet_numpy_pandas_v1"
    # Omision preservada por response_model_exclude_unset:
    assert "n_snapshots" not in payload["trace"]
    assert "n_returns" not in payload["trace"]


def test_tearsheet_insufficient_data_nulls(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _portfolio_with_history(tenant, [None])  # solo la foto base, sin retornos

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/tearsheet")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioTearsheetOut.model_validate(payload)
    assert payload["status"] == "insufficient_data"
    metrics = payload["metrics"]
    assert metrics["n_observations"] == 0
    for key in ("cumulative_return", "sharpe", "sortino", "max_drawdown", "win_rate"):
        assert metrics[key] is None
    assert metrics["periods_per_year"] == 252
    # Trazabilidad completa en la rama normal:
    assert payload["trace"]["n_snapshots"] == 1
    assert payload["trace"]["n_returns"] == 0
    # Una sola foto basta para la exposicion:
    assert payload["exposure"]["n_positions"] == 0
    assert payload["exposure"]["total_value_base"] == 1000.0
    assert payload["exposure"]["weight_bases"]["top_1_weight"] == "nav_with_cash"


def test_tearsheet_ok_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _portfolio_with_history(tenant, [None, "0.01", "-0.005", "0.02"])

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/tearsheet")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioTearsheetOut.model_validate(payload)
    assert payload["status"] == "ok"
    metrics = payload["metrics"]
    assert metrics["n_observations"] == 3
    # Medido del servicio: cumprod(1.01, 0.995, 1.02) - 1.
    assert metrics["cumulative_return"] == pytest.approx(0.025049, abs=1e-6)
    assert metrics["best_day"] == 0.02
    assert metrics["worst_day"] == -0.005
    assert metrics["win_rate"] == pytest.approx(2 / 3, abs=1e-9)
    assert metrics["sharpe"] is not None
    assert payload["qualification"]["continuous"] is True
    assert payload["qualification"]["series_breaks"] == 0
    assert payload["qualification"]["start_date"] == "2026-10-27"
    assert payload["qualification"]["end_date"] == "2026-10-30"
    assert payload["trace"]["n_snapshots"] == 4
    assert payload["trace"]["n_returns"] == 3
    exposure = payload["exposure"]
    assert exposure["snapshot_date"] == "2026-10-30"
    assert exposure["equity_weight"] == 0.6
    assert exposure["cash_weight"] == 0.4
    assert exposure["top_1_weight"] is None  # sin posiciones en la foto
