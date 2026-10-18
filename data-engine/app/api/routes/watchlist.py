from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Company, FinancialFact, MarketPrice, WatchItem
from app.services.tracked_analysis import enqueue_tracked_analysis, tracked_statuses

router = APIRouter()


class WatchItemCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")
    company: str | None = Field(default=None, max_length=255)


def _payload(item: WatchItem) -> dict:
    return {
        "id": item.id,
        "symbol": item.symbol,
        "company": item.company,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("")
def list_watchlist(db: Session = Depends(get_db)) -> list[dict]:
    """Watch items of the active tenant, most recently added first.

    Tenant scoping is applied implicitly by the session (see database.py):
    rows are only visible when their tenant_id matches the signed identity.
    """
    items = db.scalars(select(WatchItem).order_by(desc(WatchItem.created_at))).all()
    states = tracked_statuses(db, [item.symbol for item in items])
    return [{**_payload(item), "analysis": states.get(item.symbol)} for item in items]


@router.post("", status_code=201)
def upsert_watch_item(
    payload: WatchItemCreate, db: Session = Depends(get_db)
) -> dict:
    """Add a symbol to the watchlist, or update its label if it exists."""
    symbol = payload.symbol.strip().upper()
    item = db.scalar(select(WatchItem).where(WatchItem.symbol == symbol))
    created = item is None
    if item is None:
        item = WatchItem(symbol=symbol, company=payload.company)
        db.add(item)
    elif payload.company is not None:
        item.company = payload.company
    db.commit()
    db.refresh(item)
    if created:
        try:
            enqueue_tracked_analysis(db, symbol)
        except Exception:
            db.rollback()  # Following succeeds even if the analysis outbox fails.
    return _payload(item)


@router.delete("/{symbol}", status_code=204)
def delete_watch_item(symbol: str, db: Session = Depends(get_db)) -> None:
    item = db.scalar(
        select(WatchItem).where(WatchItem.symbol == symbol.strip().upper())
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watch item not found")
    db.delete(item)
    db.commit()

@router.get("/metrics/{symbol}")
def watchlist_metrics(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Market cap y PER de respaldo para emisoras sin cobertura del
    proveedor US (QA AENA/ASML): market_cap del proveedor o derivado
    (precio x acciones, servicio derived_market_cap) y PER = ultimo cierre
    / EPS diluido del ultimo ejercicio anual. Nulo honesto cuando no hay
    base: nunca se fabrica el numero.
    """
    from datetime import date, timedelta

    company = db.scalar(select(Company).where(Company.ticker == symbol.upper()))
    if company is None:
        return {"market_cap": None, "per": None, "currency": None, "sources": []}

    today = date.today()
    sources: list[str] = []

    cap_row = db.execute(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id,
               FinancialFact.metric == "market_cap")
        .order_by(desc(FinancialFact.is_reported), desc(FinancialFact.period))
        .limit(1)
    ).scalar_one_or_none()
    market_cap = float(cap_row.value) if cap_row is not None else None
    if cap_row is not None:
        sources.append(
            f"Capitalización: {cap_row.source_type}"
            + ("" if cap_row.is_reported else " (derivada: precio x acciones)"))

    price_row = db.execute(
        select(MarketPrice)
        .where(MarketPrice.company_id == company.id,
               MarketPrice.date >= today - timedelta(days=7),
               MarketPrice.close.isnot(None), MarketPrice.close > 0)
        .order_by(desc(MarketPrice.date)).limit(1)
    ).scalar_one_or_none()
    eps_row = db.execute(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id,
               FinancialFact.metric.in_(["eps_diluted", "eps_basic"]),
               FinancialFact.fiscal_quarter == "FY",
               FinancialFact.value > 0)
        .order_by(desc(FinancialFact.fiscal_year)).limit(1)
    ).scalar_one_or_none()
    per = None
    if price_row is not None and eps_row is not None:
        from app.services.split_adjustment import (
            cumulative_split_factor_after,
            period_end_date,
            split_events_by_company,
        )

        # El cierre es de hoy: EPS en acciones actuales o el PER sale
        # inflado por el factor de cualquier split posterior al ejercicio.
        split_factor = cumulative_split_factor_after(
            split_events_by_company(db, [company.id]).get(company.id, []),
            period_end_date(eps_row.period),
        )
        per = float(price_row.close) / (float(eps_row.value) / float(split_factor))
        source = (f"PER: cierre {price_row.date.isoformat()} / "
                  f"{eps_row.metric} FY{eps_row.fiscal_year} ({eps_row.source_type})")
        if split_factor != 1:
            source += (", EPS ajustado por split acumulado x"
                  f"{format(split_factor.normalize(), "f")}")
        sources.append(source)

    return {"market_cap": market_cap, "per": per,
            "currency": company.currency, "sources": sources}
