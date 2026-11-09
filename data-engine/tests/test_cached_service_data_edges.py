"""Cached service data paths with real SQLite rows, cache intentionally bypassed."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice, Portfolio, Position
from app.models.entities import Base
from app.services import cached_market_data as market
from app.services import cached_portfolio_valuation as portfolio
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.risk_service import RiskService


@pytest.fixture
def rows():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.info["tenant_id"] = "cache-edges"
            company = Company(
                ticker="CACHE",
                name="Cache Test",
                exchange="X",
                currency="EUR",
                company_type="holding",
                valuation_model="unassigned",
            )
            fund = Portfolio(name="Main", base_currency="EUR", tenant_id="cache-edges")
            db.add_all([company, fund])
            db.commit()
            yield db, company, fund
    finally:
        engine.dispose()


def test_market_absence_empty_batch_and_quote_payload(rows, monkeypatch):
    db, company, _ = rows
    service = market.CachedMarketDataService()
    assert service.get_latest_price.__wrapped__(service, db, company.id) is None
    assert service.get_prices_batch.__wrapped__(service, db, ()) == {}
    assert service.get_quote.__wrapped__(service, db, "UNKNOWN") is None
    calls = []

    def latest(db_arg, company_id):
        assert db_arg is db and company_id == company.id
        calls.append(company_id)
        return (
            None
            if len(calls) == 1
            else {"price": 12.5, "currency": "EUR", "as_of": "2026-01-01", "source": "fixture"}
        )

    monkeypatch.setattr(service, "get_latest_price", latest)
    assert service.get_quote.__wrapped__(service, db, "CACHE") is None
    assert service.get_quote.__wrapped__(service, db, "CACHE") == {
        "symbol": "CACHE",
        "company_id": company.id,
        "name": "Cache Test",
        "price": 12.5,
        "currency": "EUR",
        "as_of": "2026-01-01",
        "source": "fixture",
    }
    invalidated = []
    monkeypatch.setattr(market, "invalidate_market_data_cache", lambda: invalidated.append(True))
    service.invalidate_cache()
    assert invalidated == [True]


def test_price_history_cutoff_and_latest_batch_are_database_driven(rows):
    db, company, _ = rows
    today = date.today()
    for age, price in [(31, 5), (30, 7), (1, 9), (0, 11)]:
        db.add(
            MarketPrice(
                company_id=company.id,
                date=today - timedelta(days=age),
                close=price,
                quote_currency="EUR",
                source="fixture",
            )
        )
    db.commit()
    service = market.CachedMarketDataService()
    history = service.get_price_history.__wrapped__(service, db, company.id, days=30)
    assert [row["price"] for row in history] == [11.0, 9.0, 7.0]
    assert history[-1]["as_of"] == (today - timedelta(days=30)).isoformat()
    assert all(row["currency"] == "EUR" and row["source"] == "fixture" for row in history)
    batch = service.get_prices_batch.__wrapped__(service, db, (company.id, 999999))
    assert set(batch) == {company.id}
    assert batch[company.id]["price"] == 11 and batch[company.id]["as_of"] == today.isoformat()


def test_portfolio_summary_performance_and_invalidation_delegation(rows, monkeypatch):
    db, company, fund = rows
    monkeypatch.setattr(PortfolioFXService, "ensure_portfolio", lambda self, session: fund)
    db.add(
        Position(
            company_id=company.id,
            portfolio_id=fund.id,
            quantity=Decimal("2.5"),
            market_price=Decimal("12"),
            currency="EUR",
            tenant_id="cache-edges",
        )
    )
    db.commit()
    service = portfolio.CachedPortfolioValuationService()
    summary = service.get_positions_summary.__wrapped__(service, db)
    assert summary == {
        "portfolio_id": fund.id,
        "positions_count": 1,
        "total_value": 30.0,
        "currencies": ["EUR"],
    }
    snapshot = service.get_portfolio_snapshot.__wrapped__(service, db, as_of=date(2026, 1, 1))
    assert snapshot["snapshot_date"] == "2026-01-01" and snapshot["total_value"] == 30
    assert snapshot["positions"][0]["symbol"] == "CACHE" and snapshot["positions"][0]["quantity"] == 2.5
    seen = []
    monkeypatch.setattr(service, "get_portfolio_snapshot", lambda session: seen.append(session) or snapshot)
    assert service.get_portfolio_performance.__wrapped__(service, db, days=17) == {
        "current_value": 30.0,
        "positions_count": 1,
        "period_days": 17,
        "base_currency": "EUR",
    }
    assert seen == [db]
    monkeypatch.setattr(portfolio, "invalidate_portfolio_cache", lambda **kwargs: seen.append(kwargs))
    service.invalidate_cache(db)
    assert seen[-1] == {"db": db}
    sentinel = {"risk": "fixture"}
    monkeypatch.setattr(RiskService, "dashboard", lambda self, session: sentinel if session is db else None)
    assert portfolio.risk_dashboard.__wrapped__(db) is sentinel


def test_tenant_extractor_uses_explicit_session_tenant(rows):
    db, _, _ = rows
    assert portfolio._extract_tenant_from_db((object(), db), {}) == "cache-edges"


def test_dca_data_paths_keep_watchlist_and_portfolio_separate(rows, monkeypatch):
    from app.models import DcaSignalState, WatchItem
    from app.services.cached_dca_schedule import CachedDcaScheduleService

    db, company, fund = rows
    monkeypatch.setattr(PortfolioFXService, "ensure_portfolio", lambda self, session: fund)
    service = CachedDcaScheduleService()
    assert service.get_watchlist_dca_signals.__wrapped__(service, db) == []
    assert service.get_portfolio_dca_signals.__wrapped__(service, db) == []
    assert service.get_dca_signal.__wrapped__(service, db, "MISSING") is None
    db.add(WatchItem(symbol="CACHE", tenant_id="cache-edges"))
    db.add(
        Position(
            company_id=company.id,
            portfolio_id=fund.id,
            quantity=1,
            market_price=12,
            currency="EUR",
            tenant_id="cache-edges",
        )
    )
    db.add(
        DcaSignalState(
            symbol="CACHE",
            company_id=company.id,
            tenant_id="cache-edges",
            level=2,
            status="active",
            period="2026-01",
            signal_date=date(2026, 1, 1),
            close=12,
            level_prices={"2": "10.5"},
            params_version="test",
            data_source="fixture",
        )
    )
    db.commit()
    expected = {
        "symbol": "CACHE",
        "current_level": 2,
        "verdict_month": "2026-01",
        "current_price": 12.0,
        "level_price": 10.5,
    }
    assert service.get_watchlist_dca_signals.__wrapped__(service, db) == [expected]
    assert service.get_portfolio_dca_signals.__wrapped__(service, db) == [
        {k: v for k, v in expected.items() if k != "verdict_month"}
    ]
    assert service.get_dca_signal.__wrapped__(service, db, "CACHE")["level_price"] == 10.5
    seen = []
    from app.services import cached_dca_schedule as dca

    monkeypatch.setattr(dca, "invalidate_dca_cache", lambda **kwargs: seen.append(kwargs))
    service.invalidate_cache(db)
    assert seen == [{"db": db}]
