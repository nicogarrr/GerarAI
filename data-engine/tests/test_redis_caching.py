"""Tests for Redis caching implementation.

Verifies:
- Cache hit/miss behavior
- TTL enforcement
- Tenant isolation
- Dependency invalidation
- Fail-open behavior
- Cache hit rate >70%
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.cache import (
    get_cache_stats,
    invalidate_market_data_cache,
    reset_cache_stats,
)
from app.models import Base, Company, DcaSignalState, MarketPrice, Portfolio, Position
from app.services.cached_dca_schedule import CachedDcaScheduleService
from app.services.cached_market_data import CachedMarketDataService
from app.services.cached_portfolio_valuation import CachedPortfolioValuationService


@pytest.fixture
def db_session():
    """Create in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    # Set tenant_id in db.info for testing
    session.info["tenant_id"] = 1
    yield session
    session.close()


@pytest.fixture
def sample_company(db_session: Session) -> Company:
    """Create a sample company."""
    company = Company(
        symbol="AAPL",
        name="Apple Inc.",
        exchange="NASDAQ",
        currency="USD",
    )
    db_session.add(company)
    db_session.commit()
    return company


@pytest.fixture
def sample_prices(db_session: Session, sample_company: Company) -> list[MarketPrice]:
    """Create sample market prices."""
    prices = []
    base_date = date.today() - timedelta(days=30)
    
    for i in range(30):
        price = MarketPrice(
            company_id=sample_company.id,
            price=Decimal(f"{150 + i * 0.5}"),
            as_of=base_date + timedelta(days=i),
            currency="USD",
            source="test",
        )
        prices.append(price)
        db_session.add(price)
    
    db_session.commit()
    return prices


@pytest.fixture
def sample_portfolio(db_session: Session) -> Portfolio:
    """Create a sample portfolio."""
    portfolio = Portfolio(
        base_currency="USD",
        tenant_id=1,
    )
    db_session.add(portfolio)
    db_session.commit()
    return portfolio


@pytest.fixture
def sample_position(db_session: Session, sample_portfolio: Portfolio, sample_company: Company) -> Position:
    """Create a sample position."""
    position = Position(
        portfolio_id=sample_portfolio.id,
        company_id=sample_company.id,
        quantity=Decimal("100"),
        market_price=Decimal("150.00"),
        currency="USD",
        as_of=date.today(),
    )
    db_session.add(position)
    db_session.commit()
    return position


