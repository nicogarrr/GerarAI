"""Calendario macro oficial y resúmenes de 8-K de compañías seguidas."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.local_date import local_today
from app.core.ui_errors import ui_error
from app.services import macro_calendar_service
from app.services.eight_k_digest import eight_k_digest

router = APIRouter()


@router.get("/events")
async def macro_events(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=50),
) -> dict:
    """Eventos macro oficiales (FOMC, IPC, empleo...). Por defecto, 60 días.

    Una fuente caída marca ``status="partial"``/``"unavailable"``; nunca 5xx
    por fallo del proveedor y nunca fechas inventadas.
    """
    start = desde or local_today()  # día de Madrid, como /calendar
    try:
        end = hasta or (start + timedelta(days=60))
    except OverflowError as exc:
        # 9999-12-31 + 60 días no existe: error del cliente, no un 500.
        raise HTTPException(status_code=400, detail="Fecha fuera de rango") from exc
    try:
        result = await macro_calendar_service.get_macro_events(start, end)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Fecha fuera de rango") from exc
    offset = (page - 1) * page_size
    return {**result, "page": page, "page_size": page_size,
            "events": result["events"][offset:offset + page_size]}


@router.get("/8k")
def eight_k(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    if db.info.get("tenant_id") is None:
        raise HTTPException(status_code=401, detail=ui_error(401, "research_identity_required").detail)
    return eight_k_digest(db, page=page, page_size=page_size)
