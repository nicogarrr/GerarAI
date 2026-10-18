from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import ValuationResponse
from app.services.company_resolver import resolve_company
from app.services.historical_valuation_service import HistoricalValuationService
from app.services.valuation_service import ValuationService

router = APIRouter()


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
