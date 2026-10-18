"""Corporate actions: splits, reverse splits, ticker changes."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models import Company, DividendRecord, Position
from app.services.async_bridge import run_from_any_context
from app.services.corporate_actions_service import CorporateActionService
from app.services.split_ingestion_service import SplitIngestionService

router = APIRouter()


class CorporateActionInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    action_type: str = Field(pattern="^(split|reverse_split|ticker_change|merger|spin_off)$")
    effective_date: date
    ratio: float = Field(gt=0, le=1_000_000)
    description: str = Field(default="", max_length=500)
    apply_now: bool = Field(default=True)


def _payload(
    action, ticker: str | None, first_trade_date=None, has_holding: bool = True
) -> dict:
    return {
        "id": action.id,
        "ticker": ticker,
        "action_type": action.action_type,
        "effective_date": action.effective_date.isoformat(),
        "ratio": float(action.ratio),
        "description": action.description,
        "applied": action.applied,
        "applied_at": action.applied_at.isoformat() if action.applied_at else None,
        # Split anterior a la primera operacion: ya reflejado, sin boton Aplicar.
        "historical": (not action.applied)
        and CorporateActionService.is_historical(action, first_trade_date),
        # Empresa fuera de cartera (sin posicion ni operaciones): nada que ajustar.
        "no_position": (not action.applied) and not has_holding,
    }


def _declared_dividends(db: Session, *, days: int = 120) -> list[dict]:
    """Dividendos DECLARADOS (ingestados del proveedor) de posiciones abiertas.

    Solo lectura: no se aplican al libro (el cobro se registra a mano). Cada
    fila lleva fuente y fechas reales del registro; nada proyectado.
    """
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(DividendRecord, Company)
        .join(Company, Company.id == DividendRecord.company_id)
        .where(
            DividendRecord.ex_date >= since,
            DividendRecord.company_id.in_(
                select(Position.company_id).where(Position.quantity > 0)
            ),
        )
        .order_by(DividendRecord.ex_date.desc(), Company.ticker)
    ).all()
    out = []
    for record, company in rows:
        pay = f" · pago {record.pay_date.isoformat()}" if record.pay_date else ""
        out.append(
            {
                "id": None,
                "ticker": company.ticker,
                "action_type": "dividend",
                "effective_date": record.ex_date.isoformat(),
                "ratio": None,
                "description": (
                    f"Dividendo de {record.amount.normalize():f} {record.currency} por acción"
                    f"{pay} · fuente {record.source}"
                ),
                "applied": None,
                "applied_at": None,
                "historical": False,
                "no_position": False,
                "declared": True,
                "source": record.source,
            }
        )
    return out


@router.post("/splits/sync")
async def sync_portfolio_splits(db: Session = Depends(get_db)) -> dict:
    """Ingest historical splits for held companies from the data provider.

    Rows arrive UNAPPLIED with source provenance; apply them explicitly via
    /corporate-actions/{id}/apply after verifying against issuer/exchange
    notices. Provider failures mark the symbol unavailable.
    """
    # La ingesta mezcla sqlalchemy y el proveedor entre sus awaits: hilo del
    # pool con la corutina puenteado, no el event loop.
    return await run_in_threadpool(
        lambda: run_from_any_context(SplitIngestionService().sync_portfolio(db))
    )


@router.get("")
def list_actions(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    db: Session = Depends(get_db),
) -> list[dict]:
    service = CorporateActionService()
    actions = service.list_actions(db, limit=limit)
    # Lote: tickers en 1 query (anti N+1 de db.get por acción).
    company_ids = {action.company_id for action in actions if action.company_id}
    tickers = (
        {
            row[0]: row[1]
            for row in db.execute(
                select(Company.id, Company.ticker).where(Company.id.in_(company_ids))
            ).all()
        }
        if company_ids
        else {}
    )
    firsts = service.first_trade_dates(db, company_ids)
    held = service.companies_with_holding(db, company_ids)
    payload = [
        _payload(
            action,
            tickers.get(action.company_id),
            firsts.get(action.company_id),
            action.company_id in held,
        )
        for action in actions
    ]
    return payload + _declared_dividends(db)


@router.post("", status_code=201)
def create_action(payload: CorporateActionInput, db: Session = Depends(get_db)) -> dict:
    service = CorporateActionService()
    try:
        action = service.create_action(
            db,
            ticker=payload.ticker,
            action_type=payload.action_type,
            effective_date=payload.effective_date,
            ratio=Decimal(str(payload.ratio)),
            description=payload.description,
            apply_now=payload.apply_now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    company = db.get(Company, action.company_id)
    return _payload(action, company.ticker if company else None)


@router.post("/{action_id}/apply")
def apply_action(action_id: int, db: Session = Depends(get_db)) -> dict:
    service = CorporateActionService()
    try:
        action = service.apply_action(db, action_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    company = db.get(Company, action.company_id)
    return _payload(action, company.ticker if company else None)


@router.delete("/{action_id}", status_code=204)
def delete_action(action_id: int, db: Session = Depends(get_db)) -> None:
    service = CorporateActionService()
    try:
        if not service.delete_action(db, action_id):
            raise HTTPException(status_code=404, detail="Corporate action not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc