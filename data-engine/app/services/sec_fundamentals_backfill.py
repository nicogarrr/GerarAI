"""Backfill programado de fundamentales SEC para el universo US.

Medido en prod (19 oct 2026, data-health): 164 de 2.135 companias del
universo tienen fundamentales SEC. Causa estructural: la ingesta SEC solo se
disparaba por demanda (ver la ficha, generar una tesis); no habia ningun job
programado para el resto del universo US (ESEF si tiene re-ingesta semanal y
Finnhub profiles backfill diario presupuestado). Este servicio cierra ese
carril con el mismo patron: chunk presupuestado por ejecucion y marcas de
reanudacion persistidas.

Dos reglas anti-atasco (objecion del auditor, demostrada: con >100 no-SEC
delante en orden de id el lote procesaba siempre las mismas y la US del
fondo no llegaba nunca):

1. Candidatas prefiltradas por la guarda de identidad ``sec_eligible``
   (CIK propio o USD+bolsa US): las no-SEC ni siquiera cuentan para el
   presupuesto del lote.
2. Cada intento (ok, skipped o error) deja marca persistida y las
   candidatas se ordenan por ultimo intento ascendente (las nunca
   intentadas primero): una compania saltada o fallida no se reintenta
   hasta RETRY_ATTEMPT_AFTER, y el lote rota en vez de quedarse clavado.

La marca de intento es una fila ``ConnectorState`` propia
(connector="sec-fundamentals-backfill", feed_url="companyfacts"), NO un
Document: un Document interno contaminaria el conteo de cobertura del
thesis graph, el agrupado por source_type y el listado de fuentes de la
API (objecion del auditor). ConnectorState es la tabla que ya usan otros
conectores para su estado de reanudacion (shorts, insider monitor).

Marca de frescura de hechos = Document "SEC XBRL facts - TICKER" (el que
escribe la propia ingesta; <7d fresco no se repite). Coste: 0 EUR (SEC
companyfacts/submissions, acceso justo <=10 req/s; aqui ~1 compania cada
PAUSE_S segundos, ordenes de magnitud por debajo).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, ConnectorState
from app.services.data_health_service import utc
from app.services.tracked_financial_refresh import (
    last_sec_refresh,
    refresh_free_financials,
    sec_eligible,
)

logger = logging.getLogger(__name__)

PAUSE_S = 0.5
FRESH_FOR = timedelta(days=7)
RETRY_ATTEMPT_AFTER = timedelta(days=3)
CONNECTOR = "sec-fundamentals-backfill"
FEED = "companyfacts"

Refresher = Callable[[Session, Company], Awaitable[dict]]


def _attempt_states(db: Session) -> dict[int, ConnectorState]:
    """Marcas de intento del tenant actual, indexadas por company_id."""
    tenant = db.info.get("tenant_id")
    stmt = select(ConnectorState).where(
        ConnectorState.connector == CONNECTOR,
        ConnectorState.tenant_id.is_(tenant) if tenant is None
        else ConnectorState.tenant_id == tenant,
    )
    return {s.company_id: s for s in db.scalars(stmt).all()
            if s.company_id is not None}


def _attempt_state(db: Session, company: Company) -> ConnectorState | None:
    return _attempt_states(db).get(company.id)


def _record_attempt(db: Session, company: Company, *, now: datetime,
                    status: str, reason: str | None) -> None:
    state = db.scalar(select(ConnectorState).where(
        ConnectorState.connector == CONNECTOR,
        ConnectorState.company_id == company.id,
        ConnectorState.feed_url == FEED,
    ))
    if state is None:
        state = ConnectorState(
            tenant_id=db.info.get("tenant_id"),
            connector=CONNECTOR,
            company_id=company.id,
            feed_url=FEED,
        )
        db.add(state)
    state.last_started_at = now
    if status == "ok":
        state.last_success_at = now
        state.consecutive_errors = 0
        state.last_error = None
    elif status == "error":
        state.consecutive_errors = (state.consecutive_errors or 0) + 1
        state.last_error = reason
    state.metadata_ = {
        **(state.metadata_ or {}),
        "last_attempt_at": now.isoformat(),
        "status": status,
        "reason": reason,
    }
    # Commit por compania: la marca sobrevive al rollback de una compania
    # posterior que falle, y una ejecucion abortada no pierde los intentos
    # ya registrados (cada uno es independiente).
    db.commit()


def _candidate_ids(db: Session, *, now: datetime, limit: int) -> list[int]:
    """Universo US sin hechos SEC frescos, rotando por ultimo intento."""
    attempts = _attempt_states(db)
    rows: list[tuple[datetime, int]] = []
    never: list[int] = []
    for company in db.scalars(select(Company).order_by(Company.id)).all():
        if not sec_eligible(company):
            continue
        refreshed = last_sec_refresh(db, company)
        if refreshed is not None and now - refreshed < FRESH_FOR:
            continue
        state = attempts.get(company.id)
        attempted = utc(state.last_started_at) if state is not None else None
        if attempted is not None:
            if now - attempted < RETRY_ATTEMPT_AFTER:
                continue
            rows.append((attempted, company.id))
        else:
            never.append(company.id)
    rows.sort()
    # Nunca intentadas primero (orden id estable), luego las mas antiguas.
    return (never + [cid for _ts, cid in rows])[:limit]


async def backfill_sec_fundamentals_async(
    db: Session,
    *,
    max_companies: int = 100,
    refresher: Refresher = refresh_free_financials,
    pause_s: float = PAUSE_S,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresca fundamentales SEC de hasta `max_companies` companias US.

    Los resultados por compania son los de ``refresh_free_financials``:
    ok / skipped(emisor_no_sec, actualizado_ultimas_24h) / error. Los fallos
    quedan contados y marcados, nunca inventados.
    """
    now = now or datetime.now(UTC)
    stats: dict[str, Any] = {"ok": 0, "skipped": 0, "error": 0, "reasons": {}}
    ids = _candidate_ids(db, now=now, limit=max_companies)
    for company_id in ids:
        company = db.get(Company, company_id)
        if company is None:
            continue
        try:
            result = await refresher(db, company)
        except Exception as exc:  # noqa: BLE001 - una compania no frena el lote
            db.rollback()
            logger.warning("sec backfill %s: %s", company.ticker, exc)
            result = {"status": "error", "reason": "excepcion"}
        status = str(result.get("status", "error"))
        if status not in ("ok", "skipped", "error"):
            status = "error"
        stats[status] += 1
        reason = result.get("reason")
        _record_attempt(db, company, now=now, status=status,
                        reason=str(reason) if reason else None)
        if reason:
            stats["reasons"][str(reason)] = stats["reasons"].get(str(reason), 0) + 1
        if pause_s:
            await asyncio.sleep(pause_s)
    stats["candidatas"] = len(ids)
    return stats


def backfill_sec_fundamentals(
    db: Session,
    *,
    max_companies: int = 100,
    refresher: Refresher = refresh_free_financials,
) -> dict[str, Any]:
    from app.services.async_bridge import run_from_any_context

    return run_from_any_context(
        backfill_sec_fundamentals_async(db, max_companies=max_companies, refresher=refresher)
    )
