from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.llm_proposal_runner import QuotaExceeded, generate_proposal
from app.services.llm_proposal_service import ProposalRejected
from app.services.paper_calibration_service import calibration
from app.services.paper_cost_service import current_assumptions
from app.services.paper_trading_service import (
    UnknownProposalCurrency,
    close_position,
    create_proposal,
    refresh_trades,
    scoreboard,
    trade_out,
)

router = APIRouter()


@router.post("/proposals", status_code=201)
def propose(body: PaperProposal, db: Session = Depends(get_db)) -> dict:
    try:
        return trade_out(create_proposal(db, body))
    except UnknownProposalCurrency as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Clave de propuesta duplicada o en conflicto") from exc


class LLMProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, max_length=20)


@router.post("/llm-proposals", status_code=201)
async def llm_propose(body: LLMProposalRequest, db: Session = Depends(get_db)) -> dict:
    """Genera UNA propuesta simulada con el LLM, validada y con cuota diaria. No ejecuta nada."""
    try:
        return trade_out(await generate_proposal(db, body.ticker))
    except QuotaExceeded as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ProposalRejected as exc:
        db.rollback()
        status = 503 if exc.reason in {"llm_deshabilitado", "presupuesto_agotado", "modelo_no_gratuito", "modelo_no_verificable", "fallback_no_gratuito"} else 422
        raise HTTPException(status_code=status, detail=f"Propuesta rechazada: {exc.reason}") from exc
    except UnknownProposalCurrency as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Clave de propuesta duplicada o en conflicto") from exc


@router.get("/proposals")
def proposals(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(PaperTrade).order_by(PaperTrade.id.desc()).limit(limit)).all()
    return [trade_out(row) for row in rows]


@router.get("/scoreboard")
def score(db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(PaperTrade)).all())
    return {**scoreboard(rows), "calibracion": calibration(rows)}


@router.post("/refresh", status_code=202)
def refresh(db: Session = Depends(get_db)) -> dict:
    from app.workers.dramatiq_app import refresh_paper_trades

    message = refresh_paper_trades.send(db.info.get("tenant_id"), db.info.get("user_id"))
    return {"status": "queued", "message_id": str(message.message_id)}


@router.post("/feed", status_code=202)
def feed(db: Session = Depends(get_db)) -> dict:
    """Encola un lote de propuestas LLM (INFERIDO). Comparte la cuota diaria con /llm-proposals."""
    from app.workers.dramatiq_app import propose_paper_trades

    message = propose_paper_trades.send(db.info.get("tenant_id"), db.info.get("user_id"))
    return {"status": "queued", "message_id": str(message.message_id)}


@router.post("/proposals/{proposal_id}/close")
def close(proposal_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(PaperTrade).where(PaperTrade.id == proposal_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    if row.status == "closed":
        return trade_out(row)
    # Drop the read transaction before provider work. refresh_trades locks only
    # during application; the final close revalidates under its own row lock.
    db.commit()
    refresh_trades(db, only_id=proposal_id)
    db.refresh(row, with_for_update=True)
    if row.status == "closed":
        return trade_out(row)
    out = trade_out(row)
    if row.status != "open" or out["quote_status"] != "available" or row.mark_at is None or row.mark_price is None:
        raise HTTPException(status_code=409, detail="Sin precio real reciente para cerrar")
    if row.entry_at == row.mark_at:
        raise HTTPException(status_code=409, detail="Falta una cotización posterior a la entrada")
    close_position(row, row.mark_price, row.mark_at, "manual", current_assumptions())
    db.commit()
    return trade_out(row, datetime.now(UTC))
