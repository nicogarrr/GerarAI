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


def test_ledger_position_schema_accepts_null_flows() -> None:
    """El schema admite contribution/valores/flujos en null: los emite la
    rama de ledger no reconciliable del servicio (missing_ledger, ejercitada
    por HTTP en el test de cartera poblada; incomplete_ledger se cubre en
    los tests de servicio). El front los tipaba como number."""
    PortfolioLedgerPositionOut.model_validate(
        {
            "ticker": "ASTS",
            "contribution_pnl": None,
            "contribution_share": None,
            "end_value": 1234.5,
            "start_value": None,
            "net_invested": None,
            "income": None,
            "reason": None,
        }
    )


def test_intelligence_populated_portfolio_http(monkeypatch) -> None:
    """Cartera poblada por HTTP con el servicio real: tenant SQLite, una
    posicion EUR y dos precios. La posicion no tiene valor en divisa base
    (market_value_base None): el peso usa el fallback nativo EUR (sin
    missing_fx) pero ledger_contribution declara la razon y deja la
    contribucion en null en lugar de inventar un P&L."""
    from datetime import date
    from decimal import Decimal

    from app.models import Company, MarketPrice, Portfolio, Position

    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker="POP", name="POP", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(Position(
        company_id=company.id, quantity=Decimal("10"), currency="EUR",
        market_value=Decimal("1100"), market_value_base=None,
        as_of=date(2026, 10, 30),
    ))
    for day, close in [(28, "10"), (29, "11")]:
        db.add(MarketPrice(
            company_id=company.id, date=date(2026, 10, day),
            open=Decimal(close), high=Decimal(close), low=Decimal(close),
            close=Decimal(close), adj_close=Decimal(close), source="yfinance",
        ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/intelligence")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioIntelligenceOut.model_validate(payload)

    # Peso con fallback nativo (EUR = divisa base): sin missing_fx.
    assert payload["missing_fx"] == []
    assert payload["concentration"]["weights"] == {"POP": 1.0}

    # Attribution: retorno medido de los dos extremos ajustados (11/10 - 1).
    position = payload["attribution"]["positions"][0]
    assert position["ticker"] == "POP"
    assert abs(position["total_return"] - 0.1) < 1e-9
    assert position["fx_known"] is True
    # Sin filas de dividendos el componente es desconocido (null-propagante),
    # no cero supuesto.
    assert position["dividends_known"] is False
    assert position["partial_history"] is False

    # Ledger: sin operaciones no hay ledger que reconciliar: el P&L y los
    # flujos son desconocidos (null) con la razon declarada, nunca ceros.
    ledger = payload["ledger_contribution"]["positions"][0]
    assert ledger["ticker"] == "POP"
    assert ledger["reason"] == "missing_ledger"
    assert ledger["contribution_pnl"] is None
    assert ledger["start_value"] is None
    assert ledger["net_invested"] is None
    assert ledger["income"] is None
    assert payload["ledger_contribution"]["base_currency"] == "EUR"
