"""Inversores: tabla fija + resumen de cartera 13F (solo gestores revisados)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.api import (
    InvestorPortfolioOut,
    InvestorsListOut,
    MostBoughtOut,
    PortfolioOverlapOut,
)
from app.services.investor_videos import investor_videos
from app.services.investors import investor_detail, list_investors, most_bought
from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService

router = APIRouter()


@router.get("", response_model=InvestorsListOut, response_model_exclude_unset=True)
def investors(db: Session = Depends(get_db)) -> dict:
    """Lista de inversores con resumen de su ultimo 13F (o 'Sin datos')."""
    return list_investors(db)


@router.get("/most-bought", response_model=MostBoughtOut, response_model_exclude_unset=True)
def most_bought_route(db: Session = Depends(get_db)) -> dict:
    """Acciones mas compradas por los gestores revisados (13F, trimestre vs anterior)."""
    return most_bought(db)


@router.get("/portfolio-overlap", response_model=PortfolioOverlapOut, response_model_exclude_unset=True)
def overlap_route(db: Session = Depends(get_db)) -> dict:
    from app.services.investor_overlap import portfolio_overlap

    return portfolio_overlap(db)


@router.get("/holders/{ticker}")
def holders_by_ticker_route(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Gestores revisados que declaran el ticker en su último 13F (vista inversa)."""
    from app.services.investor_overlap import holders_by_ticker

    result = holders_by_ticker(db, ticker)
    if result is None:
        raise HTTPException(status_code=404, detail="company not found")
    return result


@router.get("/{slug}/portfolio", response_model=InvestorPortfolioOut, response_model_exclude_unset=True)
def investor_portfolio_route(slug: str, db: Session = Depends(get_db)) -> dict:
    """Posiciones, pesos y ultimos movimientos, cada dato con etiqueta y fecha."""
    from app.services.investor_portfolio import investor_portfolio

    portfolio = investor_portfolio(db, slug)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="investor not found")
    return portfolio


@router.get("/{slug}")
def investor(slug: str, db: Session = Depends(get_db)) -> dict:
    """Ficha de un inversor: posiciones del ultimo 13F y cambios trimestrales."""
    detail = investor_detail(db, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail="investor not found")
    if detail["cik"]:
        detail["changes"] = ManagerHoldingIngestionService().changes(db, cik=detail["cik"])
    detail["videos"] = investor_videos(slug)
    return detail
