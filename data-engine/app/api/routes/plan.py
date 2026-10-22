"""Investment plan, contributions and rebalancing drift."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.investment_plan_service import (
    PLAN_CURRENCY_UNSET,
    InvestmentPlanService,
)

router = APIRouter()


class PlanTarget(BaseModel):
    kind: str = Field(pattern="^(sector|asset_class|ticker)$")
    label: str = Field(min_length=1, max_length=120)
    target_pct: float = Field(ge=0, le=100)
    band_pct: float = Field(default=5, ge=0, le=50)


class PlanUpsertInput(BaseModel):
    monthly_contribution: float = Field(gt=0, le=1_000_000)
    # Divisa de la cuota. OMISO (cliente viejo): se preserva la registrada;
    # null EXPLICITO: queda «divisa no registrada»; valor ISO: se fija.
    monthly_contribution_currency: str | None = Field(
        default=None, min_length=3, max_length=10, pattern=r"^[A-Za-z]{3}$"
    )
    start_date: date
    horizon_years: int = Field(default=30, ge=1, le=80)
    target_allocations: list[PlanTarget] = Field(default_factory=list)


class ContributionInput(BaseModel):
    date: date
    amount: float = Field(gt=0, le=10_000_000)
    currency: str = Field(default="EUR", min_length=3, max_length=10)
    external_id: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=500)


@router.get("")
def get_plan(db: Session = Depends(get_db)) -> dict:
    service = InvestmentPlanService()
    plan = service.get_plan(db)
    if plan is None:
        return {"plan_exists": False}
    metrics = service.plan_metrics(db)
    metrics["id"] = plan.id
    return metrics


@router.put("")
def upsert_plan(payload: PlanUpsertInput, db: Session = Depends(get_db)) -> dict:
    service = InvestmentPlanService()
    if "monthly_contribution_currency" in payload.model_fields_set:
        currency = (
            payload.monthly_contribution_currency.upper()
            if payload.monthly_contribution_currency is not None
            else None
        )
    else:
        currency = PLAN_CURRENCY_UNSET
    plan = service.upsert_plan(
        db,
        monthly_contribution=Decimal(str(payload.monthly_contribution)),
        start_date=payload.start_date,
        horizon_years=payload.horizon_years,
        target_allocations=[t.model_dump() for t in payload.target_allocations],
        monthly_contribution_currency=currency,
    )
    return {
        "id": plan.id,
        "monthly_contribution": float(plan.monthly_contribution),
        "monthly_contribution_currency": (
            (plan.monthly_contribution_currency or "").upper() or None
        ),
        "start_date": plan.start_date.isoformat(),
        "horizon_years": plan.horizon_years,
        "status": plan.status,
    }


@router.get("/contributions")
def list_contributions(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    db: Session = Depends(get_db),
) -> list[dict]:
    service = InvestmentPlanService()
    return [
        {
            "id": c.id,
            "date": c.date.isoformat(),
            "amount": float(c.amount),
            "currency": c.currency,
            "note": c.note,
        }
        for c in service.list_contributions(db, limit=limit)
    ]


@router.post("/contributions", status_code=201)
def add_contribution(payload: ContributionInput, db: Session = Depends(get_db)) -> dict:
    service = InvestmentPlanService()
    try:
        contribution = service.add_contribution(
            db,
            date_=payload.date,
            amount=Decimal(str(payload.amount)),
            currency=payload.currency,
            external_id=payload.external_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": contribution.id,
        "date": contribution.date.isoformat(),
        "amount": float(contribution.amount),
        "currency": contribution.currency,
        "note": contribution.note,
    }


@router.delete("/contributions/{contribution_id}", status_code=204)
def delete_contribution(contribution_id: int, db: Session = Depends(get_db)) -> None:
    if not InvestmentPlanService().delete_contribution(db, contribution_id):
        raise HTTPException(status_code=404, detail="Contribution not found")


@router.get("/drift")
def drift_analysis(db: Session = Depends(get_db)) -> dict:
    return InvestmentPlanService().drift_analysis(db)