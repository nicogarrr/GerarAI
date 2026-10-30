from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, MarketPrice, NewsEvent, Portfolio, Position, Tenant
from app.services.portfolio_moves_service import build_digest, latest_digest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def test_tenant_digest_missing_and_news_are_not_causal(db):
    first = Tenant(external_id="tenant-first", name="First", metadata_={}, status="active")
    second = Tenant(external_id="tenant-second", name="Second", metadata_={}, status="active")
    db.add_all((first, second))
    db.flush()
    company = Company(ticker="TEST", name="Test", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    portfolio = Portfolio(tenant_id=first.id, name="A")
    db.add(portfolio)
    db.flush()
    db.add(Position(tenant_id=first.id, portfolio_id=portfolio.id, company_id=company.id,
                    quantity=Decimal("2"), average_cost=Decimal("10")))
    db.add_all((MarketPrice(company_id=company.id, date=date(2026, 9, 23), close=Decimal("10"), adj_close=Decimal("10"), source="yfinance"),
                MarketPrice(company_id=company.id, date=date(2026, 9, 24), close=Decimal("11"), adj_close=Decimal("11"), source="yfinance")))
    db.add(NewsEvent(tenant_id=first.id, company_id=company.id, date=datetime(2026, 9, 24, 8, tzinfo=UTC),
                     title="Related article", source="example.com", url="https://example.com/a", metadata_={"connector": "gdelt"}))
    db.add(NewsEvent(tenant_id=second.id, company_id=company.id, date=datetime(2026, 9, 24, 8, tzinfo=UTC),
                     title="Private other tenant", source="example.com", url="https://example.com/b"))
    for hour in range(9, 15):
        db.add(NewsEvent(tenant_id=first.id, company_id=company.id,
                         date=datetime(2026, 9, 24, hour, tzinfo=UTC),
                         title=f"Newer RSS {hour}", source="rss.example", url=f"https://rss.example/{hour}",
                         metadata_={"connector": "rss"}))
    db.commit()
    db.info["tenant_id"] = first.id
    digest = build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC))
    assert digest.items[0]["price_change_pct"] == 10
    assert digest.items[0]["adjusted_close"] == "11.000000"
    assert digest.items[0]["previous_adjusted_close"] == "10.000000"
    assert "close" not in digest.items[0]
    assert digest.items[0]["catalyst"] == "sin catalizador identificado"
    assert [row["url"] for row in digest.items[0]["related_news"]] == ["https://example.com/a"]
    response = latest_digest(db)
    assert response["positions_sampled_at"] == digest.generated_at.isoformat()
    assert "posiciones actuales" in response["universe"]
    assert build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC)).id == digest.id
    db.info["tenant_id"] = second.id
    assert latest_digest(db)["status"] == "sin datos"


def test_missing_close_and_intraday_guard(db):
    db.info["tenant_id"] = 999
    with pytest.raises(ValueError):
        build_digest(db, date(2026, 9, 25), datetime(2026, 9, 25, 12, tzinfo=UTC))
    assert build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC)).coverage == "sin posiciones"


def test_sql_filter_before_limit_keeps_gdelt(db):
    """5 noticias RSS/manual mas recientes no ocultan la GDELT del dia:
    el filtro connector va en SQL antes del ORDER BY/LIMIT."""
    tenant = Tenant(external_id="tenant-sql", name="SQL", metadata_={}, status="active")
    db.add(tenant)
    db.flush()
    company = Company(ticker="SQLF", name="SqlFilter", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    portfolio = Portfolio(tenant_id=tenant.id, name="A")
    db.add(portfolio)
    db.flush()
    db.add(Position(tenant_id=tenant.id, portfolio_id=portfolio.id, company_id=company.id,
                    quantity=Decimal("2"), average_cost=Decimal("10")))
    db.add_all((MarketPrice(company_id=company.id, date=date(2026, 9, 23), close=Decimal("10"), adj_close=Decimal("10"), source="yfinance"),
                MarketPrice(company_id=company.id, date=date(2026, 9, 24), close=Decimal("11"), adj_close=Decimal("11"), source="yfinance")))
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id, date=datetime(2026, 9, 24, 8, tzinfo=UTC),
                     title="GDELT article", source="example.com", url="https://example.com/gdelt",
                     metadata_={"connector": "gdelt"}))
    for hour in range(9, 14):
        db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id, date=datetime(2026, 9, 24, hour, tzinfo=UTC),
                         title=f"RSS {hour}", source="rss", url=f"https://example.com/rss{hour}"))
    db.commit()
    db.info["tenant_id"] = tenant.id
    digest = build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC))
    assert [row["url"] for row in digest.items[0]["related_news"]] == ["https://example.com/gdelt"]
