"""Calendario de mercado (earnings, dividendos y catalizadores de cartera)."""

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.services import catalyst_calendar_service as catalyst_service
from app.services.connectors import earnings_calendar as calendar_connector

router = APIRouter()


async def _empty_connector() -> dict:
    """Conector no consultado: mismo contrato que uno que respondio vacio."""
    return {"status": "ok", "events": [], "errors": []}


def _resolve_range(desde: date | None, hasta: date | None) -> tuple[date, date]:
    start = desde or date.today()
    end = hasta or (start + timedelta(days=7))
    if start > end:
        raise HTTPException(status_code=400, detail="desde no puede ser posterior a hasta")
    if (end - start).days + 1 > calendar_connector.MAX_DAYS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"rango maximo: {calendar_connector.MAX_DAYS_PER_REQUEST} dias",
        )
    return start, end


@router.get("/earnings")
async def earnings_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
) -> dict:
    """Eventos de earnings entre ``desde`` y ``hasta`` (por defecto, 7 dias).

    El conector degrada a ``status="unavailable"`` si NASDAQ no responde;
    este endpoint nunca devuelve 5xx por un fallo del proveedor.
    """
    start, end = _resolve_range(desde, hasta)
    try:
        return await calendar_connector.fetch_earnings_range(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/dividends")
async def dividends_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
) -> dict:
    """Eventos de dividendos entre ``desde`` y ``hasta`` (por defecto, 7 dias)."""
    start, end = _resolve_range(desde, hasta)
    try:
        return await calendar_connector.fetch_dividends_range(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalysts")
async def catalysts_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Calendario unico de catalizadores de la cartera (por defecto, 14 dias).

    Une resultados y fecha ex-dividendo (NASDAQ publico, solo posiciones
    abiertas en bolsa US y USD) y acciones corporativas registradas sin
    aplicar. No incluye la fecha de pago: NASDAQ solo devuelve cada dividendo
    el dia de su ex-date, asi que un pago con ex-date anterior al rango
    quedaria fuera sin avisar. Si NASDAQ no
    responde, ``status`` lo declara (``partial``/``unavailable``) y las
    acciones corporativas propias se siguen mostrando; nunca devuelve 5xx
    por un fallo del proveedor.
    """
    start = desde or date.today()
    end = hasta or (start + timedelta(days=14))
    start, end = _resolve_range(start, end)
    # held_tickers y pending_actions son sqlalchemy sincrono: hilo del pool.
    held, held_us = await run_in_threadpool(catalyst_service.held_tickers, db)
    # Pieza 5: el calendario de resultados tambien cubre la watchlist (lineas
    # US), etiquetadas con origin="watchlist"; la cartera gana el origen.
    watch_us = await run_in_threadpool(catalyst_service.watchlist_us_tickers, db, held_us)
    if not held and not watch_us:
        return {
            "status": "ok",
            "desde": start.isoformat(),
            "hasta": end.isoformat(),
            "held_count": 0,
            "watchlist_count": 0,
            "count": 0,
            "events": [],
            "errors": [],
        }
    if held_us or watch_us:
        earnings, dividends, filings = await asyncio.gather(
            calendar_connector.fetch_earnings_range(start, end),
            # Dividendos y plazos 10-Q/10-K siguen siendo solo de cartera:
            # para watchlist el brief pide resultados, no ruido.
            calendar_connector.fetch_dividends_range(start, end) if held_us else _empty_connector(),
            catalyst_service.fetch_filing_deadlines(held_us, start, end) if held_us else _empty_connector(),
        )
    else:  # sin posiciones US no hay nada que cruzar con NASDAQ/EDGAR: no se les pregunta
        earnings = dividends = filings = {"status": "ok", "events": [], "errors": []}
    pending_actions = await run_in_threadpool(
        catalyst_service.pending_actions, db, start, end
    )
    events = catalyst_service.build_catalysts(
        held=held,
        held_us=held_us,
        desde=start,
        hasta=end,
        earnings=earnings["events"],
        dividends=dividends["events"],
        actions=pending_actions,
        watchlist_us=watch_us,
    )
    events = sorted(
        [*events, *filings["events"]],
        key=lambda e: (e["date"], catalyst_service._TYPE_ORDER[e["type"]], e["ticker"]),  # noqa: SLF001
    )
    return {
        "status": catalyst_service.combine_status(
            earnings["status"], dividends["status"], filings["status"]
        ),
        "desde": start.isoformat(),
        "hasta": end.isoformat(),
        "held_count": len(held),
        "watchlist_count": len(watch_us),
        "count": len(events),
        "events": events,
        "errors": earnings["errors"] + dividends["errors"] + filings["errors"],
    }
