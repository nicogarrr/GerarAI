"""Institutional ownership endpoints (SEC Form 13F, reviewed managers only,
y SC 13D/13G de titulares >5% ya ingeridos)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.schemas.api import ManagerChangesOut, ManagerHoldingsOut, OwnershipManagersOut
from app.services import schedule13dg_monitor, schedule13dg_service
from app.services.manager_holding_ingestion_service import (
    LIMITATIONS,
    REVIEWED_MANAGERS,
    ManagerHoldingIngestionService,
)

router = APIRouter()


@router.get("/managers", response_model=OwnershipManagersOut)
def list_managers() -> dict:
    """Reviewed managers available for 13F sync (exact CIK, never inferred)."""
    return {
        "managers": [{"cik": cik, "name": name} for cik, name in REVIEWED_MANAGERS.items()],
        "limitations": LIMITATIONS,
    }


@router.post("/managers/sync-async", status_code=202)
def sync_managers_async(db: Session = Depends(get_db)) -> dict:
    """Encola el actor semanal de carteras para este tenant y responde de inmediato.

    La primera carga de una cuenta nueva no espera al cron del lunes 04:20 ni
    bloquea la peticion durante los minutos que tarda la descarga de la SEC:
    el actor `sync_investor_holdings` hace el trabajo con el contexto de
    tenant del solicitante.
    """
    from app.workers.dramatiq_app import sync_investor_holdings

    message = sync_investor_holdings.send(
        tenant_id=db.info.get("tenant_id"),
        user_id=db.info.get("user_id"),
    )
    return {"status": "queued", "broker_message_id": str(message.message_id)}


@router.post("/managers/sync")
def sync_managers(cik: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Sync the latest 13F report for one reviewed manager or all of them."""
    service = ManagerHoldingIngestionService()
    if cik:
        return service.sync_manager(db, cik=cik)
    return service.sync_all(db)


@router.get("/managers/{cik}/changes", response_model=ManagerChangesOut)
def manager_changes(cik: str, db: Session = Depends(get_db)) -> dict:
    """Quarter-over-quarter 13F position changes for a reviewed manager."""
    return ManagerHoldingIngestionService().changes(db, cik=cik)


@router.get("/managers/{cik}/holdings", response_model=ManagerHoldingsOut)
def manager_holdings(cik: str, db: Session = Depends(get_db)) -> dict:
    """Latest 13F report holdings for a reviewed manager, as filed."""
    from app.services.investor_autosync import maybe_autosync_holdings

    maybe_autosync_holdings(db)
    return ManagerHoldingIngestionService().latest_holdings(db, cik=cik)


@router.get("/schedule-13dg")
def schedule_13dg(
    ticker: str = Query(min_length=1, max_length=20),
    db: Session = Depends(get_db),
) -> dict:
    """Filings SC 13D/13G persistidos del ticker; campos no parseados = N/D."""
    return schedule13dg_service.filings_for_ticker(db, ticker)


@router.post("/schedule-13dg/sync")
def schedule_13dg_sync(
    ticker: str = Query(min_length=1, max_length=20),
    db: Session = Depends(get_db),
) -> dict:
    """Ingesta acotada de SC 13D/13G para UN ticker SEGUIDO.

    "Seguido" = watchlist o cartera del tenant (misma definicion que el
    monitor diario); cualquier otro ticker se rechaza con 404 en lugar de
    gastar peticiones a la SEC en un emisor que el usuario no sigue.
    """
    from app.services.insider_monitor import watchlist_tickers

    tenant_id = db.info.get("tenant_id")
    normalized = ticker.strip().upper()
    if normalized not in watchlist_tickers(db, tenant_id):
        raise HTTPException(
            status_code=404,
            detail=ui_error(404, "ownership_scope_limited", ticker=normalized).detail,
        )
    return schedule13dg_monitor.scan(
        db,
        tenant_id=tenant_id,
        tickers=[normalized],
    )
