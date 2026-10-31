"""Radar ProPicks+DCA (lectura): oportunidades del universo escaneado.

GET-only: la escritura la hace el job acotado (propicks_radar_job), nunca
una petición de lectura. Datos públicos de precio por empresa; el filtro
"fuera de cartera y watchlist" usa los símbolos del tenant firmado.

Cada fila separa el mes CONFIRMADO del mes EN FORMACIÓN, con fecha, precio,
fuente y versión de fórmula. Las empresas con evaluación inválida no son
oportunidades: cuentan en ``coverage``, no en los items. Un snapshot con
más de STALE_SCAN_DAYS días sin corrida nueva tampoco es vigente: cuenta en
``coverage.stale``. La cobertura es global: no cambia con los filtros de la
lista (el tamaño filtrado está en ``total``).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.tenancy import tenant_filters
from app.models import Company, Position, WatchItem
from app.services.propicks_dca_radar import PAGE_SIZE, page_candidates
from app.services.propicks_radar_job import universe_company_ids
from app.services.propicks_radar_store import latest_public_signals

router = APIRouter()

# Misma regla de vigencia que el núcleo (evaluate_candidate): más de 3 días
# sin corrida nueva y el snapshot deja de presentarse como oportunidad.
STALE_SCAN_DAYS = 3


def _tracked_symbols(db: Session) -> set[str]:
    watched = db.scalars(select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))).all()
    held = db.scalars(
        select(Company.ticker)
        .join(Position, Position.company_id == Company.id)
        .where(Position.quantity > 0, *tenant_filters(db, Position))
    ).all()
    return {str(s).upper() for s in (*watched, *held)}


@router.post("/radar/scan", status_code=202)
def enqueue_radar_scan(db: Session = Depends(get_db)) -> dict:
    """Encola un lote del barrido (ops/sync manual; el diario lo da el scheduler).

    El job es resumible por cursor: reintentar no duplica snapshots del día.
    """
    from app.workers.dramatiq_app import propicks_radar_scan

    tenant_id = db.info.get("tenant_id")
    user_id = db.info.get("user_id")
    # MEDIDO: el actor exige tenant_id y user_id (sesion de tenant); encolar
    # sin ellos crea un mensaje que siempre muere en el worker. Mejor 400 aqui.
    if tenant_id is None or not user_id:
        raise HTTPException(
            status_code=400,
            detail="El barrido manual exige contexto de tenant firmado.",
        )
    message = propicks_radar_scan.send(tenant_id=tenant_id, user_id=user_id)
    return {"status": "queued", "broker_message_id": str(message.message_id)}


@router.get("/radar/opportunities")
def list_radar_opportunities(
    page: int = Query(default=1, ge=1),
    level: int | None = Query(default=None),
    sector: str | None = Query(default=None),
    outside_tracked: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    as_of = date.today()
    signals = latest_public_signals(db, as_of=as_of)
    company_ids = [s["company_id"] for s in signals]
    companies = {
        c.id: c
        for c in db.scalars(select(Company).where(Company.id.in_(company_ids))).all()
    } if company_ids else {}

    rows: list[dict] = []
    invalid = 0
    stale = 0
    for signal in signals:
        company = companies.get(signal["company_id"])
        if company is None:
            continue
        payload = signal["payload"]
        if payload.get("status") != "ok":
            invalid += 1
            continue
        scan_day = date.fromisoformat(signal["scan_date"])
        if (as_of - scan_day).days > STALE_SCAN_DAYS:
            # Scan antiguo sin corrida nueva: no es una oportunidad vigente.
            stale += 1
            continue
        current = payload.get("current") or {}
        confirmed = payload.get("confirmed") or {}
        zone = current.get("zone") or {}
        rows.append({
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "currency": company.currency,
            "level": current.get("level"),
            "level_label": zone.get("label"),
            "status": current.get("status"),
            "signal_date": current.get("signal_date"),
            "close": current.get("close"),
            "price_date": payload.get("price_date"),
            "source": payload.get("source"),
            "price_verified": payload.get("price_verified"),
            "confirmed_level": confirmed.get("level"),
            "confirmed_period": confirmed.get("period"),
            "clear_price_signal": payload.get("clear_price_signal"),
            "change": signal["change"],
            "formula_version": payload.get("formula_version"),
            "scan_date": signal["scan_date"],
        })

    # Cobertura GLOBAL del universo: se calcula antes de los filtros y no
    # cambia con ellos (el tamaño filtrado está en ``total``).
    coverage = {
        "universe": len(universe_company_ids(db)),
        "evaluated": len(signals),
        "ok": len(rows),
        "invalid": invalid,
        "stale": stale,
    }

    if sector:
        rows = [r for r in rows if r["sector"] == sector]
    tracked = _tracked_symbols(db) if outside_tracked else None
    counts_by_level: dict[str, int] = {}
    eligible_rows = [r for r in rows if tracked is None or r["ticker"].upper() not in tracked]
    for row in eligible_rows:
        key = str(row["level"])
        counts_by_level[key] = counts_by_level.get(key, 0) + 1
    paged = page_candidates(rows, page=page, level=level, outside_tracked=tracked)

    return {
        "as_of": as_of.isoformat(),
        "page": paged["page"],
        "page_size": PAGE_SIZE,
        "total": paged["total"],
        "has_more": paged["has_more"],
        "items": paged["items"],
        "counts_by_level": counts_by_level,
        "sectors": sorted({r["sector"] for r in rows if r["sector"]}),
        "coverage": coverage,
    }
