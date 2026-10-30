"""Escenarios bull/base/bear sobre la ultima tesis guardada, sin recalculo."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.company_resolver import resolve_company
from app.services.thesis_scenario_service import ThesisScenarioService

router = APIRouter()


@router.get("/{ticker}/thesis-scenarios")
def get_thesis_scenarios(ticker: str, db: Session = Depends(get_db)) -> dict:
    if db.info.get("tenant_id") is None:
        raise HTTPException(status_code=403, detail=ui_error(401, "user_context_required").detail)
    with db.no_autoflush:
        company = resolve_company(db, ticker)
        if company is None:
            raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_dot").detail)
        return ThesisScenarioService().read(db, company)
