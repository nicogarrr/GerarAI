"""Authenticated data inventory and public short-position snapshots."""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.models import Company
from app.services.async_bridge import run_from_any_context
from app.services.company_resolver import resolve_company
from app.services.data_health_service import read_inventory
from app.services.short_positions_service import read_shorts, refresh_shorts

router = APIRouter()


@router.get("")
def data_health(db: Session = Depends(get_db)) -> dict:
    return read_inventory(db)


def _company(db: Session, ticker: str) -> Company:
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_registered").detail)
    return company


@router.get("/shorts/{ticker}")
def shorts(ticker: str = Path(min_length=1, max_length=20), db: Session = Depends(get_db)) -> dict:
    return read_shorts(db, _company(db, ticker))


@router.post("/shorts/{ticker}/refresh")
async def shorts_refresh(ticker: str = Path(min_length=1, max_length=20), db: Session = Depends(get_db)) -> dict:
    def _refresh() -> dict:
        return run_from_any_context(refresh_shorts(db, _company(db, ticker)))

    # _company y el refresh (sqlalchemy + proveedor entre awaits): hilo del pool.
    return await run_in_threadpool(_refresh)
