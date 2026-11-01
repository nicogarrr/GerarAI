"""Cached DCA schedule service with 5-minute TTL.

Wraps DCA signal queries with Redis caching for improved performance.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import (
    DCA_SCHEDULE_PREFIX,
    DCA_SCHEDULE_TTL,
    cached,
    invalidate_dca_cache,
)
from app.core.tenancy import tenant_filters
from app.models import DcaSignalState, Position, WatchItem

logger = logging.getLogger(__name__)


def _extract_tenant_from_db(args, kwargs) -> int | None:
    """Extrae tenant_id del primer argumento (Session db)."""
    if len(args) >= 2 and hasattr(args[1], 'info'):  # args[0] es self, args[1] es db
        return args[1].info.get("tenant_id")
    return None


class CachedDcaScheduleService:
    """Service for cached DCA schedule queries."""
    
    @cached(
        prefix=f"{DCA_SCHEDULE_PREFIX}:signals",
        ttl=DCA_SCHEDULE_TTL,
        category="dca_schedule",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_dca_signals(self, db: Session) -> list[dict[str, Any]]:
        """Obtiene senales DCA activas con cache de 5 minutos."""
        # Obtener todos los estados de senal DCA
        states = list(
            db.scalars(
                select(DcaSignalState)
                .where(*tenant_filters(db, DcaSignalState))
                .order_by(DcaSignalState.symbol)
            ).all()
        )
        
        result = []
        for state in states:
            level_price = None
            if state.level_prices and isinstance(state.level_prices, dict):
                val = state.level_prices.get(str(state.level))
                if val is not None:
                    try:
                        level_price = float(val)
                    except (ValueError, TypeError):
                        pass
            result.append({
                "symbol": state.symbol,
                "current_level": state.level,
                "verdict_month": state.period,
                "current_price": float(state.close) if state.close is not None else None,
                "level_price": level_price,
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            })
        
        return result
    
    @cached(
        prefix=f"{DCA_SCHEDULE_PREFIX}:signal",
        ttl=DCA_SCHEDULE_TTL,
        category="dca_schedule",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_dca_signal(self, db: Session, symbol: str) -> dict[str, Any] | None:
        """Obtiene senal DCA de un simbolo con cache."""
        state = db.scalar(
            select(DcaSignalState)
            .where(
                DcaSignalState.symbol == symbol,
                *tenant_filters(db, DcaSignalState)
            )
        )
        
        if state is None:
            return None
        
        level_price = None
        if state.level_prices and isinstance(state.level_prices, dict):
            val = state.level_prices.get(str(state.level))
            if val is not None:
                try:
                    level_price = float(val)
                except (ValueError, TypeError):
                    pass
        return {
            "symbol": state.symbol,
            "current_level": state.level,
            "verdict_month": state.period,
            "current_price": float(state.close) if state.close is not None else None,
            "level_price": level_price,
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            "metadata": state.metrics if hasattr(state, "metrics") and state.metrics else {},
        }
    
    @cached(
        prefix=f"{DCA_SCHEDULE_PREFIX}:watchlist",
        ttl=DCA_SCHEDULE_TTL,
        category="dca_schedule",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_watchlist_dca_signals(self, db: Session) -> list[dict[str, Any]]:
        """Obtiene senales DCA de la watchlist con cache."""
        # Obtener simbolos de watchlist
        watch_items = list(
            db.scalars(
                select(WatchItem)
                .where(*tenant_filters(db, WatchItem))
            ).all()
        )
        
        symbols = [item.symbol for item in watch_items]
        
        if not symbols:
            return []
        
        # Obtener senales para esos simbolos
        states = list(
            db.scalars(
                select(DcaSignalState)
                .where(
                    DcaSignalState.symbol.in_(symbols),
                    *tenant_filters(db, DcaSignalState)
                )
                .order_by(DcaSignalState.level.desc())
            ).all()
        )
        
        result = []
        for state in states:
            level_price = None
            if state.level_prices and isinstance(state.level_prices, dict):
                val = state.level_prices.get(str(state.level))
                if val is not None:
                    try:
                        level_price = float(val)
                    except (ValueError, TypeError):
                        pass
            result.append({
                "symbol": state.symbol,
                "current_level": state.level,
                "verdict_month": state.period,
                "current_price": float(state.close) if state.close is not None else None,
                "level_price": level_price,
            })
        
        return result
    
    @cached(
        prefix=f"{DCA_SCHEDULE_PREFIX}:portfolio",
        ttl=DCA_SCHEDULE_TTL,
        category="dca_schedule",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_portfolio_dca_signals(self, db: Session) -> list[dict[str, Any]]:
        """Obtiene senales DCA de posiciones en cartera con cache."""
        from app.services.portfolio_fx_service import PortfolioFXService
        
        fx_service = PortfolioFXService()
        portfolio = fx_service.ensure_portfolio(db)
        
        # Obtener posiciones activas
        positions = list(
            db.scalars(
                select(Position)
                .where(Position.portfolio_id == portfolio.id)
            ).all()
        )
        
        symbols = [p.company.ticker for p in positions if p.company and p.company.ticker]
        
        if not symbols:
            return []
        
        # Obtener senales para esos simbolos
        states = list(
            db.scalars(
                select(DcaSignalState)
                .where(
                    DcaSignalState.symbol.in_(symbols),
                    *tenant_filters(db, DcaSignalState)
                )
                .order_by(DcaSignalState.level.desc())
            ).all()
        )
        
        result = []
        for state in states:
            level_price = None
            if state.level_prices and isinstance(state.level_prices, dict):
                val = state.level_prices.get(str(state.level))
                if val is not None:
                    try:
                        level_price = float(val)
                    except (ValueError, TypeError):
                        pass
            result.append({
                "symbol": state.symbol,
                "current_level": state.level,
                "current_price": float(state.close) if state.close is not None else None,
                "level_price": level_price,
            })
        
        return result
    
    def invalidate_cache(self, db: Session) -> None:
        """Invalida cache de DCA para el tenant actual."""
        invalidate_dca_cache(db=db)

# La invalidacion automatica por eventos ORM vive en
# app.core.cache_invalidation (instalada desde app.models); los listeners que
# habia aqui nunca llegaban a instalarse porque nadie importaba este modulo.