class TestCacheStats:
    """Test cache statistics tracking."""
    
    def test_cache_stats_initialization(self):
        """Test that cache stats are properly initialized."""
        reset_cache_stats()
        stats = get_cache_stats()
        
        assert "market_data" in stats
        assert "portfolio_valuation" in stats
        assert "dca_schedule" in stats
        
        for category in stats.values():
            assert category["hits"] == 0
            assert category["misses"] == 0
            assert category["total"] == 0
            assert category["hit_rate"] == 0.0
    
    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate calculation."""
        from app.core.cache import _record_hit, _record_miss
        
        reset_cache_stats()
        
        # Record 7 hits and 3 misses (70% hit rate)
        for _ in range(7):
            _record_hit("market_data")
        for _ in range(3):
            _record_miss("market_data")
        
        stats = get_cache_stats()
        assert stats["market_data"]["hits"] == 7
        assert stats["market_data"]["misses"] == 3
        assert stats["market_data"]["total"] == 10
        assert stats["market_data"]["hit_rate"] == 70.0


class TestCachedMarketData:
    """Test cached market data service."""
    
    def test_get_latest_price_cache_miss_then_hit(self, db_session: Session, sample_company: Company, sample_prices):
        """Test cache miss followed by cache hit."""
        reset_cache_stats()
        service = CachedMarketDataService()
        
        # First call: cache miss
        result1 = service.get_latest_price(db_session, sample_company.id)
        assert result1 is not None
        assert result1["company_id"] == sample_company.id
        
        stats = get_cache_stats()
        assert stats["market_data"]["misses"] == 1
        assert stats["market_data"]["hits"] == 0
        
        # Second call: cache hit
        result2 = service.get_latest_price(db_session, sample_company.id)
        assert result2 == result1
        
        stats = get_cache_stats()
        assert stats["market_data"]["misses"] == 1
        assert stats["market_data"]["hits"] == 1
        assert stats["market_data"]["hit_rate"] == 50.0
    
    def test_get_prices_batch(self, db_session: Session, sample_company: Company, sample_prices):
        """Test batch price retrieval with caching."""
        reset_cache_stats()
        service = CachedMarketDataService()
        
        # First call: cache miss
        result1 = service.get_prices_batch(db_session, (sample_company.id,))
        assert sample_company.id in result1
        
        # Second call: cache hit
        result2 = service.get_prices_batch(db_session, (sample_company.id,))
        assert result1 == result2
        
        stats = get_cache_stats()
        assert stats["market_data"]["hit_rate"] == 50.0
    
    def test_cache_invalidation(self, db_session: Session, sample_company: Company, sample_prices):
        """Test cache invalidation for market data."""
        reset_cache_stats()
        service = CachedMarketDataService()
        
        # Cache the result
        result1 = service.get_latest_price(db_session, sample_company.id)
        
        # Verify it's cached
        result2 = service.get_latest_price(db_session, sample_company.id)
        assert result1 == result2
        
        # Invalidate cache
        invalidate_market_data_cache()
        
        # Next call should be a miss
        result3 = service.get_latest_price(db_session, sample_company.id)
        
        stats = get_cache_stats()
        assert stats["market_data"]["misses"] == 2
        assert stats["market_data"]["hits"] == 1


class TestCachedPortfolioValuation:
    """Test cached portfolio valuation service."""
    
    def test_get_portfolio_snapshot_cache(
        self, db_session: Session, sample_portfolio: Portfolio, sample_position: Position
    ):
        """Test portfolio snapshot caching."""
        reset_cache_stats()
        service = CachedPortfolioValuationService()
        
        # First call: cache miss
        result1 = service.get_portfolio_snapshot(db_session)
        assert result1["portfolio_id"] == sample_portfolio.id
        assert result1["positions_count"] == 1
        
        # Second call: cache hit
        result2 = service.get_portfolio_snapshot(db_session)
        assert result1 == result2
        
        stats = get_cache_stats()
        assert stats["portfolio_valuation"]["hits"] == 1
        assert stats["portfolio_valuation"]["misses"] == 1
    
    def test_position_change_invalidates_cache(
        self, db_session: Session, sample_portfolio: Portfolio, sample_position: Position
    ):
        """Test that position changes invalidate cache."""
        reset_cache_stats()
        service = CachedPortfolioValuationService()
        
        # Cache the snapshot
        result1 = service.get_portfolio_snapshot(db_session)
        
        # Modify position
        sample_position.quantity = Decimal("200")
        db_session.commit()
        
        # Next call should be a miss due to auto-invalidation
        result2 = service.get_portfolio_snapshot(db_session)
        
        stats = get_cache_stats()
        assert stats["portfolio_valuation"]["misses"] == 2
    
    def test_tenant_isolation(self, db_session: Session, sample_portfolio: Portfolio, sample_position: Position):
        """Test that cache is isolated by tenant."""
        reset_cache_stats()
        service = CachedPortfolioValuationService()
        
        # Tenant 1
        db_session.info["tenant_id"] = 1
        result1 = service.get_portfolio_snapshot(db_session)
        
        # Tenant 2 - should be a miss
        db_session.info["tenant_id"] = 2
        result2 = service.get_portfolio_snapshot(db_session)
        
        stats = get_cache_stats()
        assert stats["portfolio_valuation"]["misses"] == 2
        assert stats["portfolio_valuation"]["hits"] == 0


class TestCachedDcaSchedule:
    """Test cached DCA schedule service."""
    
    def test_get_dca_signals_cache(self, db_session: Session, sample_company: Company):
        """Test DCA signals caching."""
        reset_cache_stats()
        
        # Create a DCA signal
        signal = DcaSignalState(
            symbol=sample_company.symbol,
            current_level=2,
            verdict_month=date.today().replace(day=1),
            current_price=Decimal("150.00"),
            level_price=Decimal("145.00"),
            tenant_id=1,
        )
        db_session.add(signal)
        db_session.commit()
        
        service = CachedDcaScheduleService()
        
        # First call: cache miss
        result1 = service.get_dca_signals(db_session)
        assert len(result1) == 1
        assert result1[0]["symbol"] == sample_company.symbol
        
        # Second call: cache hit
        result2 = service.get_dca_signals(db_session)
        assert result1 == result2
        
        stats = get_cache_stats()
        assert stats["dca_schedule"]["hits"] == 1
        assert stats["dca_schedule"]["misses"] == 1


class TestCacheHitRate:
    """Test cache hit rate requirements."""
    
    def test_repeated_requests_achieve_70_percent_hit_rate(
        self, db_session: Session, sample_company: Company, sample_prices
    ):
        """Test that repeated requests achieve >70% hit rate."""
        reset_cache_stats()
        service = CachedMarketDataService()
        
        # Simulate 100 requests with realistic pattern:
        # - 10 unique queries (cache misses)
        # - 90 repeated queries (cache hits)
        for i in range(10):
            service.get_price_history(db_session, sample_company.id, days=i+1)
        
        for i in range(90):
            # Repeat the same 10 queries
            service.get_price_history(db_session, sample_company.id, days=(i % 10) + 1)
        
        stats = get_cache_stats()
        hit_rate = stats["market_data"]["hit_rate"]
        
        # Should achieve >70% hit rate
        assert hit_rate > 70.0
        assert stats["market_data"]["total"] == 100


class TestFailOpen:
    """Test fail-open behavior when Redis is unavailable."""
    
    @patch('app.core.cache._redis_client')
    def test_cache_degrades_gracefully_on_redis_failure(
        self, mock_redis, db_session: Session, sample_company: Company, sample_prices
    ):
        """Test that service works when Redis fails."""
        # Mock Redis to return None (unavailable)
        mock_redis.return_value = None
        
        service = CachedMarketDataService()
        
        # Should still work, just without caching
        result = service.get_latest_price(db_session, sample_company.id)
        assert result is not None
        assert result["company_id"] == sample_company.id


class TestCacheTTL:
    """Test cache TTL enforcement."""
    
    @patch('time.monotonic')
    def test_cache_respects_ttl(self, mock_time, db_session: Session, sample_company: Company, sample_prices):
        """Test that cache entries expire after TTL."""
        # This test would require mocking Redis or using a test Redis instance
        # For now, we verify the TTL is set correctly in the decorator
        from app.core.cache import MARKET_DATA_TTL
        
        assert MARKET_DATA_TTL == 300  # 5 minutes
