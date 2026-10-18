from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import WatchItem
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