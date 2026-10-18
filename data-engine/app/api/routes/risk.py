from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.services.async_bridge import run_from_any_context
from app.services.connectors import short_interest
from app.services.risk_service import RiskService

router = APIRouter()


@router.get("/dashboard")
def risk_dashboard(db: Session = Depends(get_db)) -> dict:
    return RiskService().dashboard(db)


async def market_stress_signals(ticker: str | None = None) -> dict:
    """Senales de estres de mercado (VIX + posicion corta FINRA).

    El conector degrada a ``unavailable`` cuando los vendors gratuitos no
    responden; nunca se fabrican senales.
    """
    return await short_interest.market_stress_report(ticker)


@router.get("/market-stress")
async def market_stress(ticker: str | None = None) -> dict:
    return await market_stress_signals(ticker)


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
            raise HTTPException(status_code=422, detail="Ticker no válido")
    # build() mezcla descargas y sqlalchemy sincronos entre sus awaits: todo
    # el servicio corre en un hilo del pool, con su corutina puenteado.
    return await run_in_threadpool(
        lambda: run_from_any_context(HistoricalStressService().build(db, ticker=ticker))
    )
