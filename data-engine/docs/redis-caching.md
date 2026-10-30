# Redis Caching Implementation

## Overview

This implementation adds Redis caching for market data, portfolio valuations, and DCA schedules to improve performance and reduce database load.

## Features

### 1. Market Data Caching (`app/services/cached_market_data.py`)
- **TTL**: 5 minutes
- **Cached operations**:
  - Latest prices by company ID
  - Batch price retrieval
  - Price quotes by symbol
  - Price history (30 days)

### 2. Portfolio Valuation Caching (`app/services/cached_portfolio_valuation.py`)
- **TTL**: 10 minutes
- **Cached operations**:
  - Portfolio snapshots
  - Position summaries
  - Portfolio performance metrics
- **Automatic invalidation**: Cache is automatically invalidated when positions or transactions change

### 3. DCA Schedule Caching (`app/services/cached_dca_schedule.py`)
- **TTL**: 5 minutes
- **Cached operations**:
  - DCA signals for all symbols
  - DCA signal for individual symbols
  - Watchlist DCA signals
  - Portfolio DCA signals
- **Automatic invalidation**: Cache is automatically invalidated when DCA signal states change

## Architecture

### Core Components

- **`app/core/cache.py`**: Core caching decorator and utilities
  - `@cached` decorator for transparent caching
  - Cache statistics tracking (hits, misses, hit rate)
  - Invalidation functions
  - Fail-open behavior (degrades gracefully if Redis is unavailable)

- **`app/api/routes/cache.py`**: API endpoints for cache management
  - `GET /api/cache/stats`: View cache statistics
  - `POST /api/cache/invalidate/market-data`: Invalidate market data cache
  - `POST /api/cache/invalidate/portfolio`: Invalidate portfolio cache
  - `POST /api/cache/invalidate/dca`: Invalidate DCA cache
  - `POST /api/cache/invalidate/all`: Invalidate all caches
  - `POST /api/cache/stats/reset`: Reset statistics

### Tenant Isolation

Cache keys include tenant ID to ensure isolation between tenants. Tenant ID is extracted from `db.info["tenant_id"]` which is set by the authentication middleware.

### Cache Key Generation

Cache keys are generated using SHA256 hash of:
- Tenant ID
- Function arguments
- Function keyword arguments

This ensures deterministic keys and avoids collisions.

## Performance Expectations

- **Cache hit rate**: >70% for repeated requests
- **Dashboard load time**: <200ms when served from cache
- **Database load reduction**: ~60-80% for cached queries

## Usage

### Using Cached Services

```python
from app.services.cached_market_data import CachedMarketDataService
from app.services.cached_portfolio_valuation import CachedPortfolioValuationService
from app.services.cached_dca_schedule import CachedDcaScheduleService

# Market data
market_service = CachedMarketDataService()
latest_price = market_service.get_latest_price(db, company_id)
prices_batch = market_service.get_prices_batch(db, (company_id1, company_id2))
history = market_service.get_price_history(db, company_id, days=30)

# Portfolio valuation
portfolio_service = CachedPortfolioValuationService()
snapshot = portfolio_service.get_portfolio_snapshot(db)
summary = portfolio_service.get_positions_summary(db)

# DCA schedules
dca_service = CachedDcaScheduleService()
signals = dca_service.get_dca_signals(db)
signal = dca_service.get_dca_signal(db, symbol="AAPL")
```

### Manual Cache Invalidation

```python
from app.core.cache import (
    invalidate_market_data_cache,
    invalidate_portfolio_cache,
    invalidate_dca_cache,
)

# Invalidate all market data
invalidate_market_data_cache()

# Invalidate portfolio for current tenant
invalidate_portfolio_cache(db=db)

# Invalidate DCA for specific tenant
invalidate_dca_cache(tenant_id=1)
```

### Viewing Cache Statistics

```bash
curl http://localhost:8000/api/cache/stats
```

Response:
```json
{
  "market_data": {
    "hits": 850,
    "misses": 150,
    "total": 1000,
    "hit_rate": 85.0
  },
  "portfolio_valuation": {
    "hits": 420,
    "misses": 80,
    "total": 500,
    "hit_rate": 84.0
  },
  "dca_schedule": {
    "hits": 180,
    "misses": 20,
    "total": 200,
    "hit_rate": 90.0
  }
}
```

## Testing

Run the cache tests:

```bash
cd data-engine
APP_ENV=test uv run pytest tests/test_redis_caching.py -v
```

Tests verify:
- Cache hit/miss behavior
- TTL enforcement
- Tenant isolation
- Dependency invalidation
- Fail-open behavior
- >70% hit rate for repeated requests

## Configuration

Redis configuration is in `.env`:

```bash
REDIS_URL=redis://localhost:6379/0
```

Cache TTLs are defined in `app/core/cache.py`:
- `MARKET_DATA_TTL = 300` (5 minutes)
- `PORTFOLIO_VALUATION_TTL = 600` (10 minutes)
- `DCA_SCHEDULE_TTL = 300` (5 minutes)

## Monitoring

Cache statistics are tracked in-memory and can be accessed via the API or programmatically:

```python
from app.core.cache import get_cache_stats

stats = get_cache_stats()
print(f"Market data hit rate: {stats['market_data']['hit_rate']:.1f}%")
```

## Failure Handling

The caching layer is designed to fail-open:
- If Redis is unavailable, queries go directly to the database
- Connection failures trigger a 30-second backoff before retrying
- Cache errors are logged but never break the application

## Performance Impact

Expected performance improvements:
- Dashboard load: 400-500ms → <200ms (60% reduction)
- Repeated market data queries: 50-100ms → <10ms (80-90% reduction)
- Portfolio valuation: 200-300ms → <50ms (70-80% reduction)

Fulfills: **VAL-PERF-004**