def test_spot_is_not_treated_as_completed_daily_bar(db):
    tenant = Tenant(external_id="spot-tenant", name="Spot", metadata_={}, status="active")
    db.add(tenant)
    db.flush()
    company = Company(ticker="SPOT", name="Spot", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    db.add(Position(tenant_id=tenant.id, company_id=company.id, quantity=Decimal("1")))
    db.add_all((MarketPrice(company_id=company.id, date=date(2026, 9, 23), close=Decimal("10"),
                            adj_close=None, source="FMP"),
                MarketPrice(company_id=company.id, date=date(2026, 9, 24), close=Decimal("11"),
                            adj_close=None, source="yahoo_finance_intraday")))
    db.commit()
    db.info["tenant_id"] = tenant.id
    digest = build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC))
    assert digest.items[0]["status"] == "sin datos"
    assert digest.items[0]["related_news"] == []


def test_split_does_not_become_false_price_move(db):
    tenant = Tenant(external_id="split-tenant", name="Split", metadata_={}, status="active")
    db.add(tenant)
    db.flush()
    company = Company(ticker="SPLT", name="Split", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    db.add(Position(tenant_id=tenant.id, company_id=company.id, quantity=Decimal("2")))
    db.add_all((MarketPrice(company_id=company.id, date=date(2026, 9, 23),
                            close=Decimal("200"), adj_close=Decimal("100"), source="yfinance"),
                MarketPrice(company_id=company.id, date=date(2026, 9, 24),
                            close=Decimal("110"), adj_close=Decimal("110"), source="yfinance")))
    db.commit()
    db.info["tenant_id"] = tenant.id
    item = build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC)).items[0]
    assert item["price_change_pct"] == 10  # raw closes would falsely show -45%.
    assert item["adjusted_close"] == "110.000000"
    assert item["previous_adjusted_close"] == "100.000000"
    assert "close" not in item and "previous_close" not in item


def test_missing_session_is_not_presented_as_the_day_move(db):
    # Falta el martes 22-sep: lunes 10 -> miercoles 11 (+10 % en dos sesiones)
    # no es la variacion del miercoles.
    tenant = Tenant(external_id="tenant-gap", name="Gap", metadata_={}, status="active")
    db.add(tenant)
    db.flush()
    company = Company(ticker="GAP", name="Gap", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    portfolio = Portfolio(tenant_id=tenant.id, name="A")
    db.add(portfolio)
    db.flush()
    db.add(Position(tenant_id=tenant.id, portfolio_id=portfolio.id, company_id=company.id,
                    quantity=Decimal("1"), average_cost=Decimal("10")))
    db.add_all((MarketPrice(company_id=company.id, date=date(2026, 9, 21), close=Decimal("10"), adj_close=Decimal("10"), source="yfinance"),
                MarketPrice(company_id=company.id, date=date(2026, 9, 23), close=Decimal("11"), adj_close=Decimal("11"), source="yfinance")))
    db.commit()
    db.info["tenant_id"] = tenant.id
    item = build_digest(db, date(2026, 9, 23), datetime(2026, 9, 24, tzinfo=UTC)).items[0]
    assert item["status"] == "hueco de sesión"
    assert "price_change_pct" not in item
    assert item["missing_sessions"] == ["2026-09-22"]
