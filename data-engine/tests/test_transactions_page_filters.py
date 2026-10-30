"""Movimientos filtrados por ticker y tipo: el total y la paginación respetan el filtro."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.portfolio import transactions_page
from app.core.database import Base
from app.models import Company, Tenant, Transaction


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="filters", name="Filters")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        companies = {}
        for ticker in ("AAPL", "SAN.MC"):
            companies[ticker] = Company(ticker=ticker, name=ticker, exchange="TEST", company_type="operating", valuation_model="dcf")
            session.add(companies[ticker])
        session.flush()
        for i in range(60):
            session.add(Transaction(company_id=companies["AAPL"].id, action="buy", quantity=Decimal(1), price=Decimal(10),
                                    currency="USD", trade_date=date(2025, 1, 1)))
        session.add(Transaction(company_id=companies["AAPL"].id, action="sell", quantity=Decimal(5), price=Decimal(12),
                                currency="USD", trade_date=date(2025, 2, 1)))
        for i in range(3):
            session.add(Transaction(company_id=companies["SAN.MC"].id, action="buy", quantity=Decimal(10), price=Decimal(4),
                                    currency="EUR", trade_date=date(2025, 3, 1)))
        session.add(Transaction(company_id=companies["SAN.MC"].id, action="dividend", quantity=Decimal(0), price=Decimal(1),
                                currency="EUR", trade_date=date(2025, 4, 1)))
        session.commit()
        yield session
    engine.dispose()


def test_ticker_filter_counts_and_pages_only_that_ticker(db):
    page = transactions_page(limit=50, offset=0, ticker="san.mc", db=db)
    assert page["total"] == 3
    assert {item["ticker"] for item in page["items"]} == {"SAN.MC"}


def test_action_filter_and_combination(db):
    sells = transactions_page(limit=50, offset=0, action="sell", db=db)
    assert sells["total"] == 1
    assert sells["items"][0]["action"] == "sell"
    aapl_buys = transactions_page(limit=50, offset=50, ticker="AAPL", action="buy", db=db)
    assert aapl_buys["total"] == 60
    assert len(aapl_buys["items"]) == 10


def test_without_filters_unchanged_and_no_dividends(db):
    page = transactions_page(limit=50, offset=0, db=db)
    assert page["total"] == 64
    assert transactions_page(limit=50, offset=0, ticker="  ", db=db)["total"] == 64
