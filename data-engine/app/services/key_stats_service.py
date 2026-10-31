"""Datos clave de la ficha, estilo Stock Analysis: rango de 52 semanas,
proximos resultados, fecha ex-dividendo y beta.

Solo fuentes gratuitas que GerarAI ya usa, sin claves nuevas:

* Rango 52 semanas: los cierres diarios guardados en la BD (``MarketPrice``).
  Si el historial propio no cubre el ano (menos de ``MIN_SESSIONS_52W``
  sesiones), se usa el rango que publica Yahoo para ese listado, marcado como
  tal y solo si la divisa coincide.
* Proximos resultados: la tabla ``earnings_dates`` (Yahoo calendarEvents /
  NASDAQ, mantenida por el refresco de resultados); si no hay fila, la fecha
  de Yahoo con su marca de estimada.
* Ex-dividendo y beta: Yahoo Finance (no oficial) via yfinance, igual que los
  precios objetivo de analistas.

Regla de veracidad: un dato que ninguna fuente da queda en ``None`` y la UI no
pinta la fila; nunca se rellena ni se estima.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

DB_CLOSES_SOURCE = "Cierres diarios guardados en GerarAI"
YAHOO_SOURCE = "Yahoo Finance (no oficial)"
YAHOO_RANGE_SOURCE = "Yahoo Finance (no oficial), rango intradía"
YAHOO_BETA_SOURCE = "Yahoo Finance (no oficial), beta a 5 años con datos mensuales"
MIN_SESSIONS_52W = 200
CACHE_TTL_SECONDS = 6 * 3600
FETCH_TIMEOUT_SECONDS = 12.0


class Range52w(BaseModel):
    low: float
    high: float
    low_date: str | None = None
    high_date: str | None = None
    sessions: int | None = None
    source: str


class KeyDate(BaseModel):
    date: str
    upcoming: bool
    confirmed: bool | None = None
    source: str


class Beta(BaseModel):
    value: float
    source: str


class KeyStats(BaseModel):
    symbol: str
    fetched_at: int
    currency: str | None = None
    range_52w: Range52w | None = None
    next_earnings: KeyDate | None = None
    ex_dividend: KeyDate | None = None
    beta: Beta | None = None
    note: str | None = None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _epoch_date(value: Any) -> date | None:
    number = _finite(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=UTC).date()


def range_from_closes(rows: list[tuple[date, float]], today: date) -> Range52w | None:
    """Minimo y maximo de cierre de las ultimas 52 semanas (cierres propios)."""
    cutoff = today - timedelta(days=365)
    valid = [(day, float(close)) for day, close in rows if day > cutoff and _positive(close) is not None]
    if not valid:
        return None
    low = min(valid, key=lambda row: row[1])
    high = max(valid, key=lambda row: row[1])
    return Range52w(
        low=low[1],
        high=high[1],
        low_date=low[0].isoformat(),
        high_date=high[0].isoformat(),
        sessions=len(valid),
        source=DB_CLOSES_SOURCE,
    )


def normalize_yahoo_info(info: dict[str, Any], today: date) -> dict[str, Any]:
    """Se queda solo con valores reales del ``info`` de Yahoo."""
    beta = _finite(info.get("beta"))
    earnings = _epoch_date(info.get("earningsTimestamp") or info.get("earningsTimestampStart"))
    estimate = info.get("isEarningsDateEstimate")
    low, high = _positive(info.get("fiftyTwoWeekLow")), _positive(info.get("fiftyTwoWeekHigh"))
    ex_dividend = _epoch_date(info.get("exDividendDate"))
    return {
        "beta": round(beta, 2) if beta is not None else None,
        "ex_dividend": ex_dividend.isoformat() if ex_dividend else None,
        "earnings": earnings.isoformat() if earnings and earnings >= today else None,
        "earnings_confirmed": (not estimate) if isinstance(estimate, bool) else None,
        "low_52w": low if low is not None and high is not None and low <= high else None,
        "high_52w": high if low is not None and high is not None and low <= high else None,
        "currency": str(info["currency"]).strip().upper() if info.get("currency") else None,
    }


def _fetch_yahoo_info(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    return dict(yf.Ticker(symbol).get_info() or {})


def _own_data(db: Session, ticker: str, today: date) -> dict[str, Any]:
    from app.models import MarketPrice
    from app.models.entities import EarningsDate
    from app.services.company_resolver import resolve_company
    from app.services.propicks_price_service import yahoo_symbol

    company = resolve_company(db, ticker)
    out: dict[str, Any] = {"found": company is not None, "yahoo": ticker.strip().upper(), "currency": None}
    if company is not None:
        out["yahoo"] = yahoo_symbol(company)
        out["currency"] = (company.currency or "").upper() or None
        rows = db.execute(
            select(MarketPrice.date, MarketPrice.close).where(
                MarketPrice.company_id == company.id,
                MarketPrice.close.isnot(None),
                MarketPrice.date > today - timedelta(days=365),
            )
        ).all()
        out["range"] = range_from_closes([(row[0], row[1]) for row in rows], today)
    symbol = (company.ticker if company is not None else ticker).strip().upper()
    nxt = db.scalars(
        select(EarningsDate)
        .where(EarningsDate.ticker == symbol, EarningsDate.event_date >= today)
        .order_by(EarningsDate.event_date.asc())
    ).first()
    if nxt is not None:
        out["earnings"] = KeyDate(
            date=nxt.event_date.isoformat(),
            upcoming=True,
            confirmed=nxt.confirmed,
            source=nxt.source_label or YAHOO_SOURCE,
        )
    return out


class KeyStatsService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def clear(self) -> None:
        self._cache.clear()

    async def _yahoo(self, symbol: str, today: date) -> dict[str, Any] | None:
        now = time.time()
        hit = self._cache.get(symbol)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        try:
            info = await asyncio.wait_for(asyncio.to_thread(_fetch_yahoo_info, symbol), FETCH_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - Yahoo puede fallar; nunca se cachea un fallo
            return None
        data = normalize_yahoo_info(info, today)
        self._cache[symbol] = (now, data)
        return data

    async def get(self, db: Session, ticker: str) -> KeyStats:
        today = datetime.now(UTC).date()
        key = ticker.strip().upper()
        try:
            own = await run_in_threadpool(_own_data, db, key, today)
        except Exception:  # noqa: BLE001 - sin BD la ficha sigue con lo que de Yahoo
            own = {"found": False, "yahoo": key, "currency": None}
        yahoo = await self._yahoo(own["yahoo"], today) if own.get("yahoo") else None
        stats = KeyStats(symbol=key, fetched_at=int(time.time()), currency=own.get("currency"))
        rng: Range52w | None = own.get("range")
        same_currency = yahoo is not None and (
            own.get("currency") is None or yahoo.get("currency") == own.get("currency")
        )
        if (
            (rng is None or (rng.sessions or 0) < MIN_SESSIONS_52W)
            and same_currency
            and yahoo
            and yahoo["low_52w"]
        ):
            rng = Range52w(low=yahoo["low_52w"], high=yahoo["high_52w"], source=YAHOO_RANGE_SOURCE)
        stats.range_52w = rng
        stats.next_earnings = own.get("earnings")
        if stats.next_earnings is None and yahoo and yahoo["earnings"]:
            stats.next_earnings = KeyDate(
                date=yahoo["earnings"],
                upcoming=True,
                confirmed=yahoo["earnings_confirmed"],
                source=YAHOO_SOURCE,
            )
        if yahoo and yahoo["ex_dividend"]:
            stats.ex_dividend = KeyDate(
                date=yahoo["ex_dividend"],
                upcoming=yahoo["ex_dividend"] >= today.isoformat(),
                source=YAHOO_SOURCE,
            )
        if yahoo and yahoo["beta"] is not None:
            stats.beta = Beta(value=yahoo["beta"], source=YAHOO_BETA_SOURCE)
        if stats.currency is None and yahoo:
            stats.currency = yahoo.get("currency")
        if yahoo is None:
            stats.note = "No se pudo consultar Yahoo Finance ahora: faltan beta y ex-dividendo; reintenta en unos minutos."
        return stats


key_stats_service = KeyStatsService()
