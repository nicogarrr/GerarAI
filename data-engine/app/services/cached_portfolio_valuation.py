"""Cached portfolio valuation service with dependency invalidation.

Wraps portfolio valuation queries with Redis caching. Cache is invalidated
when portfolio positions, transactions, or market prices are updated.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.cache import (
    PORTFOLIO_VALUATION_PREFIX,
    PORTFOLIO_VALUATION_TTL,
    cached,
    invalidate_portfolio_cache,
    tenant_from_first_db_arg,
)
from app.core.cache import (
    tenant_from_method_db_arg as _extract_tenant_from_db,
)
from app.models import Position

logger = logging.getLogger(__name__)


def _position_value_base(
    position: Position, value_native: Decimal, base_currency: str
) -> Decimal | None:
    """Valor de la posicion en divisa base; ``None`` si no se conoce el tipo.

    Misma divisa que la base: el nativo (tipo 1). Otra divisa: solo el
    ``market_value_base`` que dejo el ledger (``None`` cuando falta el tipo
    de cambio); nunca se improvisa una conversion con el valor nativo.
    """
    if (position.currency or "").upper() == base_currency:
        return value_native
    return position.market_value_base



class CachedPortfolioValuationService:
    """Service for cached portfolio valuation queries."""
    
    @cached(
        prefix=f"{PORTFOLIO_VALUATION_PREFIX}:snapshot",
        ttl=PORTFOLIO_VALUATION_TTL,
        category="portfolio_valuation",
        extract_tenant=_extract_tenant_from_db,
    )
    def get_portfolio_snapshot(self, db: Session) -> dict[str, Any]:
        """Snapshot de cartera con cache de 10 minutos, valorado en divisa base.

        Antes aceptaba ``as_of`` y lo devolvia como ``snapshot_date`` mientras
        valoraba con las posiciones ACTUALES: una etiqueta de fecha que el
        dato no tenia. Y sumaba ``quantity * market_price`` en divisa NATIVA
        de cada posicion mezclando divisas bajo la etiqueta ``base_currency``.
        Ahora cada posicion lleva su valor nativo y su valor en base, y el
        total solo se publica si TODAS las posiciones tienen valor en base
        (una posicion sin tipo de cambio no vale 0 en la suma: falta, y se
        declara en ``positions_missing_base_value``).
        """
        from app.services.portfolio_fx_service import PortfolioFXService

        fx_service = PortfolioFXService()
        portfolio = fx_service.ensure_portfolio(db)
        base_currency = (portfolio.base_currency or "").upper()

        positions = list(
            db.scalars(
                select(Position)
                .options(joinedload(Position.company))
                .where(Position.portfolio_id == portfolio.id)
                .order_by(Position.company_id)
            ).all()
        )

        total_value = Decimal("0")
        positions_data: list[dict[str, Any]] = []
        missing_base_value: list[str] = []

        for position in positions:
            value_native = position.quantity * position.market_price
            symbol = position.company.ticker if position.company else None
            value_base = _position_value_base(position, value_native, base_currency)
            if value_base is None:
                missing_base_value.append(symbol or str(position.company_id))
            else:
                total_value += value_base
            positions_data.append({
                "company_id": position.company_id,
                "symbol": symbol,
                "quantity": float(position.quantity),
                "market_price": float(position.market_price),
                "currency": position.currency,
                "value": float(value_native),
                "value_base": float(value_base) if value_base is not None else None,
                "as_of": position.as_of.isoformat(),
            })

        complete = not missing_base_value
        return {
            "generated_at": date.today().isoformat(),
            "portfolio_id": portfolio.id,
            "base_currency": portfolio.base_currency,
            "total_value": float(total_value) if complete else None,
            "total_value_complete": complete,
            "positions_missing_base_value": sorted(missing_base_value),
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
        
        base_currency = (portfolio.base_currency or "").upper()
        total_value = Decimal("0")
        missing_base_value: list[str] = []
        for position in positions:
            value_base = _position_value_base(
                position, position.quantity * position.market_price, base_currency
            )
            if value_base is None:
                missing_base_value.append(str(position.company_id))
            else:
                total_value += value_base
        complete = not missing_base_value

        return {
            "portfolio_id": portfolio.id,
            "positions_count": len(positions),
            "total_value": float(total_value) if complete else None,
            "total_value_complete": complete,
            "positions_missing_base_value": sorted(missing_base_value),
            "currencies": sorted({p.currency for p in positions}),
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

# La invalidacion automatica por eventos ORM vive ahora en
# app.core.cache_invalidation (instalada desde app.models): este modulo se
# importaba solo en tests y sus listeners nunca se instalaban en produccion.


@cached(
    prefix=f"{PORTFOLIO_VALUATION_PREFIX}:risk_dashboard",
    ttl=PORTFOLIO_VALUATION_TTL,
    category="portfolio_valuation",
    extract_tenant=tenant_from_first_db_arg,
)
def risk_dashboard(db: Session) -> dict[str, Any]:
    '''Dashboard de valoracion/riesgo de cartera con cache de 10 min por tenant.

    Lo usa GET /portfolio/summary. Se invalida por eventos ORM al escribir
    posiciones, transacciones, caja, cartera o conversiones FX, y de forma
    explicita tras un market refresh o un PATCH de precios.
    '''
    from app.services.risk_service import RiskService

    return RiskService().dashboard(db)
