"""Tesis v2 (nivel comité de inversión) y valoración por TIR para el accionista: solo lectura."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter()


def _company(db: Session, ticker: str):
    from app.services.company_resolver import resolve_company

    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="empresa no encontrada")
    return company


@router.get("/{ticker}/thesis-v2")
def get_thesis_v2(ticker: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """La última tesis v2 guardada (cifras del cálculo de hoy si la valoración no cambió), o solo la
    valoración por TIR si todavía no hay tesis."""
    from app.services.expert_team.thesis_v2 import read_thesis_v2
    from app.services.shareholder_irr_service import value_company

    company = _company(db, ticker)
    thesis = read_thesis_v2(db, company)
    if thesis is not None:
        return {"status": "ok", "thesis": thesis}
    return {"status": "no_thesis", "thesis": None, "valuation": value_company(db, company)}


@router.get("/{ticker}/shareholder-irr")
def get_shareholder_irr(ticker: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Valoración determinista por TIR para el accionista (escenarios, descomposición, sensibilidad, citas)."""
    from app.services.shareholder_irr_service import value_company

    return value_company(db, _company(db, ticker))
