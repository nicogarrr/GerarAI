from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

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
