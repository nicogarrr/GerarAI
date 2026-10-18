"""Senales insider (Form 4, SEC EDGAR, gratis). Best-effort: nunca 500 por red."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import insider_feed, insider_service

router = APIRouter()


@router.get("/signals")
def insider_signals(
    ticker: str = Query(min_length=1, max_length=20),
    cik: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=20, ge=1, le=50),
    notify: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    result = insider_service.get_signals_for_ticker(ticker, cik=cik, limit=limit, db=db)
    if notify:
        # Enganche minimo Telegram: detras de INSIDER_ALERTS_ENABLED, nunca rompe.
        result["notification"] = insider_service.maybe_notify_insider_buy(
            result.get("ticker", ticker), result.get("signals", [])
        )
    return result


@router.get("/feed")
def insider_feed_route(
    days: int = Query(default=90, ge=1, le=730),
    side: str = Query(default="all", pattern="^(all|buy|sell)$"),
    ticker: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
) -> dict:
    """Operaciones insider persistidas de todos los emisores (sin red)."""
    try:
        return insider_feed.build_feed(db, days=days, side=side, ticker=ticker, limit=limit)
    except Exception as exc:  # noqa: BLE001 - best-effort por contrato del modulo
        return {
            "status": "unavailable",
            "reason": type(exc).__name__,
            "days": days,
            "side": side,
            "count": 0,
            "transactions": [],
            "clusters": [],
            "c_suite_buys": [],
            "big_buys": [],
        }


@router.get("/filings")
def insider_filings(
    ticker: str = Query(min_length=1, max_length=20),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Filings Form 4/4-A persistidos para un ticker (lectura durable, PR-2).

    Best-effort como el resto del modulo: ante cualquier fallo degrada a
    status != ok con filings=[] (nunca 500). Las enmiendas (4/A) son filas
    propias; nunca mutan el filing original.
    """
    wanted = ticker.strip().upper()
    try:
        filings = list(
            db.scalars(
                select(InsiderFiling)
                .where(InsiderFiling.issuer_ticker == wanted)
                .order_by(desc(InsiderFiling.filing_date), desc(InsiderFiling.id))
                .limit(limit)
                .offset(offset)
            ).all()
        )
        total = (
            db.scalar(
                select(func.count())
                .select_from(InsiderFiling)
                .where(InsiderFiling.issuer_ticker == wanted)
            )
            or 0
        )
        items = []
        for filing in filings:
            txs = list(
                db.scalars(
                    select(InsiderTransaction)
                    .where(InsiderTransaction.filing_id == filing.id)
                    .order_by(InsiderTransaction.id)
                    .limit(50)
                ).all()
            )
            items.append(
                {
                    "accession_number": filing.accession_number,
                    "form": filing.form,
                    "is_amendment": filing.is_amendment,
                    "filing_date": filing.filing_date,
                    "report_date": filing.report_date,
                    "source_url": filing.source_url,
                    "transaction_count": len(txs),
                    "transactions": [
                        {
                            "insider": tx.insider,
                            "role": tx.role,
                            "officer_title": tx.officer_title,
                            "code": tx.code,
                            "is_derivative": bool(tx.is_derivative),
                            "shares": tx.shares,
                            "price": tx.price,
                            "value": tx.value,
                            "tx_date": tx.tx_date,
                            "source_url": tx.source_url,
                        }
                        for tx in txs
                    ],
                }
            )
        return {
            "ticker": wanted,
            "status": "ok",
            "count": len(items),
            # Total persistido del ticker (count = filings de esta pagina).
            "total": total,
            "filings": items,
        }
    except Exception as exc:  # noqa: BLE001 — best-effort por contrato del modulo
        return {
            "ticker": wanted,
            "status": "unavailable",
            "reason": type(exc).__name__,
            "count": 0,
            "filings": [],
        }
