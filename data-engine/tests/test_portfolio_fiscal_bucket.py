"""Fiscalidad por posición: resultado latente y bucket corto/largo plazo.

Run from data-engine/:
    pytest tests/test_portfolio_fiscal_bucket.py -v
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import portfolio as portfolio_route
from app.core.database import Base
from app.models import Company, Portfolio, Position, Tenant, Transaction


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="fiscal-bucket-test", name="Fiscal bucket test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    portfolio = Portfolio(
        tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True
    )
    db.add(portfolio)
    db.flush()
    return db


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="X",
        currency="EUR",
        sector="S",
        industry="I",
        company_type="imported_holding",
        valuation_model="unassigned",
    )
    db.add(company)
    db.flush()
    return company


# Antigüedad de posiciones abiertas: hasta HOY (Nico, 29 oct 2026), no hasta el
# as_of del último precio. "Hoy" fijo para que los tests sean deterministas.
TODAY = date(2026, 10, 29)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(portfolio_route, "local_today", lambda: TODAY)


def _position(db: Session, company: Company, as_of: date, quantity: str = "10") -> None:
    db.add(
        Position(
            company_id=company.id,
            portfolio_id=1,
            quantity=Decimal(quantity),
            average_cost=Decimal("100"),
            market_price=Decimal("150"),
            market_value=Decimal("1500"),
            unrealized_pnl=Decimal("500"),
            realized_pnl=Decimal("0"),
            currency="EUR",
            base_currency="EUR",
            market_value_base=Decimal("1500"),
            cost_basis_base=Decimal("1000"),
            unrealized_pnl_base=Decimal("500"),
            source="test",
            as_of=as_of,
        )
    )
    db.flush()


def test_long_term_bucket_after_one_year():
    db = _session()
    try:
        company = _company(db, "LONG")
        db.add(
            Transaction(
                portfolio_id=1,
                company_id=company.id,
                trade_date=date(2024, 1, 10),
                action="buy",
                quantity=Decimal("10"),
                price=Decimal("100"),
                fees=Decimal("0"),
                currency="EUR",
            )
        )
        _position(db, company, date(2026, 9, 21))
        rows = portfolio_route.positions(db=db)["items"]  # sobre paginado {items, page_info}
    finally:
        db.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "LONG"
    # Resultado latente visible en nativa y base.
    assert row["unrealized_pnl_native"] == 500.0
    assert row["unrealized_pnl_base"] == 500.0
    assert row["first_buy_date"] == "2024-01-10"
    assert row["holding_days"] == (TODAY - date(2024, 1, 10)).days
    assert row["fiscal_bucket"] == "largo_plazo"


def test_short_term_bucket_within_one_year():
    db = _session()
    try:
        company = _company(db, "SHORT")
        db.add(
            Transaction(
                portfolio_id=1,
                company_id=company.id,
                trade_date=date(2026, 6, 1),
                action="buy",
                quantity=Decimal("10"),
                price=Decimal("100"),
                fees=Decimal("0"),
                currency="EUR",
            )
        )
        _position(db, company, date(2026, 9, 21))
        rows = portfolio_route.positions(db=db)["items"]  # sobre paginado {items, page_info}
    finally:
        db.close()
    assert rows[0]["fiscal_bucket"] == "corto_plazo"
    assert rows[0]["holding_days"] == (TODAY - date(2026, 6, 1)).days


def test_no_bucket_without_buy_history():
    db = _session()
    try:
        company = _company(db, "NOHIST")
        _position(db, company, date(2026, 9, 21))
        rows = portfolio_route.positions(db=db)["items"]  # sobre paginado {items, page_info}
    finally:
        db.close()
    assert rows[0]["fiscal_bucket"] is None
    assert rows[0]["holding_days"] is None
    assert rows[0]["first_buy_date"] is None
    # El resultado latente se sigue mostrando aunque no haya historial.
    assert rows[0]["unrealized_pnl_base"] == 500.0


def _tx(db, company, trade_date, action):
    db.add(
        Transaction(
            portfolio_id=1,
            company_id=company.id,
            trade_date=trade_date,
            action=action,
            quantity=Decimal("10"),
            price=Decimal("100"),
            fees=Decimal("0"),
            currency="EUR",
        )
    )


def test_open_position_counts_to_today_even_with_stale_price():
    """Sin precio reciente as_of = fecha de compra: antes salía «Corto plazo · 0d»."""
    db = _session()
    try:
        company = _company(db, "STALE")
        _tx(db, company, date(2024, 10, 20), "buy")
        _position(db, company, date(2024, 10, 20))
        rows = portfolio_route.positions(db=db)["items"]  # sobre paginado {items, page_info}
    finally:
        db.close()
    assert rows[0]["holding_days"] == (TODAY - date(2024, 10, 20)).days
    assert rows[0]["holding_days"] > 365
    assert rows[0]["fiscal_bucket"] == "largo_plazo"


def test_closed_position_counts_to_close_date():
    db = _session()
    try:
        company = _company(db, "CLOSED")
        _tx(db, company, date(2025, 1, 10), "buy")
        _tx(db, company, date(2025, 6, 10), "sell")
        _position(db, company, date(2025, 6, 10), quantity="0")
        rows = portfolio_route.positions(db=db)["items"]  # sobre paginado {items, page_info}
    finally:
        db.close()
    assert rows[0]["holding_days"] == (date(2025, 6, 10) - date(2025, 1, 10)).days
    assert rows[0]["fiscal_bucket"] == "corto_plazo"
