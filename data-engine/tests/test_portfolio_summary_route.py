"""GET /api/portfolio/summary con response_model: el wire es el contrato.

La ruta devolvia schema free-form y el front tipaba a mano: top_1_weight,
top_5_weight, alerts, cash_native y provenance llegaban sin tipo. Estos
tests ejercitan la respuesta HTTP real con RiskService.dashboard real (sin
mock del payload).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Portfolio, Position, Tenant
from app.schemas.api import PortfolioSummaryOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-summary-route-test-secret-32-chars"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-summary-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio summary route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-summary-user"


def test_summary_empty_portfolio_validates_full_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/summary")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioSummaryOut.model_validate(payload)
    # Claves que el tipo TS manuscrito no conocia (deriva silenciosa previa).
    assert payload["top_1_weight"] == 0
    assert payload["top_5_weight"] == 0
    assert payload["alerts"] == []
    assert payload["cash_native"] == {}
    assert payload["provenance"]["source_kind"] == "internal"
    assert payload["status"] == "ok"
    assert payload["data_as_of"] is None
    assert payload["cash_as_of"] is None
    assert payload["valuation_dates_differ"] is False


def test_summary_weight_alert_and_cash_native(monkeypatch) -> None:
    """Una posicion con el 100 % del peso dispara la alerta >20 % y la caja
    nativa se publica por divisa. Formas medidas con el servicio real."""
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker="SUM", name="SUM", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(Position(
        company_id=company.id, quantity=Decimal("10"), currency="EUR",
        market_value=Decimal("1000"), market_value_base=Decimal("1000"),
        as_of=date(2026, 10, 30),
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/summary")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioSummaryOut.model_validate(payload)
    assert payload["equity_value"] == 1000.0
    assert payload["top_1_weight"] == 1.0
    alert = next(a for a in payload["alerts"] if a["ticker"] == "SUM")
    assert alert["severity"] == "high"
    assert alert["threshold"] == 0.2
    assert payload["base_currency"] == "EUR"
    assert payload["data_as_of"] == "2026-10-30"
