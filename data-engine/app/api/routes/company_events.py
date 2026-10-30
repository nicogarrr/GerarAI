"""Eventos de resultados e índice de filings de una compañía (ficha, Fase 1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.async_bridge import run_from_any_context
from app.services.company_events_service import CompanyEventsService
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
