"""Comparacion de informes frente al ano anterior. Las lecturas nunca descargan ni analizan."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.company_resolver import resolve_company
from app.services.filing_yoy_service import comparison

router = APIRouter()


@router.get("/{ticker}/filing-yoy")
def filing_yoy(
    ticker: str, form: str = Query(default="10-K", pattern="^(10-K|10-Q)$"),
    page: int = Query(default=1, ge=1, le=200), db: Session = Depends(get_db),
) -> dict:
    """Un informe 10-K/10-Q frente al del ano anterior; ``page`` recorre informes."""
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found").detail)
    if db.info.get("tenant_id") is None:
        raise HTTPException(status_code=401, detail=ui_error(401, "research_identity_required").detail)
    return comparison(db, company.id, form, page)
