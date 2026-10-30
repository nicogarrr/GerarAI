"""Cached portfolio valuation service with dependency invalidation.

Wraps portfolio valuation queries with Redis caching. Cache is invalidated
when portfolio positions, transactions, or market prices are updated.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.cache import (
    PORTFOLIO_VALUATION_PREFIX,
    PORTFOLIO_VALUATION_TTL,
    cached,
    invalidate_portfolio_cache,
)
from app.core.tenancy import tenant_cache_scope
from app.models import Position, Transaction

logger = logging.getLogger(__name__)


def _extract_tenant_from_db(args, kwargs) -> int | None:
    """Extrae tenant_id del primer argumento (Session db)."""
    if len(args) >= 2 and hasattr(args[1], 'info'):  # args[0] es self, args[1] es db
        tenant_id = args[1].info.get("tenant_id")
        if tenant_id is not None:
            return tenant_id
    return tenant_cache_scope.get()


class CachedPortfolioValuationService:
    """Service for cached portfolio valuation queries."""
    
    @cached(
        prefix=f"{PORTFOLIO_VALUATION_PREFIX}:snapshot",
        ttl=PORTFOLIO_VALUATION_TTL,
        category="portfolio_valuation",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_portfolio_snapshot(self, db: Session, as_of: date | None = None) -> dict[str, Any]:
        """Obtiene snapshot de cartera con cache de 10 minutos."""
        from app.services.portfolio_fx_service import PortfolioFXService
        
        snapshot_date = as_of or date.today()
        fx_service = PortfolioFXService()
        portfolio = fx_service.ensure_portfolio(db)
        
        # Obtener posiciones
        positions = list(
            db.scalars(
                select(Position)
                .where(Position.portfolio_id == portfolio.id)
                .order_by(Position.company_id)
            ).all()
        )
        
        # Calcular valor total
        total_value = Decimal("0")
        positions_data = []
        
        for position in positions:
            value = position.quantity * position.market_price
            total_value += value
            
            positions_data.append({
                "company_id": position.company_id,
                "symbol": position.company.ticker if position.company else None,
                "quantity": float(position.quantity),
                "market_price": float(position.market_price),
                "currency": position.currency,
                "value": float(value),
                "as_of": position.as_of.isoformat(),
            })
        
        return {
            "snapshot_date": snapshot_date.isoformat(),
            "portfolio_id": portfolio.id,
            "base_currency": portfolio.base_currency,
            "total_value": float(total_value),
            "positions": positions_data,
            "positions_count": len(positions_data),
        }
    
    @cached(
        prefix=f"{PORTFOLIO_VALUATION_PREFIX}:positions",
        ttl=PORTFOLIO_VALUATION_TTL,
        category="portfolio_valuation",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_positions_summary(self, db: Session) -> dict[str, Any]:
        """Obtiene resumen de posiciones con cache."""
        from app.services.portfolio_fx_service import PortfolioFXService
        
        fx_service = PortfolioFXService()
        portfolio = fx_service.ensure_portfolio(db)
        
        positions = list(
            db.scalars(
                select(Position)
                .where(Position.portfolio_id == portfolio.id)
            ).all()
        )
        
        total_value = sum(p.quantity * p.market_price for p in positions)
        
        return {
            "portfolio_id": portfolio.id,
            "positions_count": len(positions),
            "total_value": float(total_value),
            "currencies": list({p.currency for p in positions}),
        }
    
    @cached(
        prefix=f"{PORTFOLIO_VALUATION_PREFIX}:performance",
        ttl=PORTFOLIO_VALUATION_TTL,
        category="portfolio_valuation",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_portfolio_performance(self, db: Session, days: int = 30) -> dict[str, Any]:
        """Obtiene metricas de performance con cache."""
        snapshot = self.get_portfolio_snapshot(db)
        
        # Calcular metricas basicas (simplificado para el ejemplo)
        return {
            "current_value": snapshot["total_value"],
            "positions_count": snapshot["positions_count"],
            "period_days": days,
            "base_currency": snapshot["base_currency"],
        }
    
    def invalidate_cache(self, db: Session) -> None:
        """Invalida cache de valoracion de cartera para el tenant actual."""
        invalidate_portfolio_cache(db=db)


# Event listeners para invalidacion automatica
def _setup_invalidation_listeners():
    """Configura listeners de SQLAlchemy para invalidar cache al modificar datos."""
    
    @event.listens_for(Position, "after_insert")
    @event.listens_for(Position, "after_update")
    @event.listens_for(Position, "after_delete")
    def invalidate_on_position_change(mapper, connection, target):
        """Invalida cache cuando cambian posiciones."""
        try:
            tenant_id = getattr(target, 'tenant_id', None)
            invalidate_portfolio_cache(tenant_id)
            logger.debug(f"Invalidated portfolio cache after position change (tenant={tenant_id})")
        except Exception as exc:
            logger.warning(f"Failed to invalidate cache on position change: {exc}")
    
    @event.listens_for(Transaction, "after_insert")
    @event.listens_for(Transaction, "after_update")
    @event.listens_for(Transaction, "after_delete")
    def invalidate_on_transaction_change(mapper, connection, target):
        """Invalida cache cuando cambian transacciones."""
        try:
            tenant_id = getattr(target, 'tenant_id', None)
            invalidate_portfolio_cache(tenant_id)
            logger.debug(f"Invalidated portfolio cache after transaction change (tenant={tenant_id})")
        except Exception as exc:
            logger.warning(f"Failed to invalidate cache on transaction change: {exc}")


# Instalar listeners al importar el modulo
_setup_invalidation_listeners()
