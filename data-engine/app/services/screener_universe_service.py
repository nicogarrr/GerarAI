"""Resto del universo del screener Mercado: ultimo cierre desde market_prices.

Los 35 valores en vivo (Finnhub) van aparte. Aqui solo hay cierres diarios ya
almacenados, cada fila con su fecha. Sin dato no hay fila: nada se inventa.
Se excluyen entradas de prueba: solo empresas con CIK o ISIN (reales) y con
al menos dos cierres recientes para calcular la variacion.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice

MAX_STALE_DAYS = 10  # un cierre mas viejo no se vende como "el cierre"


def universe_close_rows(
    db: Session,
    *,
    exclude_symbols: set[str],
    sector: str | None = None,
    limit: int = 100,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    since = today - timedelta(days=MAX_STALE_DAYS + 7)
    limit = max(1, min(limit, 500))
    latest_sq = (
        select(MarketPrice.company_id, func.max(MarketPrice.date).label("d"))
        .where(MarketPrice.close > 0, MarketPrice.date >= since)
        .group_by(MarketPrice.company_id)
        .subquery()
    )
    q = (
        select(Company, MarketPrice)
        .join(latest_sq, latest_sq.c.company_id == Company.id)
        .join(
            MarketPrice,
            (MarketPrice.company_id == Company.id) & (MarketPrice.date == latest_sq.c.d),
        )
        .where((Company.cik.isnot(None)) | (Company.isin.isnot(None)))
    )
    if sector:
        q = q.where(Company.sector == sector)
    pairs = [
        (c, p)
        for c, p in db.execute(q).all()
        if c.ticker.upper() not in exclude_symbols and (today - p.date).days <= MAX_STALE_DAYS
    ]
    rows: list[dict[str, Any]] = []
    for company, last in pairs:
        prev = db.scalar(
            select(MarketPrice.close)
            .where(
                MarketPrice.company_id == company.id,
                MarketPrice.date < last.date,
                MarketPrice.close > 0,
            )
            .order_by(MarketPrice.date.desc())
            .limit(1)
        )
        change = (
            float((last.close - prev) / prev * 100) if prev is not None and prev > 0 else None
        )
        rows.append(
            {
                "symbol": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "currency": company.currency,
                "close": float(last.close),
                "close_date": last.date.isoformat(),
                "change_pct": change,
                "source": last.source,
            }
        )
    rows.sort(key=lambda r: r["symbol"])
    total = len(rows)
    return {"rows": rows[:limit], "total": total, "limit": limit}
