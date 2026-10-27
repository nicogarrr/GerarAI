"""Cierres oficiales diarios para todo el universo (market_prices).

El refresco intradia y las cotizaciones spot (Finnhub/FMP/yahoo 15 min) guardan
una foto del precio en un momento cualquiera, no el cierre oficial. Comparar
dos fotos daba variaciones distintas de las del proveedor (AAPL +0,45 % frente
a +0,43 %). Este job descarga las barras diarias reales (yfinance, sin ajustar)
de las ultimas sesiones y las escribe con source="yfinance": es la unica fuente
que Movers, Mercado y watchlist consideran cierre."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice
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
    skipped = 0
    companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
    by_symbol = {s: c for c in companies if (s := yahoo_symbol(c)) is not None}
    symbols = list(by_symbol)
    written = 0
    covered = 0
    for start in range(0, len(symbols), chunk):
        part = symbols[start : start + chunk]
        history = fetcher(part, period=period)
        for symbol in part:
            bars = history.get(symbol) or []
            if not bars:
                continue
            count = upsert_prices(db, by_symbol[symbol], bars, now=now)
            written += count
            skipped += len(bars) - count
            covered += int(count > 0)
        db.commit()
    return {
        "status": "ok",
        "companies": len(companies),
        "with_symbol": len(symbols),
        "covered": covered,
        "bars_written": written,
        "partial_session_skipped": skipped > 0,
    }


# Historial minimo que se considera suficiente para no re-descargar.
BACKFILL_MIN_HISTORY_DAYS = 300
BACKFILL_PERIOD = "1y"


def companies_needing_history_backfill(
    db: Session, company_ids: Iterable[int], *, today: date | None = None
) -> list[int]:
    """Ids sin historial profundo en MarketPrice (una sola query agrupada).

    MarketPrice solo acumula hacia adelante (sync_official_closes escribe la
    ultima semana cada dia), asi que una compania recien creada no tiene
    pasado: las metricas de cartera median ventanas de dias con pinta de
    anos. Estas son las candidatas a backfill.
    """
    ids = sorted({int(id_) for id_ in company_ids})
    if not ids:
        return []
    today = today or datetime.now(UTC).date()
    threshold = today - timedelta(days=BACKFILL_MIN_HISTORY_DAYS)
    earliest = dict(
        db.execute(
            select(MarketPrice.company_id, func.min(MarketPrice.date))
            .where(MarketPrice.company_id.in_(ids))
            .group_by(MarketPrice.company_id)
        ).all()
    )
    return [
        id_
        for id_ in ids
        if earliest.get(id_) is None or earliest[id_] > threshold
    ]


def backfill_company_history(
    db: Session,
    company: Company,
    *,
    period: str = BACKFILL_PERIOD,
    fetcher: Callable[..., dict[str, list[PriceBar]]] = fetch_history_yfinance,
    today: date | None = None,
) -> dict[str, Any]:
    """Descarga ~1 ano de historia de UNA compania (una llamada, ritmo amable).

    Idempotente: upsert por (company_id, date). Sin simbolo Yahoo, con
    historial ya suficiente o con fuente sin barras: skip declarado, sin
    inventar barras.
    """
    symbol = yahoo_symbol(company)
    if symbol is None:
        return {"status": "skipped", "reason": "sin simbolo Yahoo"}
    if company.id not in companies_needing_history_backfill(
        db, [company.id], today=today
    ):
        return {"status": "skipped", "reason": "historico suficiente"}
    history = fetcher([symbol], period=period)
    bars = history.get(symbol) or []
    if not bars:
        return {"status": "skipped", "reason": "fuente sin barras"}
    written = upsert_prices(db, company, bars)
    db.commit()
    return {"status": "ok", "bars_written": written, "period": period}


# Escalonado entre backfills: una importacion puede estrenar N companias y
# N tareas en paralelo contra Yahoo dispararian el rate limit de la fuente.
BACKFILL_STAGGER_MS = 60_000


def _send_backfill(
    company_id: int, tenant_id: int | None, user_id: str | None, delay_ms: int
) -> None:
    from app.workers.dramatiq_app import backfill_company_price_history

    backfill_company_price_history.send_with_options(
        args=(company_id,),
        kwargs={"tenant_id": tenant_id, "user_id": user_id},
        delay=delay_ms,
    )


def enqueue_price_backfills(
    db: Session,
    company_ids: Iterable[int],
    *,
    tenant_id: int | None = None,
    user_id: str | None = None,
    stagger_ms: int = BACKFILL_STAGGER_MS,
    sender: Callable[[int, int | None, str | None, int], None] = _send_backfill,
    today: date | None = None,
) -> int:
    """Encola backfills ESCALONADOS para las companias sin historial profundo.

    Devuelve cuantas tareas se encolaron. El delay incremental (0, stagger,
    2*stagger, ...) evita que una importacion con N companias nuevas dispare
    N llamadas simultaneas contra la fuente (rate limit).
    """
    enqueued = 0
    for company_id in companies_needing_history_backfill(db, company_ids, today=today):
        sender(company_id, tenant_id, user_id, enqueued * stagger_ms)
        enqueued += 1
    return enqueued
