"""Investment plan, contributions and rebalancing drift."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.api import SavingsProjectionOut
from app.services.investment_plan_service import (
    PLAN_CURRENCY_UNSET,
    ContributionConflict,
    InvestmentPlanService,
    plan_currency_enforced,
)
from app.valuation.currency import is_currency_code

router = APIRouter()


class PlanTarget(BaseModel):
    kind: str = Field(pattern="^(sector|asset_class|ticker)$")
    label: str = Field(min_length=1, max_length=120)
    target_pct: float = Field(ge=0, le=100)
    band_pct: float = Field(default=5, ge=0, le=50)

    @model_validator(mode="after")
    def _normalize_label(self) -> PlanTarget:
        # «nvda» y «NVDA» son el mismo ticker: se guarda en mayusculas para que
        # objetivos, desviacion, reparto y enlaces lo muestren igual.
        label = self.label.strip()
        if not label:
            raise ValueError("La etiqueta del objetivo no puede estar vacía.")
        self.label = label.upper() if self.kind == "ticker" else label
        return self


def _iso_currency(value: str | None) -> str | None:
    # «QQQ» o «NaN» pasaban el patron de tres letras y el plan quedaba
    # «incompleto» para siempre: ningun tipo de cambio los convierte.
    if value is not None and not is_currency_code(value, allow_subunits=False):
        raise ValueError("currency must be an ISO 4217 code such as EUR or USD")
    return value


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

    _currency_is_iso = field_validator("monthly_contribution_currency")(_iso_currency)

    @model_validator(mode="after")
    def _targets_fit_in_each_dimension(self) -> PlanUpsertInput:
        # Cada dimension (ticker, sector, clase de activo) describe la MISMA
        # cartera: 60 % MSFT + 60 % NVDA no cabe. El formulario ya lo impide;
        # la API no debe guardar un plan que el reparto y la desviacion leerian
        # como pesos imposibles (espejo de lib/plan/target-totals.ts).
        totals: dict[str, float] = {}
        for target in self.target_allocations:
            totals[target.kind] = totals.get(target.kind, 0.0) + target.target_pct
        for kind, total in totals.items():
            if total > 100 + 1e-9:
                raise ValueError(
                    f"Los objetivos de tipo {kind} suman {total:g} %: no pueden superar el 100 %."
                )
        return self


class ContributionInput(BaseModel):
    date: date
    amount: float = Field(gt=0, le=10_000_000)
    # ISO 4217: «EURO» o «€» nunca tendrian tipo de cambio y dejarian el plan
    # «incompleto» para siempre; «eur» se guarda como «EUR».
    currency: str = Field(default="EUR", pattern=r"^[A-Za-z]{3}$")
    external_id: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=500)

    _currency_is_iso = field_validator("currency")(_iso_currency)


@router.get("")
def get_plan(db: Session = Depends(get_db)) -> dict:
    service = InvestmentPlanService()
    plan = service.get_plan(db)
    if plan is None:
        return {
            "plan_exists": False,
            "currency_contract_enabled": plan_currency_enforced(),
        }
    metrics = service.plan_metrics(db)
    metrics["id"] = plan.id
    return metrics


@router.put("")
def upsert_plan(payload: PlanUpsertInput, db: Session = Depends(get_db)) -> dict:
    service = InvestmentPlanService()
    if (
        "monthly_contribution_currency" in payload.model_fields_set
        and not plan_currency_enforced()
    ):
        # Capability apagada: ignorar la divisa en silencio guardaria un
        # plan que el cliente cree en esa divisa y se calcularia como base.
        raise HTTPException(
            status_code=409,
            detail="plan_currency_contract_disabled",
        )
    if "monthly_contribution_currency" not in payload.model_fields_set:
        # Cliente viejo: su formulario entiende el importe como EUR. Si el plan
        # tiene registrada otra divisa, cambiar el importe sin divisa
        # guardaria «300» creyendo euros bajo la etiqueta USD: se rechaza.
        existing = service.get_plan(db)
        registered = (
            (existing.monthly_contribution_currency or "").upper() if existing else ""
        )
        if (
            registered
            and registered != "EUR"
            and Decimal(str(payload.monthly_contribution)) != existing.monthly_contribution
        ):
            raise HTTPException(
                status_code=409,
                detail="plan_currency_required_for_amount_change",
            )
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
    except ContributionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.get("/contribution-split")
def contribution_split(db: Session = Depends(get_db)) -> dict:
    """Reparto de la aportacion de este mes ponderado por nivel DCA."""
    from app.services.plan_contribution_split import build_contribution_split

    return build_contribution_split(db)


@router.get("/drift")
def drift_analysis(db: Session = Depends(get_db)) -> dict:
    return InvestmentPlanService().drift_analysis(db)

@router.get("/savings-projection", response_model=SavingsProjectionOut)
def savings_projection(
    db: Session = Depends(get_db),
    monthly: Annotated[float | None, Query(ge=0, le=1_000_000)] = None,
    years: Annotated[int | None, Query(ge=1, le=80)] = None,
    # Misma regla que la divisa del plan: «QQQ», «NaN» o «GBp» (peniques, que
    # se subian a «GBP») no rotulan una vista previa como si fueran divisas.
    currency: Annotated[
        str | None, Query(pattern=r"^[A-Za-z]{3}$"), AfterValidator(_iso_currency)
    ] = None,
    annual_return: Annotated[float | None, Query(ge=-0.99, le=1)] = None,
    dividend_yield: Annotated[float, Query(ge=0, le=0.5)] = 0.03,
    inflation: Annotated[float, Query(ge=-0.99, le=1)] = 0.02,
) -> dict:
    """Read-only preview or canonical illustration of the existing savings plan."""
    from app.services.savings_projection import savings_contract
    return savings_contract(db, monthly=monthly, years=years, currency=currency,
        annual_return=annual_return, dividend_yield=dividend_yield, inflation=inflation)
