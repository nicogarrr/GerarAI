"""Lectura por tenant de las notas de analista estructuradas (PR 2 de 2).

Devuelve las últimas notas de las casas mejor puntuadas para el ticker, en el
orden del ranking de #4543 (error frente a sus pares en el horizonte con menor
error del propio ticker), y aparte las últimas notas de otras casas. Solo lee:
ni recoge ni llama al LLM. Sin tenant en la sesión no hay notas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.tenancy import session_tenant_id
from app.models import AnalystNote
from app.services.analyst_history_service import AnalystHistory, FirmScore, analyst_history_service
from app.services.analyst_note_service import analyst_note_service
from app.services.company_resolver import resolve_company

router = APIRouter()

#: Cuántas notas de otras casas se buscan para el bloque «otras casas».
OTHER_NOTES_SCAN = 200


class RankedFirmOut(BaseModel):
    rank: int
    firm: str
    samples: int
    median_abs_error_pct: float
    relative_error: float | None = None
    direction_hit_rate: float
    small_sample: bool = False


class AnalystNoteOut(BaseModel):
    id: int
    ticker: str
    firm: str
    firm_rank: int | None = None
    analyst: str | None = None
    note_date: date
    action: str
    rating_old: str | None = None
    rating_new: str | None = None
    pt_old: float | None = None
    pt_new: float | None = None
    currency: str | None = None
    price_at_note: float | None = None
    # (objetivo nuevo / precio de ese día − 1) × 100; None si falta alguno.
    upside_pct: float | None = None
    key_arguments: list[str] = []
    sentiment: str | None = None
    quote: str | None = None
    source_url: str | None = None
    source_type: str
    verification: Literal["verificado", "fragmento", "rumor_no_verificado"]
    estimates: dict[str, Any] = {}
    valuation: dict[str, Any] = {}
    segment_assumptions: dict[str, Any] = {}
    bull_target: float | None = None
    bear_target: float | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    catalysts: list[str] = []
    risks: list[str] = []
    changes_since_previous: str | None = None
    links: list[str] = []
    extras: dict[str, Any] = {}
    driver_refs: list[str] | None = None


class AnalystNotesView(BaseModel):
    ticker: str
    status: Literal["available", "empty", "no_tenant"]
    # ranked: las casas salen en el orden del ranking; unranked: sin ranking
    # (Yahoo no respondió o aún no hay objetivos vencidos), solo por fecha.
    ranking_status: Literal["ranked", "unranked"]
    ranking_horizon: Literal["6m", "12m"] | None = None
    ranking_note: str | None = None
    ranked_firms: list[RankedFirmOut] = []
    notes: list[AnalystNoteOut] = []
    other_notes: list[AnalystNoteOut] = []


def _f(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def note_out(row: AnalystNote, rank: int | None = None) -> AnalystNoteOut:
    pt_new, price = _f(row.pt_new), _f(row.price_at_note)
    upside = round((pt_new / price - 1.0) * 100.0, 2) if pt_new and price else None
    return AnalystNoteOut(
        id=row.id,
        ticker=row.ticker,
        firm=row.firm,
        firm_rank=rank,
        analyst=row.analyst,
        note_date=row.note_date,
        action=row.action,
        rating_old=row.rating_old,
        rating_new=row.rating_new,
        pt_old=_f(row.pt_old),
        pt_new=pt_new,
        currency=row.currency,
        price_at_note=price,
        upside_pct=upside,
        key_arguments=list(row.key_arguments or []),
        sentiment=row.sentiment,
        quote=row.quote,
        source_url=row.source_url,
        source_type=row.source_type,
        verification=row.verification,  # type: ignore[arg-type]
        estimates=dict(row.estimates or {}),
        valuation=dict(row.valuation or {}),
        segment_assumptions=dict(row.segment_assumptions or {}),
        bull_target=_f(row.bull_target),
        bear_target=_f(row.bear_target),
        bull_case=row.bull_case,
        bear_case=row.bear_case,
        catalysts=list(row.catalysts or []),
        risks=list(row.risks or []),
        changes_since_previous=row.changes_since_previous,
        links=list(row.links or []),
        extras=dict(row.extras or {}),
        driver_refs=list(row.driver_refs) if row.driver_refs is not None else None,
    )


def ranked_firms(history: AnalystHistory) -> tuple[str | None, list[FirmScore]]:
    """Casas mejor puntuadas del horizonte con menor error del ticker (#4543)."""
    if history.status != "available" or not history.horizons:
        return None, []
    order = [history.best_horizon] if history.best_horizon else []
    order += [h.horizon for h in history.horizons if h.horizon not in order]
    by_key = {h.horizon: h for h in history.horizons}
    for key in order:
        summary = by_key.get(key)  # type: ignore[arg-type]
        if summary is not None and summary.top:
            return key, list(summary.top)
    return None, []


def build_view(
    db: Session,
    tenant_id: int | None,
    ticker: str,
    history: AnalystHistory | None,
    *,
    per_firm: int,
    others: int,
) -> AnalystNotesView:
    symbol = ticker.strip().upper()
    horizon, top = ranked_firms(history) if history is not None else (None, [])
    ranking_note = None
    if not top:
        ranking_note = (
            history.note
            if history is not None and history.note
            else "Sin ranking de casas para este valor ahora: notas por fecha."
        )
    view = AnalystNotesView(
        ticker=symbol,
        status="empty",
        ranking_status="ranked" if top else "unranked",
        ranking_horizon=horizon,  # type: ignore[arg-type]
        ranking_note=ranking_note,
        ranked_firms=[
            RankedFirmOut(
                rank=i + 1,
                firm=s.firm,
                samples=s.samples,
                median_abs_error_pct=s.median_abs_error_pct,
                relative_error=s.relative_error,
                direction_hit_rate=s.direction_hit_rate,
                small_sample=s.small_sample,
            )
            for i, s in enumerate(top)
        ],
    )
    if tenant_id is None:
        view.status = "no_tenant"
        return view
    rank_of = {f.firm.lower(): f.rank for f in view.ranked_firms}
    firms = [f.firm for f in view.ranked_firms]
    best = (
        analyst_note_service.latest_by_firm(db, tenant_id, symbol, firms, per_firm=per_firm) if firms else []
    )
    view.notes = [note_out(n, rank_of.get(n.firm_key)) for n in best]
    if others > 0:
        taken = {n.id for n in best}
        recent = analyst_note_service.list_notes(db, tenant_id, symbol, limit=OTHER_NOTES_SCAN)
        rest = [n for n in recent if n.id not in taken and n.firm_key not in rank_of]
        view.other_notes = [note_out(n) for n in rest[:others]]
    if view.notes or view.other_notes:
        view.status = "available"
    return view


@router.get("/{ticker}/analyst-notes", response_model=AnalystNotesView)
async def company_analyst_notes(
    ticker: str,
    db: Session = Depends(get_db),
    per_firm: int = Query(1, ge=1, le=5),
    others: int = Query(5, ge=0, le=20),
) -> AnalystNotesView:
    """Últimas notas de analista guardadas para este tenant: primero las de las
    casas mejor puntuadas para el ticker (ranking de /analyst-history, por error
    frente a sus pares), en ese orden, y después las últimas de otras casas.
    Cada nota lleva su fuente, su tipo y su verificación (las de redes son
    «rumor_no_verificado»). Si el ranking no está disponible, las notas salen
    por fecha con ``ranking_status=unranked``. Solo lectura."""
    company = await run_in_threadpool(resolve_company, db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    history = await analyst_history_service.get(company.ticker)
    tenant_id = session_tenant_id(db)
    return await run_in_threadpool(
        build_view, db, tenant_id, company.ticker, history, per_firm=per_firm, others=others
    )
