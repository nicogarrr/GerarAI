"""Resto del universo del screener Mercado: ultimo cierre desde market_prices.

Los 35 valores en vivo (Finnhub) van aparte. Aqui solo hay cierres diarios ya
almacenados, cada fila con su fecha. Sin dato no hay fila: nada se inventa.
Se excluyen entradas de prueba por patron de ticker (ZZZ..., TEST...): exigir
CIK o ISIN dejaba ~53 de ~1.950 empresas con cierre reciente, porque la mayoria
de los valores reales no tienen esos campos rellenos.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice

_TEST_TICKER = re.compile(r"Z{3,}\d*|TEST[A-Z0-9]*")

MAX_STALE_DAYS = 10  # un cierre mas viejo no se vende como "el cierre"


def _is_test_ticker(ticker: str) -> bool:
    return bool(_TEST_TICKER.fullmatch(ticker.upper()))


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
    )
    if sector:
        q = q.where(Company.sector == sector)
    pairs = [
        (c, p)
        for c, p in db.execute(q).all()
        if c.ticker.upper() not in exclude_symbols
        and not _is_test_ticker(c.ticker)
        and (today - p.date).days <= MAX_STALE_DAYS
    ]
    pairs.sort(key=lambda cp: cp[0].ticker)
    total = len(pairs)
    # Se corta ANTES de pedir el cierre previo: una sola consulta con ventana
    # para la pagina, no una por empresa (~1.900 por carga).
    page = pairs[:limit]
    prev_by_company: dict[int, Any] = {}
    if page:
        ranked = (
            select(
                MarketPrice.company_id.label("cid"),
                MarketPrice.close.label("close"),
                func.row_number()
                .over(partition_by=MarketPrice.company_id, order_by=MarketPrice.date.desc())
                .label("rn"),
            )
            .where(MarketPrice.company_id.in_([c.id for c, _ in page]), MarketPrice.close > 0)
            .subquery()
        )
        prev_by_company = {
            cid: close for cid, close in db.execute(select(ranked.c.cid, ranked.c.close).where(ranked.c.rn == 2))
        }
    rows: list[dict[str, Any]] = []
    for company, last in page:
        prev = prev_by_company.get(company.id)
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
    return {"rows": rows, "total": total, "limit": limit}
