"""Senales insider (Form 4, SEC EDGAR, gratis). Best-effort: nunca 500 por red."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.tenancy import tenant_filters
from app.models.entities import Company, Document, InsiderFiling, InsiderTransaction
from app.services import insider_feed, insider_operations, insider_service
from app.services.ticker_ownership_signals import ownership_signals

logger = logging.getLogger(__name__)

router = APIRouter()

# Un FPI presenta 20-F/40-F (anual) y 6-K (corriente); uno domestico, 10-K/10-Q.
_FPI_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"}
_US_PERIODIC_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def _foreign_issuer(db: Session, ticker: str) -> bool | None:
    """Estatus FPI derivado de los formularios SEC guardados, NO del domicilio:
    Chubb, Accenture o Schlumberger domicilian fuera de EE. UU. y presentan
    10-K (sus insiders SI declaran Form 4). True = solo formularios de FPI
    (20-F/40-F/6-K sin 10-K/10-Q): exento de la Seccion 16, no presenta Form 4.
    False = presenta 10-K/10-Q. None = sin filings guardados o solo formularios
    no concluyentes: nunca se afirma la causa sin dato."""
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        return None
    rows = db.scalars(
        select(Document.metadata_["form"].as_string()).where(
            Document.company_id == company.id,
            Document.source_type == "SEC",
            *tenant_filters(db, Document),
        )
    )
    forms = {str(form).strip().upper() for form in rows if form}
    if not forms:
        return None
    if forms & _US_PERIODIC_FORMS:
        return False
    if forms & _FPI_FORMS:
        return True
    return None


@router.get("/signals")
def insider_signals(
    ticker: str = Query(min_length=1, max_length=20),
    cik: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=20, ge=1, le=50),
    notify: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    result = insider_service.get_signals_for_ticker(
        ticker,
        cik=cik,
        limit=limit,
        db=db,
        tenant_id=db.info.get("tenant_id"),
    )
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


@router.get("/ownership-signals")
def insider_ownership_signals(
    ticker: str = Query(min_length=1, max_length=20),
    db: Session = Depends(get_db),
) -> dict:
    """Resumen para la tesis y la ficha: insiders (Form 4, 180 dias) + fondos 13F.

    Solo lee lo persistido (sin red). Nunca 500: un bloque que falla queda en
    ``pendiente`` y uno sin datos en ``sin_datos`` con su motivo. Si la cuenta
    aun no tiene ningun 13F sincronizado, encola UNA vez su primera descarga
    (no espera al cron del lunes) y lo dice en el detalle.
    """
    out = ownership_signals(db, ticker)
    holders = out.get("holders")
    if isinstance(holders, dict) and holders.get("reason") == "sin_sincronizar":
        if _queue_first_13f_sync(db):
            holders["sync"] = "queued"
            holders["detail"] = (
                "Tu cuenta aún no tenía los 13F de los gestores revisados: la primera descarga "
                "de la SEC ya está en marcha y tarda unos minutos. Después se actualizan cada lunes."
            )
    return out


# Primera descarga 13F por tenant: como mucho una cada 30 min por proceso; el
# actor ademas toma un lease por tenant, asi que dos peticiones no duplican trabajo.
_FIRST_13F_SYNC_COOLDOWN_SECONDS = 1800
_first_13f_sync_at: dict[str, float] = {}


def _queue_first_13f_sync(db: Session) -> bool:
    import time

    tenant = str(db.info.get("tenant_id") or "legacy")
    now = time.monotonic()
    last = _first_13f_sync_at.get(tenant)
    if last is not None and now - last < _FIRST_13F_SYNC_COOLDOWN_SECONDS:
        return True
    try:
        from app.workers.dramatiq_app import sync_investor_holdings

        sync_investor_holdings.send(tenant_id=db.info.get("tenant_id"), user_id=db.info.get("user_id"))
    except Exception:  # noqa: BLE001 - sin broker el resumen sigue respondiendo
        logger.warning("no se pudo encolar la primera sincronizacion 13F", exc_info=True)
        return False
    _first_13f_sync_at[tenant] = now
    return True


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
                .where(
                    InsiderFiling.issuer_ticker == wanted,
                    *tenant_filters(db, InsiderFiling),
                )
            )
            or 0
        )
        # Las transacciones de la pagina se cargan en UNA consulta (nunca una
        # por filing): row_number por filing conserva el cap de 50 y el orden
        # por id que tenia el bucle, sin leer de mas en filings enormes.
        filing_ids = [filing.id for filing in filings]
        txs_by_filing: dict[int, list[InsiderTransaction]] = {fid: [] for fid in filing_ids}
        if filing_ids:
            numbered = (
                select(
                    InsiderTransaction.id.label("id"),
                    func.row_number()
                    .over(partition_by=InsiderTransaction.filing_id, order_by=InsiderTransaction.id)
                    .label("rn"),
                )
                .where(InsiderTransaction.filing_id.in_(filing_ids))
                .subquery()
            )
            for tx in db.scalars(
                select(InsiderTransaction)
                .join(numbered, InsiderTransaction.id == numbered.c.id)
                .where(numbered.c.rn <= 50)
                .order_by(InsiderTransaction.filing_id, InsiderTransaction.id)
            ).all():
                txs_by_filing[tx.filing_id].append(tx)
        items = []
        for filing in filings:
            txs = txs_by_filing[filing.id]
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
                            "security_title": (tx.data_quality or {}).get("security_title")
                            if isinstance(tx.data_quality, dict)
                            else None,
                            "rule_10b5_1": bool(tx.rule_10b5_1),
                            "shares": tx.shares,
                            "price": tx.price,
                            # Como insider_feed: USD solo en Form 4; PDMR sin
                            # divisa queda None (nunca se asume).
                            "currency": ((tx.data_quality or {}).get("currency")
                            if isinstance(tx.data_quality, dict) else None)
                            or ("USD" if tx.form in ("4", "4/A") else None),
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
            # Causa real cuando esta vacio: FPI exento de Form 4 (None = se desconoce).
            "foreign_issuer": _foreign_issuer(db, wanted),
        }
    except Exception as exc:  # noqa: BLE001 — best-effort por contrato del modulo
        return {
            "ticker": wanted,
            "status": "unavailable",
            "reason": type(exc).__name__,
            "count": 0,
            "filings": [],
            "foreign_issuer": None,
        }


@router.get("/operations")
def insider_operations_route(
    days: int = Query(default=365, ge=1, le=1825),
    db: Session = Depends(get_db),
) -> dict:
    """Operaciones P/S agregadas por empresa de cartera + watchlist (persistidas)."""
    try:
        return insider_operations.insider_operations(db, days=days)
    except Exception as exc:  # noqa: BLE001 - best-effort por contrato del modulo
        return {
            "status": "unavailable",
            "reason": type(exc).__name__,
            "days": days,
            "companies": [],
            "companies_without_data": [],
            "companies_without_data_detail": [],
        }
