"""Informe tipo analista: GET /companies/{ticker}/analyst-report (solo lectura)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.analyst_report import build_company_report
from app.services.company_resolver import resolve_company

router = APIRouter()


@router.get("/{ticker}/analyst-report")
def analyst_report(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Datos de mercado (cierre, volumen medio, acciones, capitalización, EV) y cifras
    reales de ingresos y EBITDA por ejercicio y trimestre para el «Informe» de la
    ficha. Solo lo guardado: un dato sin fuente sale vacío con su motivo."""
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_dot").detail)
    return build_company_report(db, company)
