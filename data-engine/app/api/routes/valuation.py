from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models import Company
from app.schemas import ValuationResponse
from app.services.company_resolver import resolve_company
from app.services.fair_value_service import (
    PRECEDENCE_TEXT,
    resolve_fair_value_cached,
    resolve_fair_values,
)
from app.services.historical_valuation_service import HistoricalValuationService
from app.services.valuation_service import ValuationService
from app.services.valuation_summary import build_summaries
from app.valuation.what_to_believe import WhatToBelieve, build_what_to_believe

router = APIRouter()


@router.get("/summary")
def valuation_summaries(
    tickers: str = Query(..., max_length=1500, description="CSV de tickers, máximo 60"),
    db: Session = Depends(get_db),
) -> dict:
    """Una lectura por lotes; sin recálculos, llamadas a proveedores ni escrituras."""
    wanted = list(dict.fromkeys(t.strip().upper() for t in tickers.split(",") if t.strip()))[:60]
    companies = list(db.scalars(select(Company).where(Company.ticker.in_(wanted))).all())
    return {"items": build_summaries(db, companies)}


# Va ANTES de "/{ticker}": si no, «fair-value» se resolvería como ticker.
@router.get("/fair-value")
def fair_values(
    tickers: str = Query(..., description="CSV de tickers, máx. 60"),
    db: Session = Depends(get_db),
) -> dict:
    """Valor justo único por ticker (tesis o motor), con su procedencia.

    Por lotes no se recalcula el motor: se usa su última valoración persistida.
    """
    wanted = list(dict.fromkeys(t.strip().upper() for t in tickers.split(",") if t.strip()))[:60]
    companies = db.scalars(select(Company).where(Company.ticker.in_(wanted))).all()
    readings = resolve_fair_values(db, companies)
    return {
        "precedence": PRECEDENCE_TEXT,
        "items": {reading["ticker"]: reading for reading in readings.values()},
    }


@router.get("/{ticker}/fair-value")
def fair_value(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Valor justo único de un ticker; recalcula el motor si la tesis no basta.

    El recalculo pasa por cache Redis (FAIR_VALUE_LIVE_CACHE_TTL_SECONDS):
    el sondeo de oportunidades de Inicio y la ficha piden el mismo ticker
    muchas veces al dia y el motor no cambia hasta la proxima ingesta.
    """
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {**resolve_fair_value_cached(db, company, live=True), "precedence": PRECEDENCE_TEXT}


@router.get("/{ticker}", response_model=ValuationResponse)
def valuation(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return ValuationService().value_company(db, company)


@router.get("/{ticker}/what-to-believe", response_model=WhatToBelieve)
async def what_to_believe(ticker: str, db: Session = Depends(get_db)) -> WhatToBelieve:
    """«Qué hace falta creer» para justificar el precio con el DCF de la empresa.

    Solo lee: la valoración vigente (misma que /api/valuation/{ticker}, con su
    WACC tal y como lo resolvió el motor), el WACC implícito al precio y al
    consenso simple de analistas (si está en la misma divisa), el crecimiento
    del DCF inverso del motor y el contraste con un múltiplo de salida. Los
    métodos que no son un DCF FCFF responden «no aplica» con el motivo.
    """
    company = await run_in_threadpool(resolve_company, db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    valuation_result = await run_in_threadpool(ValuationService().value_company, db, company)
    consensus_price = None
    consensus_currency = None
    consensus_source = None
    if valuation_result.get("status") in ("ok", "partial"):
        from app.services.analyst_targets_service import analyst_targets_service

        targets = await analyst_targets_service.get(company.ticker)
        if targets.status == "available" and targets.consensus is not None:
            consensus_price = targets.consensus.mean
            consensus_currency = targets.currency
            consensus_source = targets.source
    return build_what_to_believe(
        company.ticker,
        valuation_result,
        consensus_price=consensus_price,
        consensus_currency=consensus_currency,
        consensus_source=consensus_source,
    )


@router.get("/{ticker}/history")
def historical_valuation(
    ticker: str,
    years: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return HistoricalValuationService().build(db, company, years=years)
