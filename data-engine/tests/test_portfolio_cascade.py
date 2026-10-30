"""Foreign key cascade tests.

Fulfills: VAL-SEC-007 (Foreign key cascades prevent orphaned records)
Fulfills: VAL-DB-001 (Foreign key constraints)
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import (
    Base,
    Company,
    InvestmentPlan,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    TaxReport,
    Transaction,
)


@pytest.fixture
def db():
    """Isolated in-memory test database."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "cascade-test-tenant"
        yield session


def test_cascade_delete_portfolio(db: Session):
    """Deleting a portfolio cascades to holdings, transactions, snapshots, and plans."""
    tenant_id = "cascade-test-tenant"

    # Setup company
    company = Company(
        ticker="TEST",
        name="Test Company",
        exchange="NASDAQ",
        currency="USD",
        company_type="research_candidate",
        valuation_model="unassigned",
    )
    db.add(company)
    db.flush()

    # Create portfolio
    portfolio = Portfolio(
        tenant_id=tenant_id,
        name="Retirement",
        base_currency="EUR",
    )
    db.add(portfolio)
    db.flush()
    portfolio_id = portfolio.id

    # Create associated holdings (Position)
    position = Position(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        company_id=company.id,
        quantity=Decimal("50"),
        market_price=Decimal("150.00"),
        market_value=Decimal("7500.00"),
        currency="USD",
    )
    db.add(position)

    # Create associated Transaction
    tx = Transaction(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        company_id=company.id,
        trade_date=date(2025, 1, 15),
        action="buy",
        quantity=Decimal("50"),
        price=Decimal("150.00"),
        currency="USD",
    )
    db.add(tx)

    # Create associated Snapshot
    snapshot = PortfolioDailySnapshot(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        snapshot_date=date(2025, 1, 15),
        base_currency="EUR",
        positions_value_base=Decimal("7000.00"),
        cash_value_base=Decimal("500.00"),
        total_value_base=Decimal("7500.00"),
    )
    db.add(snapshot)

    # Create associated TaxReport
    tax = TaxReport(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        fiscal_year=2025,
        base_currency="EUR",
    )
    db.add(tax)

    # Create associated InvestmentPlan
    plan = InvestmentPlan(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        start_date=date(2025, 1, 1),
        monthly_contribution=Decimal("500.00"),
    )
    db.add(plan)
    db.commit()

    # Verify everything exists
    assert db.scalar(select(Portfolio).where(Portfolio.id == portfolio_id)) is not None
    assert db.scalar(select(Position).where(Position.portfolio_id == portfolio_id)) is not None
    assert db.scalar(select(Transaction).where(Transaction.portfolio_id == portfolio_id)) is not None
    assert db.scalar(select(PortfolioDailySnapshot).where(PortfolioDailySnapshot.portfolio_id == portfolio_id)) is not None
    assert db.scalar(select(TaxReport).where(TaxReport.portfolio_id == portfolio_id)) is not None
    assert db.scalar(select(InvestmentPlan).where(InvestmentPlan.portfolio_id == portfolio_id)) is not None

    # Delete portfolio
    portfolio_to_delete = db.get(Portfolio, portfolio_id)
    assert portfolio_to_delete is not None
    db.delete(portfolio_to_delete)
    db.commit()

    # Verify cascade deletion: all associated records are cleaned up, zero orphaned rows
    assert db.scalar(select(Portfolio).where(Portfolio.id == portfolio_id)) is None
    assert db.scalar(select(Position).where(Position.portfolio_id == portfolio_id)) is None
    assert db.scalar(select(Transaction).where(Transaction.portfolio_id == portfolio_id)) is None
    assert db.scalar(select(PortfolioDailySnapshot).where(PortfolioDailySnapshot.portfolio_id == portfolio_id)) is None
    assert db.scalar(select(TaxReport).where(TaxReport.portfolio_id == portfolio_id)) is None
    assert db.scalar(select(InvestmentPlan).where(InvestmentPlan.portfolio_id == portfolio_id)) is None

    # Company is independent and was NOT deleted
    assert db.scalar(select(Company).where(Company.id == company.id)) is not None
