"""Operaciones declaradas por politicos (PTR de la Camara de EE. UU.). Solo lee lo guardado."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import politician_trades

router = APIRouter()


@router.get("")
def politicians_list(
    chamber: str = Query(default="all", pattern="^(all|house|senate|executive)$"),
    party: str | None = Query(default=None, pattern="^[DRI]$"),
    sort: str = Query(default="trades", pattern="^(trades|late|recent|on_time)$"),
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Una ficha por politico: operaciones, tickers, ultima operacion, % a tiempo,
    presentadas tarde (>45 dias) y mas de 30 dias tarde, tickers mas operados."""
    return politician_trades.politicians(db, chamber=chamber, party=party, sort=sort, query=q, limit=limit, offset=offset)


@router.get("/ticker/{ticker}")
def politicians_ticker(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Quien opero el ticker, con cada operacion enlazada a su PTR."""
    if not 1 <= len(ticker) <= 20:
        raise HTTPException(status_code=422, detail="ticker no valido")
    return politician_trades.ticker_trades(db, ticker)


@router.get("/member/{member_key}")
def politicians_member(member_key: str, db: Session = Depends(get_db)) -> dict:
    if len(member_key) > 120:
        raise HTTPException(status_code=422, detail="clave no valida")
    detail = politician_trades.member_detail(db, member_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="politico sin declaraciones guardadas")
    return detail
