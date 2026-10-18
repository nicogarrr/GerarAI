"""Cierres oficiales diarios para todo el universo (market_prices).

El refresco intradia y las cotizaciones spot (Finnhub/FMP/yahoo 15 min) guardan
una foto del precio en un momento cualquiera, no el cierre oficial. Comparar
dos fotos daba variaciones distintas de las del proveedor (AAPL +0,45 % frente
a +0,43 %). Este job descarga las barras diarias reales (yfinance, sin ajustar)
de las ultimas sesiones y las escribe con source="yfinance": es la unica fuente
que Movers, Mercado y watchlist consideran cierre."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Company
from app.services.propicks_price_service import (
    PriceBar,
    fetch_history_yfinance,
    upsert_prices,
    yahoo_symbol,
)

_NY = ZoneInfo("America/New_York")
# Una barra del dia en curso solo es cierre cuando la sesion US ya termino.
_SESSION_CLOSED_AFTER = (16, 30)
CHUNK = 100


def _session_open(now: datetime) -> bool:
    local = now.astimezone(_NY)
    if local.weekday() >= 5:
        return False
    return (local.hour, local.minute) < _SESSION_CLOSED_AFTER


def sync_official_closes(
    db: Session,
    *,
    period: str = "7d",
    fetcher: Callable[..., dict[str, list[PriceBar]]] = fetch_history_yfinance,
    now: datetime | None = None,
    chunk: int = CHUNK,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    today_ny = now.astimezone(_NY).date()
    skip_today = _session_open(now)
    companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
    by_symbol = {s: c for c in companies if (s := yahoo_symbol(c)) is not None}
    symbols = list(by_symbol)
    written = 0
    covered = 0
    for start in range(0, len(symbols), chunk):
        part = symbols[start : start + chunk]
        history = fetcher(part, period=period)
        for symbol in part:
            bars = [
                bar
                for bar in history.get(symbol) or []
                if not (skip_today and bar.day >= today_ny)
            ]
            if not bars:
                continue
            written += upsert_prices(db, by_symbol[symbol], bars)
            covered += 1
        db.commit()
    return {
        "status": "ok",
        "companies": len(companies),
        "with_symbol": len(symbols),
        "covered": covered,
        "bars_written": written,
        "partial_session_skipped": skip_today,
    }
