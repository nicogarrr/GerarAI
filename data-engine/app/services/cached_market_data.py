"""Cached market data service with 5-minute TTL.

Wraps common market data queries with Redis caching for improved performance.
Expected cache hit rate >70% for repeated requests.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import (
    MARKET_DATA_PREFIX,
    MARKET_DATA_TTL,
    cached,
    invalidate_market_data_cache,
)
from app.models import Company, MarketPrice

logger = logging.getLogger(__name__)


class CachedMarketDataService:
    """Service for cached market data queries."""
    
    @cached(prefix=f"{MARKET_DATA_PREFIX}:price", ttl=MARKET_DATA_TTL, category="market_data")
    def get_latest_price(self, db: Session, company_id: int) -> dict[str, Any] | None:
        """Obtiene el precio mas reciente de una compania con cache de 5 minutos."""
        price = db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company_id)
            .order_by(MarketPrice.date.desc())
            .limit(1)
        )
        if price is None:
            return None
        
        return {
            "company_id": price.company_id,
            "price": float(price.close),
            "as_of": price.date.isoformat(),
            "currency": price.quote_currency or "USD",
            "source": price.source,
        }
    
    @cached(prefix=f"{MARKET_DATA_PREFIX}:prices_batch", ttl=MARKET_DATA_TTL, category="market_data")
    def get_prices_batch(self, db: Session, company_ids: tuple[int, ...]) -> dict[int, dict[str, Any]]:
        """Obtiene precios en lote para multiples companias con cache."""
        if not company_ids:
            return {}
        
        # Subconsulta para obtener el precio mas reciente por compania
        from sqlalchemy import func
        
        subq = (
            select(
                MarketPrice.company_id,
                func.max(MarketPrice.date).label("max_date")
            )
            .where(MarketPrice.company_id.in_(company_ids))
            .group_by(MarketPrice.company_id)
            .subquery()
        )
        
        prices = db.scalars(
            select(MarketPrice)
            .join(
                subq,
                (MarketPrice.company_id == subq.c.company_id)
                & (MarketPrice.date == subq.c.max_date)
            )
        ).all()
        
        result = {}
        for price in prices:
            result[price.company_id] = {
                "company_id": price.company_id,
                "price": float(price.close),
                "as_of": price.date.isoformat(),
                "currency": price.quote_currency or "USD",
                "source": price.source,
            }
        
        return result
    
    @cached(prefix=f"{MARKET_DATA_PREFIX}:quote", ttl=MARKET_DATA_TTL, category="market_data")
    def get_quote(self, db: Session, symbol: str) -> dict[str, Any] | None:
        """Obtiene quote de un simbolo con cache."""
        company = db.scalar(select(Company).where(Company.ticker == symbol))
        if company is None:
            return None
        
        price_data = self.get_latest_price(db, company.id)
        if price_data is None:
            return None
        
        return {
            "symbol": symbol,
            "company_id": company.id,
            "name": company.name,
            **price_data,
        }
    
    @cached(prefix=f"{MARKET_DATA_PREFIX}:history", ttl=MARKET_DATA_TTL, category="market_data")
    def get_price_history(
        self, db: Session, company_id: int, days: int = 30
    ) -> list[dict[str, Any]]:
        """Obtiene historia de precios con cache."""
        from datetime import date, timedelta
        
        cutoff = date.today() - timedelta(days=days)
        
        prices = db.scalars(
            select(MarketPrice)
            .where(
                MarketPrice.company_id == company_id,
                MarketPrice.date >= cutoff
            )
            .order_by(MarketPrice.date.desc())
        ).all()
        
        return [
            {
                "as_of": price.date.isoformat(),
                "price": float(price.close),
                "currency": price.quote_currency or "USD",
                "source": price.source,
            }
            for price in prices
        ]
    
    def invalidate_cache(self) -> None:
        """Invalida toda la cache de market data."""
        invalidate_market_data_cache()
