"""Eventos de resultados e índice de filings de una compañía (ficha, Fase 1)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.local_date import local_today
from app.core.ui_errors import ui_error
from app.services.async_bridge import run_from_any_context
from app.services.company_events_service import CompanyEventsService, stored_holding, stored_timeline_events
from app.services.company_resolver import resolve_company

router = APIRouter()


class NextEventOut(BaseModel):
    date: str | None = None
    hour: str | None = None
    quarter: int | None = None
    year: int | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    source: str


class EventHistoryItemOut(BaseModel):
    period: str
    quarter: int | None = None
    year: int | None = None
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    eps_surprise_percent: float | None = None
    source: str


class CompanyEventsOut(BaseModel):
    ticker: str
    company_name: str
    as_of: str
    calendar_status: str
    eps_history_status: str
    next_event: NextEventOut | None = None
    history: list[EventHistoryItemOut]
    source: str
    note: str | None = None


class FilingItemOut(BaseModel):
    form: str
    filed_at: str | None = None
    period: str | None = None
    accession: str
    url: str
    source: str


class DocumentItemOut(BaseModel):
    title: str
    source_type: str
    url: str | None = None
    published_at: str | None = None
    imported_at: str | None = None


class CompanyFilingsOut(BaseModel):
    ticker: str
    company_name: str
    as_of: str
    sec_status: str
    filings: list[FilingItemOut]
    documents: list[DocumentItemOut]
    source: str | None = None
    note: str | None = None


class TimelineEventOut(BaseModel):
    id: str
    date: str
    kind: str
    title: str
    detail: str | None = None
    source: str
    source_url: str | None = None


class TimelineHoldingOut(BaseModel):
    average_cost: float | None = None
    first_buy_date: str | None = None


class CompanyTimelineEventsOut(BaseModel):
    ticker: str
    currency: str | None = None
    desde: str
    hasta: str
    holding: TimelineHoldingOut | None = None
    events: list[TimelineEventOut]
    source: str


TIMELINE_MAX_DAYS = 366 * 30


@router.get("/{ticker}/events/timeline", response_model=CompanyTimelineEventsOut)
def get_company_timeline_events(
    ticker: str,
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """Eventos guardados para el gráfico de precio (resultados, ex-dividendo, filings, insiders, noticias).

    Lee solo la base de datos: no llama a Finnhub, GDELT, la SEC ni Yahoo. Todo evento lleva fecha y fuente.
    """
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_ticker", ticker=ticker).detail)
    end = hasta or local_today()  # día de Madrid, no el UTC del servidor
    start = desde or end - timedelta(days=183)
    if start > end:
        raise HTTPException(status_code=400, detail="desde no puede ser posterior a hasta")
    if (end - start).days > TIMELINE_MAX_DAYS:
        start = end - timedelta(days=TIMELINE_MAX_DAYS)
    return {
        "ticker": company.ticker,
        "currency": company.currency,
        "desde": start.isoformat(),
        "hasta": end.isoformat(),
        "holding": stored_holding(db, company),
        "events": stored_timeline_events(db, company, start, end),
        "source": "Datos guardados en GerarAI",
    }


@router.get("/{ticker}/events", response_model=CompanyEventsOut)
async def get_company_events(ticker: str, db: Session = Depends(get_db)) -> Any:
    def _events() -> Any:
        company = resolve_company(db, ticker)
        if company is None:
            raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_ticker", ticker=ticker).detail)
        return run_from_any_context(CompanyEventsService(db).get_events(company))

    # resolve + servicio (sqlalchemy sincrono entre awaits): hilo del pool.
    return await run_in_threadpool(_events)


@router.get("/{ticker}/filings", response_model=CompanyFilingsOut)
async def get_company_filings(ticker: str, db: Session = Depends(get_db)) -> Any:
    def _filings() -> Any:
        company = resolve_company(db, ticker)
        if company is None:
            raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_ticker", ticker=ticker).detail)
        return run_from_any_context(CompanyEventsService(db).get_filings(company))

    return await run_in_threadpool(_filings)
