"""GET /api/portfolio/positions con response_model: el wire es el contrato.

La ruta devolvia schema free-form y el front tipaba a mano: name, sector y
source llegaban sin tipo, y market_value_native estaba tipado como number
aunque la rama de valoracion en suspenso lo emite como null. Estos tests
ejercitan la respuesta HTTP real con el servicio real (sin mock del
payload): posicion valorada, valoracion en suspenso y precio del ledger
sin cotizacion (quote_missing anula las plusvalias).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Portfolio, Position, Tenant, Transaction
from app.schemas.api import PortfolioPositionItemOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-positions-route-test-secret-32-chars"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-positions-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio positions route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-positions-user"


def _seed(tenant: str) -> None:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    valued = Company(
        ticker="VAL", name="Valued Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    held = Company(
        ticker="HELD", name="Held Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    ledger = Company(
        ticker="LED", name="Ledger Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add_all([valued, held, ledger])
    db.commit()
    db.add_all([
        Position(
            company_id=valued.id, quantity=Decimal("100"), currency="EUR",
            average_cost=Decimal("8"), market_price=Decimal("10"),
            market_value=Decimal("1000"), unrealized_pnl=Decimal("200"),
            realized_pnl=Decimal("5"), market_value_native=Decimal("1000"),
            market_value_base=Decimal("1000"), cost_basis_native=Decimal("800"),
            cost_basis_base=Decimal("800"), unrealized_pnl_base=Decimal("200"),
            realized_pnl_base=Decimal("5"), as_of=date(2026, 10, 30),
        ),
        Position(
            company_id=held.id, quantity=Decimal("10"), currency="EUR",
            average_cost=Decimal("50"), market_price=Decimal("60"),
            market_value=Decimal("600"), unrealized_pnl=Decimal("100"),
            realized_pnl=Decimal("0"), as_of=date(2026, 10, 30),
            valuation_hold_reason="split_pending",
            valuation_hold_effective_date=date(2026, 10, 1),
            valuation_hold_since=date(2026, 9, 15),
        ),
        Position(
            company_id=ledger.id, quantity=Decimal("100"), currency="EUR",
            average_cost=Decimal("10"), market_price=Decimal("10"),
            market_value=Decimal("1000"), unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"), source="postgres_ledger",
            cost_basis_native=Decimal("1000"), cost_basis_base=Decimal("1000"),
            unrealized_pnl_base=Decimal("0"),
            as_of=date(2026, 10, 30),
        ),
        Transaction(
            company_id=ledger.id, trade_date=date(2026, 1, 15), action="buy",
            quantity=Decimal("100"), price=Decimal("10"), fees=Decimal("0"),
            currency="EUR",
        ),
    ])
    db.commit()
    db.close()


def test_positions_empty_portfolio_validates_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["items"] == []
    assert payload["page_info"]["total_items"] == 0


def test_positions_full_wire_with_real_service(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _seed(tenant)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["page_info"]["total_items"] == 3
    items = {item["ticker"]: item for item in payload["items"]}
    for item in items.values():
        PortfolioPositionItemOut.model_validate(item)

    valued = items["VAL"]
    assert valued["name"] == "Valued Co"  # clave sin tipo en el front
    assert valued["sector"] == "Tech"     # clave sin tipo en el front
    assert valued["source"] == "manual"   # clave sin tipo en el front
    assert valued["market_price"] == 10.0
    assert valued["unrealized_pnl"] == 200.0
    assert valued["cost_basis"] == 800.0
    assert valued["market_value_native"] == 1000.0
    assert valued["quote_missing"] is False
    assert valued["valuation_hold"] is None
    assert valued["cost_reconciliation"] is None
    assert valued["fiscal_bucket"] is None  # sin compras registradas

    held = items["HELD"]
    assert held["market_price"] is None
    assert held["market_value"] is None
    # market_value_native: null en suspenso (el front lo tipaba como number).
    assert held["market_value_native"] is None
    assert held["unrealized_pnl"] is None
    assert held["valuation_hold"] == {
        "reason": "split_pending",
        "effective_date": "2026-10-01",
        "since": "2026-09-15",
    }

    ledger = items["LED"]
    # Precio del ledger sin cotizacion: plusvalias null, nunca un 0 medido.
    assert ledger["quote_missing"] is True
    assert ledger["unrealized_pnl"] is None
    assert ledger["unrealized_pnl_base"] is None
    assert ledger["pnl_price_effect_base"] is None
    assert ledger["first_buy_date"] == "2026-01-15"
    assert ledger["holding_days"] is not None
    assert ledger["fiscal_bucket"] in ("corto_plazo", "largo_plazo")
