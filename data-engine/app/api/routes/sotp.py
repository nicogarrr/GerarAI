"""Desglose por partes (SOTP) editable: GET/PUT/DELETE /valuation/{ticker}/sotp."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.schemas.sotp import SotpModelIn
from app.services.company_resolver import resolve_company
from app.services.user_sotp_service import UserSotpService

router = APIRouter()


def _context(db: Session, ticker: str):
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise HTTPException(status_code=403, detail=ui_error(401, "user_context_required").detail)
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_dot").detail)
    return company, int(tenant)


@router.get("/{ticker}/sotp")
def get_user_sotp(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Desglose por partes del usuario (o el borrador de ejemplo), con su aritmética,
    escenarios, sensibilidad y la tasa base medida. Supuestos del usuario: no es el
    valor justo de GerarAI."""
    company, tenant = _context(db, ticker)
    return UserSotpService().read(db, company, tenant)


@router.put("/{ticker}/sotp")
def put_user_sotp(ticker: str, model: SotpModelIn, db: Session = Depends(get_db)) -> dict:
    """Guarda una versión nueva del desglose (la anterior queda en el histórico)."""
    company, tenant = _context(db, ticker)
    try:
        return UserSotpService().save(db, company, tenant, model.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{ticker}/sotp", status_code=204)
def delete_user_sotp(ticker: str, db: Session = Depends(get_db)) -> None:
    company, tenant = _context(db, ticker)
    UserSotpService().delete(db, company, tenant)
