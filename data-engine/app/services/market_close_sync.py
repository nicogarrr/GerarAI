"""Cierres oficiales diarios para todo el universo (market_prices).

El refresco intradia y las cotizaciones spot (Finnhub/FMP/yahoo 15 min) guardan
una foto del precio en un momento cualquiera, no el cierre oficial. Comparar
dos fotos daba variaciones distintas de las del proveedor (AAPL +0,45 % frente
a +0,43 %). Este job descarga las barras diarias reales (yfinance, sin ajustar)
de las ultimas sesiones y las escribe con source="yfinance": es la unica fuente
que Movers, Mercado y watchlist consideran cierre."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice
from app.services.propicks_price_service import (
    PriceBar,
    _bar_is_final,
    bar_unit_is_known,
    fetch_history_yfinance,
    upsert_prices,
    yahoo_symbol,
)

logger = logging.getLogger(__name__)

_NY = ZoneInfo("America/New_York")
# Una barra del dia en curso solo es cierre cuando la sesion US ya termino.
_SESSION_CLOSED_AFTER = (16, 30)
CHUNK = 100
MIN_TARGET_COVERAGE = 0.90


def last_completed_us_session(now: datetime) -> date:
    local = now.astimezone(_NY)
    day = local.date()
    if (local.hour, local.minute) < _SESSION_CLOSED_AFTER:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


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
    target_date = last_completed_us_session(now)
    target_covered = 0
    companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
    by_symbol = {s: c for c in companies if (s := yahoo_symbol(c)) is not None}
    symbols = list(by_symbol)
    written = 0
    latest_date: date | None = None
    covered = 0
    failed_chunks = 0
    failed_symbols: list[str] = []
    last_error: Exception | None = None
    for start in range(0, len(symbols), chunk):
        part = symbols[start : start + chunk]
        try:
            history = fetcher(part, period=period)
        except Exception as exc:  # noqa: BLE001 - un lote caido no tumba el resto
            # Un fallo de red/rate limit en un lote dejaba sin cierre a todos
            # los lotes siguientes. Se registra y se sigue con el proximo.
            logger.warning("market_close_sync: lote %s fallo: %s", start // chunk, exc)
            failed_chunks += 1
            failed_symbols.extend(part)
            last_error = exc
            continue
        for symbol in part:
            bars = history.get(symbol) or []
            if not bars:
                continue
            target_covered += int(any(bar.day == target_date and _bar_is_final(by_symbol[symbol], bar, now)
                                      and bar_unit_is_known(by_symbol[symbol], bar) for bar in bars))
            count = upsert_prices(db, by_symbol[symbol], bars, now=now)
            written += count
            if count:
                latest = max(bar.day for bar in bars
                             if _bar_is_final(by_symbol[symbol], bar, now)
                             and bar_unit_is_known(by_symbol[symbol], bar))
                latest_date = max(latest_date, latest) if latest_date else latest
            skipped += len(bars) - count
            covered += int(count > 0)
        db.commit()
    if last_error is not None and len(failed_symbols) == len(symbols):
        # Todo caido: se propaga para que el actor registre el error y
        # reintente como antes (no un «ok» vacio).
        raise last_error
    target_coverage = target_covered / len(symbols) if symbols else 0.0
    complete = target_coverage >= MIN_TARGET_COVERAGE
    status = "partial" if failed_chunks or not complete else "ok"
    return {
        "status": status,
        "target_date": target_date.isoformat(),
        "target_covered": target_covered,
        "target_coverage": target_coverage,
        "minimum_target_coverage": MIN_TARGET_COVERAGE,
        "failed_chunks": failed_chunks,
        "failed_symbols": failed_symbols,
        "companies": len(companies),
        "with_symbol": len(symbols),
        "covered": covered,
        "bars_written": written,
        "latest_date": latest_date.isoformat() if latest_date else None,
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
