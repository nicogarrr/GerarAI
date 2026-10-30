"""Export: las filas de posicion no mezclan divisas ni inventan plusvalias."""

import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import export as route
from app.core.database import Base, get_db
from app.models import Company, Position, Transaction
from app.services.portfolio_fx_service import PortfolioFXService


def _export(monkeypatch, seed_fn, fmt="csv"):
    monkeypatch.setattr(route.TaxReportService, "compute_report", lambda *a: {})
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        seed.info["tenant_id"] = 1
        portfolio = PortfolioFXService().ensure_portfolio(seed)
        seed_fn(seed, portfolio)
        seed.commit()
    app = FastAPI()
    app.include_router(route.router, prefix="/api/export")

    def isolated_db():
        with Session(engine) as db:
            db.info["tenant_id"] = 1
            yield db

    app.dependency_overrides[get_db] = isolated_db
    response = TestClient(app).get(f"/api/export/2026?format={fmt}")
    engine.dispose()
    assert response.status_code == 200
    return response


def _usd_position(seed, portfolio, *, source="manual", price=Decimal("150")):
    company = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="dcf")
    seed.add(company)
    seed.flush()
    # 10 acciones a 100 USD compradas con EURUSD 1,25 (0,80 EUR/USD) -> coste 800 EUR;
    # hoy 150 USD con 0,90 EUR/USD -> 1.350 EUR. Nativo: 1.500 USD, +500 USD.
    seed.add(Position(
        company_id=company.id, portfolio_id=portfolio.id, quantity=Decimal("10"),
        average_cost=Decimal("100"), market_price=price, market_value=10 * price,
        unrealized_pnl=10 * price - Decimal("1000"), realized_pnl=Decimal("0"),
        currency="USD", base_currency="EUR", market_value_native=10 * price,
        cost_basis_native=Decimal("1000"), market_value_base=10 * price * Decimal("0.9"),
        cost_basis_base=Decimal("800"),
        unrealized_pnl_base=10 * price * Decimal("0.9") - Decimal("800"),
        fx_rate=Decimal("0.9"), source=source, as_of=date(2026, 10, 29),
    ))
    return company


def _position_row(response):
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))
    return next(row for row in rows if row[0] == "position")


def test_csv_position_amounts_are_in_the_currency_printed_beside_them(monkeypatch):
    row = _position_row(_export(monkeypatch, lambda s, p: _usd_position(s, p)))
    # type, date, ticker, quantity, average_cost, market_value, currency, unrealized
    assert row[2:] == ["MSFT", "10.0", "100.0", "1500.0", "USD", "500.0"]


def test_json_position_carries_native_and_base_amounts_labelled(monkeypatch):
    data = _export(monkeypatch, lambda s, p: _usd_position(s, p), fmt="json").json()
    position = data["positions"][0]
    assert position["currency"] == "USD" and position["base_currency"] == "EUR"
    assert position["market_value_native"] == 1500.0
    assert position["unrealized_pnl_native"] == 500.0
    assert position["market_value_base"] == 1350.0
    assert position["unrealized_pnl_base"] == 550.0


def test_position_without_a_real_quote_exports_unknown_gain_not_zero(monkeypatch):
    def seed(s, p):
        company = _usd_position(s, p, source="postgres_ledger", price=Decimal("100"))
        s.add(Transaction(
            portfolio_id=p.id, company_id=company.id, trade_date=date(2026, 10, 1),
            action="buy", quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"),
            currency="USD", external_id="t-1", raw_payload={},
        ))

    response = _export(monkeypatch, seed)
    row = _position_row(response)
    assert row[7] == ""  # plusvalia desconocida, nunca 0.0
    data = _export(monkeypatch, seed, fmt="json").json()["positions"][0]
    assert data["quote_missing"] is True
    assert data["unrealized_pnl_native"] is None and data["unrealized_pnl_base"] is None
