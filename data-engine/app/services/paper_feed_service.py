"""Alimentacion del paper book con propuestas LLM (item 5), con cuota compartida.

Elige candidatos entre las empresas del tenant con titulares materiales recientes
y pide UNA propuesta por ticker a `generate_proposal` (que valida contra una
cotizacion fresca, registra presupuesto en cada respuesta y libera la sesion
antes de la red). Todo es INFERIDO y simulado: no ejecuta nada.

La cuota diaria (`DAILY_QUOTA`) es la MISMA que usa el endpoint manual
POST /paper-trading/llm-proposals: `save_within_quota` cuenta por tenant y dia
UTC, de modo que este lote y las llamadas manuales se reparten un unico tope.
Este modulo no define ni amplia ningun tope propio.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Company, NewsEvent
from app.models.paper_trading import PaperTrade
from app.services.llm_proposal_runner import (
    DAILY_QUOTA,
    NEWS_WINDOW,
    QuotaExceeded,
    _utc,
    generate_proposal,
    todays_llm_proposals,
)
from app.services.llm_proposal_service import ProposalRejected

logger = logging.getLogger(__name__)

MIN_MATERIALITY = 5  # escala 1-10 de news_events.materiality_score
ATTEMPTS_PER_QUOTA_SLOT = 2  # rechazos (sin cotizacion, validador) no consumen cuota
PAUSE_SECONDS = 2.0
# Un rechazo de estos tipos afecta a TODO el lote: se corta, no se insiste.
_BATCH_STOPPERS = {
    "llm_deshabilitado",
    "presupuesto_agotado",
    "modelo_no_gratuito",
    "modelo_no_verificable",
    "fallback_no_gratuito",
}

Generate = Callable[..., Awaitable[PaperTrade]]
Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


def select_candidates(db: Session, now: datetime, limit: int) -> list[str]:
    """Tickers del tenant con titulares materiales recientes, mas materiales primero.

    Excluye los que ya tienen una propuesta LLM viva (pending/open) o creada hoy.
    Solo lee escalares: la sesion queda libre de objetos antes de la red.
    """
    since = _utc(now) - NEWS_WINDOW
    ranked = db.execute(
        select(
            Company.ticker,
            func.max(NewsEvent.materiality_score).label("peak"),
            func.count(NewsEvent.id).label("n"),
        )
        .join(NewsEvent, NewsEvent.company_id == Company.id)
        .where(NewsEvent.date >= since,
            NewsEvent.date <= _utc(now),  # nunca evidencia con fecha futura
            NewsEvent.materiality_score >= MIN_MATERIALITY,
            *tenant_filters(db, NewsEvent))
        .group_by(Company.ticker)
        .order_by(func.max(NewsEvent.materiality_score).desc(), func.count(NewsEvent.id).desc(), Company.ticker)
    ).all()
    start = _utc(now).replace(hour=0, minute=0, second=0, microsecond=0)
    blocked = {
        ticker
        for (ticker,) in db.execute(
            select(PaperTrade.ticker).where(
                (PaperTrade.author == "LLM") | PaperTrade.proposal_key.like("llm:%"),
                (PaperTrade.status.in_(("pending", "open"))) | (PaperTrade.created_at >= start),
                *tenant_filters(db, PaperTrade),
            )
        ).all()
    }
    return [row.ticker for row in ranked if row.ticker.upper() not in {b.upper() for b in blocked}][:limit]


async def run_feed(
    db: Session,
    *,
    clock: Clock = _now,
    generate: Generate = generate_proposal,
    pause: float = PAUSE_SECONDS,
) -> dict[str, Any]:
    # El corte inicial solo sirve para elegir candidatos; cada llamada usa el reloj
    # ACTUAL, porque tras las pausas una cotizacion fresca seria "futura" para un
    # `now` congelado y se rechazaria como vieja.
    now = clock()
    remaining = DAILY_QUOTA - todays_llm_proposals(db, now)
    outcome: dict[str, Any] = {
        "etiqueta": "INFERIDO",
        "cuota_diaria": DAILY_QUOTA,
        "cuota_restante_al_inicio": max(remaining, 0),
        "guardadas": [],
        "omitidas": [],
        "status": "ok",
    }
    if remaining <= 0:
        db.commit()
        outcome["status"] = "cuota_agotada"
        return outcome
    candidates = select_candidates(db, now, remaining * ATTEMPTS_PER_QUOTA_SLOT)
    db.commit()  # sesion libre antes de cualquier cotizacion o LLM
    if not candidates:
        outcome["status"] = "sin_candidatos"
        return outcome
    for index, ticker in enumerate(candidates):
        if len(outcome["guardadas"]) >= remaining:
            break
        if index:
            await asyncio.sleep(pause)
        try:
            row = await generate(db, ticker, clock=clock)
            outcome["guardadas"].append({"ticker": ticker, "id": row.id})
        except QuotaExceeded:
            db.rollback()
            outcome["status"] = "cuota_agotada"
            break
        except ProposalRejected as exc:
            db.rollback()
            outcome["omitidas"].append({"ticker": ticker, "motivo": exc.reason})
            if exc.reason in _BATCH_STOPPERS:
                outcome["status"] = exc.reason
                break
        except (ValueError, IntegrityError):
            db.rollback()
            outcome["omitidas"].append({"ticker": ticker, "motivo": "conflicto_clave"})
        except Exception as exc:  # noqa: BLE001 - un ticker roto no tumba el lote
            db.rollback()
            logger.warning("paper_feed %s fallo: %s", ticker, type(exc).__name__)
            outcome["omitidas"].append({"ticker": ticker, "motivo": f"error_{type(exc).__name__}"})
    if outcome["status"] == "ok" and not outcome["guardadas"]:
        outcome["status"] = "sin_propuestas"
    return outcome
