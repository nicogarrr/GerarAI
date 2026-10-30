"""API endpoints for cache statistics and management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.cache import (
    get_cache_stats,
    invalidate_dca_cache,
    invalidate_market_data_cache,
    invalidate_portfolio_cache,
    reset_cache_stats,
)
from app.core.database import get_db

router = APIRouter()


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """Get cache statistics including hit rates.
    
    Returns cache hits, misses, and hit rate percentage for:
    - market_data: Market prices, quotes, history
    - portfolio_valuation: Portfolio snapshots and valuations
    - dca_schedule: DCA signals and schedules
    
    Expected hit rate >70% for repeated requests.
    """
    return get_cache_stats()


@router.post("/invalidate/market-data")
def invalidate_market_data(db: Session = Depends(get_db)) -> dict[str, str]:
    """Invalidate all market data cache entries."""
    invalidate_market_data_cache()
    return {"status": "ok", "message": "Market data cache invalidated"}


@router.post("/invalidate/portfolio")
def invalidate_portfolio(db: Session = Depends(get_db)) -> dict[str, str]:
    """Invalidate portfolio valuation cache for current tenant."""
    invalidate_portfolio_cache(db=db)
    tenant_id = db.info.get("tenant_id", "unknown")
    return {"status": "ok", "message": f"Portfolio cache invalidated for tenant {tenant_id}"}


@router.post("/invalidate/dca")
def invalidate_dca(db: Session = Depends(get_db)) -> dict[str, str]:
    """Invalidate DCA schedule cache for current tenant."""
    invalidate_dca_cache(db=db)
    tenant_id = db.info.get("tenant_id", "unknown")
    return {"status": "ok", "message": f"DCA cache invalidated for tenant {tenant_id}"}


@router.post("/invalidate/all")
def invalidate_all(db: Session = Depends(get_db)) -> dict[str, str]:
    """Invalidate all cache entries for current tenant."""
    invalidate_market_data_cache()
    invalidate_portfolio_cache(db=db)
    invalidate_dca_cache(db=db)
    return {"status": "ok", "message": "All caches invalidated"}


@router.post("/stats/reset")
def reset_stats() -> dict[str, str]:
    """Reset cache statistics counters (for testing)."""
    reset_cache_stats()
    return {"status": "ok", "message": "Cache statistics reset"}
