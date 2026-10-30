"""Tests for pagination functionality across list endpoints.

Run from data-engine/:
    pytest tests/test_pagination.py -v
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import portfolio as portfolio_routes
from app.api.routes import search as search_routes
from app.core.database import Base, get_db
from app.models import FXRate, Portfolio, PortfolioDailySnapshot
from app.services.portfolio_ledger_service import PortfolioLedgerService


@pytest.fixture()
def env():
    """Set up in-memory database with test data."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    
    with factory() as s:
        s.info["tenant_id"] = "pagination-test"
        
        portfolio = Portfolio(
            name="Test Portfolio",
            base_currency="EUR",
            is_default=True,
        )
        s.add(portfolio)
        s.commit()
        portfolio_id = portfolio.id
        
        # Use service to create transactions, which creates companies and positions
        service = PortfolioLedgerService()
        tickers = [f"TST{i:02d}" for i in range(25)]
        
        for i, ticker in enumerate(tickers):
            service.create_transaction(
                s,
                ticker=ticker,
                action="buy",
                quantity=Decimal(100 + i * 10),
                price=Decimal(50.0 + i),
                trade_date=date.today() - timedelta(days=60 + i),
                currency="USD",
            )
        
        # Create additional transactions for testing
        for i in range(5):
            service.create_transaction(
                s,
                ticker=tickers[i],
                action="sell",
                quantity=Decimal(10),
                price=Decimal(55.0 + i),
                trade_date=date.today() - timedelta(days=10 + i),
                currency="USD",
            )
        
        # Create FX rates
        for i in range(15):
            fx_rate = FXRate(
                base_currency="EUR",
                quote_currency=f"CUR{i:02d}",
                rate=Decimal(str(1.1 + i * 0.01)),
                rate_date=date.today() - timedelta(days=i),
                source="manual",
            )
            s.add(fx_rate)
        
        # Create snapshots
        for i in range(40):
            snapshot = PortfolioDailySnapshot(
                portfolio_id=portfolio_id,
                snapshot_date=date.today() - timedelta(days=i),
                base_currency="EUR",
                positions_value_base=Decimal(10000 + i * 100),
                cash_value_base=Decimal(5000),
                total_value_base=Decimal(15000 + i * 100),
                net_external_flow_base=Decimal(0),
                daily_return=Decimal(0.01 if i % 2 == 0 else -0.005),
                cumulative_twr=Decimal(0.1 + i * 0.001),
                pricing_coverage=Decimal(1.0),
                source="manual",
            )
            s.add(snapshot)
        
        s.commit()
    
    def override_db():
        with factory() as session:
            session.info["tenant_id"] = "pagination-test"
            session.info["user_id"] = "test-user"
            yield session
    
    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")
    app.include_router(search_routes.router, prefix="/search")
    app.dependency_overrides[get_db] = override_db
    
    return TestClient(app)


def test_positions_pagination(env):
    """Test /positions endpoint returns paginated response."""
    # First page
    resp = env.get("/portfolio/positions?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    
    assert "items" in data
    assert "page_info" in data
    assert len(data["items"]) == 10
    
    page_info = data["page_info"]
    assert page_info["page"] == 1
    assert page_info["page_size"] == 10
    assert page_info["total_items"] == 25
    assert page_info["total_pages"] == 3
    assert page_info["has_next"] is True
    assert page_info["has_prev"] is False
    
    # Second page
    resp = env.get("/portfolio/positions?page=2&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 10
    assert data["page_info"]["page"] == 2
    assert data["page_info"]["has_next"] is True
    assert data["page_info"]["has_prev"] is True
    
    # Last page
    resp = env.get("/portfolio/positions?page=3&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 5
    assert data["page_info"]["page"] == 3
    assert data["page_info"]["has_next"] is False
    assert data["page_info"]["has_prev"] is True


def test_transactions_pagination(env):
    """Test /transactions endpoint returns paginated response."""
    resp = env.get("/portfolio/transactions?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    
    assert "items" in data
    assert "page_info" in data
    assert len(data["items"]) == 10
    
    page_info = data["page_info"]
    assert page_info["page"] == 1
    assert page_info["page_size"] == 10
    assert page_info["total_items"] == 30
    assert page_info["total_pages"] == 3
    assert page_info["has_next"] is True
    assert page_info["has_prev"] is False
    
    # Test with filters
    resp = env.get("/portfolio/transactions?page=1&page_size=10&action=buy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page_info"]["total_items"] == 25  # 25 buys


def test_fx_rates_pagination(env):
    """Test /fx-rates endpoint returns paginated response."""
    resp = env.get("/portfolio/fx-rates?page=1&page_size=5")
    assert resp.status_code == 200
    data = resp.json()
    
    assert "items" in data
    assert "page_info" in data
    assert len(data["items"]) == 5
    
    page_info = data["page_info"]
    assert page_info["page"] == 1
    assert page_info["page_size"] == 5
    assert page_info["total_items"] == 15
    assert page_info["total_pages"] == 3


def test_snapshots_pagination(env):
    """Test /snapshots endpoint returns paginated response."""
    resp = env.get("/portfolio/snapshots?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    
    assert "items" in data
    assert "page_info" in data
    assert len(data["items"]) == 10
    
    page_info = data["page_info"]
    assert page_info["page"] == 1
    assert page_info["page_size"] == 10
    assert page_info["total_items"] == 40
    assert page_info["total_pages"] == 4
    assert page_info["has_next"] is True


def test_pagination_default_values(env):
    """Test that default page=1 and page_size=20 work correctly."""
    # Without explicit pagination params
    resp = env.get("/portfolio/positions")
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["page_info"]["page"] == 1
    assert data["page_info"]["page_size"] == 20
    assert len(data["items"]) == 20  # 25 total, so first 20


def test_pagination_validates_parameters(env):
    """Test that invalid pagination parameters are rejected."""
    # Invalid page (less than 1)
    resp = env.get("/portfolio/positions?page=0&page_size=10")
    assert resp.status_code == 422
    
    # Invalid page_size (less than 1)
    resp = env.get("/portfolio/positions?page=1&page_size=0")
    assert resp.status_code == 422
