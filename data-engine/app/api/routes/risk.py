from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.async_bridge import run_from_any_context
from app.services.risk_service import RiskService

router = APIRouter()


@router.get("/dashboard")
def risk_dashboard(db: Session = Depends(get_db)) -> dict:
    return RiskService().dashboard(db)


@router.get("/historical-stress")
async def historical_stress(
    ticker: str | None = None, db: Session = Depends(get_db)
) -> dict:
    from fastapi import HTTPException

    from app.services.historical_stress_service import HistoricalStressService

    if ticker is not None:
        import re

        ticker = ticker.strip().upper()
        if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", ticker):
            raise HTTPException(status_code=422, detail=ui_error(400, "invalid_ticker").detail)
    # build() mezcla descargas y sqlalchemy sincronos entre sus awaits: todo
    # el servicio corre en un hilo del pool, con su corutina puenteado.
    return await run_in_threadpool(
        lambda: run_from_any_context(HistoricalStressService().build(db, ticker=ticker))
    )
