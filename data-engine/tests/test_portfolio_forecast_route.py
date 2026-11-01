"""GET /api/portfolio/forecast con response_model: el wire es el contrato.

La ruta (agregacion inline determinista) devolvia schema free-form y el tipo
manuscrito del front no contemplaba reason_code "valuation_hold". Servicio
real contra SQLite, sin mock del payload.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Position, Tenant, ThesisVersion
from app.schemas.api import PortfolioForecastOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-forecast-route-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-forecast-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio forecast route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-forecast-user"


def _seed_position(tenant_ext: str, *, with_base_value: bool, ticker_suffix: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    suffix = uuid4().hex[:4].upper()
    company = Company(
        ticker=f"FRC{ticker_suffix}{suffix}", name="Forecast route test co",
        exchange="TEST", currency="EUR", company_type="stock", valuation_model="dcf",
    )
    db.add(company)
    db.flush()
    db.add(Position(
        company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("90"),
        market_price=Decimal("100"), market_value=Decimal("1000"), currency="EUR",
        market_value_base=(Decimal("1000") if with_base_value else None),
    ))
    db.commit()
    ticker = company.ticker
    db.close()
    return ticker


def test_forecast_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/forecast")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioForecastOut.model_validate(payload)
    assert payload["as_of"] is None
    assert payload["base_currency"] is None
    assert payload["portfolio"] is None
    assert payload["positions"] == []
    assert payload["excluded"] == []
    assert payload["assumptions"] == ["Sin posiciones: no hay previsión que calcular."]


def test_forecast_excluded_no_base_value(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _seed_position(tenant, with_base_value=False, ticker_suffix="X")

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/forecast")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioForecastOut.model_validate(payload)
    mine = [e for e in payload["excluded"] if e["ticker"] == ticker]
    assert len(mine) == 1
    assert mine[0]["reason_code"] == "no_base_value"
    assert mine[0]["weight"] is None
    # Sin ninguna posicion valorada del tenant: agregados N/D, nunca fabricados.
    own = [p for p in payload["positions"] if p["ticker"] == ticker]
    assert own == []


def test_forecast_covered_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _seed_position(tenant, with_base_value=True, ticker_suffix="W")
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    company = db.query(Company).filter(Company.ticker == ticker).one()
    db.add(ThesisVersion(
        company_id=company.id, version=1, status="published",
        thesis_markdown="t", executive_summary="t",
        bear_value=Decimal("80"), base_value=Decimal("120"), bull_value=Decimal("160"),
        scenario_probabilities={"bear": 0.25, "base": 0.5, "bull": 0.25},
        valuation_basis={"value_per_share_basis": "ordinary_share"},
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/forecast")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioForecastOut.model_validate(payload)
    mine = [p for p in payload["positions"] if p["ticker"] == ticker]
    assert len(mine) == 1
    pos = mine[0]
    # Medido del servicio: (intrinseco/precio)^(1/5)-1 con precio 100.
    assert pos["cagr"]["base"] == pytest.approx(1.2 ** 0.2 - 1.0, abs=1e-9)
    assert pos["cagr"]["bear"] == pytest.approx(0.8 ** 0.2 - 1.0, abs=1e-9)
    assert pos["total_return"]["bull"] == pytest.approx(0.6, abs=1e-9)
    assert pos["horizon_years"] == 5  # sin modelo vigente: horizonte por defecto
    assert pos["thesis_version"] == 1
    assert pos["thesis_status"] == "published"
    assert pos["model_version"] is None
    assert pos["comparison_basis"] == "ordinary_share"
    assert pos["probabilities"] == {"bear": 0.25, "base": 0.5, "bull": 0.25}
    assert pos["probability_mass"] == pytest.approx(1.0)
    assert pos["expected_cagr"] is not None
    assert pos["contribution_expected"] == pytest.approx(pos["weight"] * pos["expected_cagr"])
    assert pos["weight_scope"] in ("total_portfolio", "valued_subset")
    assert pos["price_veracity"] in ("OFICIAL", "MANUAL/NO OFICIAL", "NO VERIFICADA")


def test_forecast_intrinsic_scenario_none(monkeypatch) -> None:
    # Tesis sin bear_value: el escenario bear llega como null DENTRO de
    # intrinsic (nunca se inventa) y desaparece de cagr/total_return.
    client, tenant, user = _client(monkeypatch)
    ticker = _seed_position(tenant, with_base_value=True, ticker_suffix="N")
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    company = db.query(Company).filter(Company.ticker == ticker).one()
    db.add(ThesisVersion(
        company_id=company.id, version=1, status="published",
        thesis_markdown="t", executive_summary="t",
        bear_value=None, base_value=Decimal("120"), bull_value=Decimal("160"),
        scenario_probabilities={"base": 0.6, "bull": 0.4},
        valuation_basis={"value_per_share_basis": "ordinary_share"},
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/forecast")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioForecastOut.model_validate(payload)
    mine = [p for p in payload["positions"] if p["ticker"] == ticker]
    assert len(mine) == 1
    pos = mine[0]
    assert pos["intrinsic"]["bear"] is None
    assert pos["intrinsic"]["base"] == 120.0
    assert "bear" not in pos["cagr"]
    assert "bear" not in pos["total_return"]
