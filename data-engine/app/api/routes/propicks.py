"""ProPicks funnel (big-data stage): deterministic runs over the whole
research universe, persisted and diffable. LLM selection lands in F3."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Company, MarketPrice, ProPickCandidate, ProPickRun
from app.services.propicks_funnel_service import execute_run, run_funnel
from app.services.propicks_gems_service import find_gems

router = APIRouter()


class ProPickRunOut(BaseModel):
    id: int
    as_of: datetime
    status: str
    funnel_version: str
    universe_size: int
    passed_count: int
    top_n: int
    duration_ms: int
    params: dict

    class Config:
        from_attributes = True


class ProPickCandidateOut(BaseModel):
    company_id: int
    ticker: str
    name: str
    sector: str
    currency: str
    passed: bool
    rank: int | None
    score: float | None
    failed_gates: list[str]
    metrics: dict
    coverage: dict
    current_price: float | None = None
    price_as_of: date | None = None


class ProPickRunDetailOut(ProPickRunOut):
    candidates: list[ProPickCandidateOut]


def _run_out(run: ProPickRun) -> ProPickRunOut:
    return ProPickRunOut.model_validate(run)


@router.post("/prices/refresh", status_code=202)
def refresh_prices(db: Session = Depends(get_db)) -> dict:
    """Encola el job F2 (precios yfinance + momentum del top-40 del ultimo run).

    Ops/sync manual; el scheduler lo corre a diario tras el cierre US."""
    from app.workers.dramatiq_app import refresh_propicks_prices

    message = refresh_propicks_prices.send(
        tenant_id=db.info.get("tenant_id"),
        user_id=db.info.get("user_id"),
    )
    return {"status": "queued", "broker_message_id": str(message.message_id)}


@router.post("/runs", response_model=ProPickRunOut, status_code=201)
def create_run(
    top_n: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ProPickRunOut:
    """Execute the funnel now and persist the result (idempotent per call:
    every call is a new run row; history is the point)."""
    return _run_out(execute_run(db, top_n=top_n))


@router.get("/runs", response_model=list[ProPickRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ProPickRunOut]:
    rows = db.scalars(
        select(ProPickRun).order_by(ProPickRun.as_of.desc()).limit(limit)
    ).all()
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=ProPickRunDetailOut)
def get_run(
    run_id: int,
    only_passed: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> ProPickRunDetailOut:
    run = db.scalar(select(ProPickRun).where(ProPickRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="propick run not found")
    stmt = select(ProPickCandidate, Company).join(
        Company, Company.id == ProPickCandidate.company_id
    )
    stmt = stmt.where(ProPickCandidate.run_id == run_id)
    if only_passed:
        stmt = stmt.where(ProPickCandidate.passed.is_(True))
    stmt = stmt.order_by(
        ProPickCandidate.rank.asc().nulls_last(), ProPickCandidate.score.desc()
    )
    rows = db.execute(stmt).all()
    # Ultimo precio persistido por empresa (F2/yfinance); None honesto si aun no hay.
    latest_prices: dict[int, MarketPrice] = {}
    price_rows = db.scalars(
        select(MarketPrice)
        .where(MarketPrice.company_id.in_([c.company_id for c, _ in rows]))
        .order_by(MarketPrice.date.desc())
    ).all()
    for price in price_rows:
        latest_prices.setdefault(price.company_id, price)
    out = ProPickRunDetailOut(**ProPickRunOut.model_validate(run).model_dump(), candidates=[])
    out.candidates = [
        ProPickCandidateOut(
            company_id=c.company_id,
            ticker=co.ticker,
            name=co.name,
            sector=co.sector,
            currency=co.currency,
            passed=c.passed,
            rank=c.rank,
            score=c.score,
            failed_gates=c.failed_gates,
            metrics=c.metrics,
            coverage=c.coverage,
            current_price=(
                float(latest_prices[c.company_id].close)
                if c.company_id in latest_prices and latest_prices[c.company_id].close is not None
                else None
            ),
            price_as_of=(
                latest_prices[c.company_id].date if c.company_id in latest_prices else None
            ),
        )
        for c, co in rows
    ]
    return out


class GemOut(BaseModel):
    ticker: str
    name: str
    score: float
    market_cap: float
    reasons: list[dict]


@router.get("/gems", response_model=list[GemOut])
def list_gems(
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[GemOut]:
    """Joyas ocultas: calidad (embudo) + valor + insiders + 13F, con fuente y fecha por dato."""
    results, _ = run_funnel(db, top_n=limit)
    return [
        GemOut(ticker=g.ticker, name=g.name, score=g.score, market_cap=g.market_cap, reasons=g.reasons)
        for g in find_gems(db, results, limit=limit)
    ]


@router.post("/snapshots", status_code=201)
def freeze_snapshot(db: Session = Depends(get_db)) -> dict:
    """Congela el snapshot del mes (idempotente: el primero del mes gana)."""
    from app.services.propicks_snapshot_service import freeze_monthly_snapshot

    row = freeze_monthly_snapshot(db)
    if row is None:
        raise HTTPException(status_code=409, detail="ninguna empresa pasa el embudo: no se congela un mes vacio")
    return {"month": row.month, "as_of": row.as_of, "passed_count": row.passed_count}


@router.get("/snapshots")
def list_snapshots(db: Session = Depends(get_db)) -> list[dict]:
    from app.models.propick_snapshot import PropickSnapshot

    rows = db.scalars(select(PropickSnapshot).order_by(PropickSnapshot.month.desc())).all()
    return [
        {"month": r.month, "as_of": r.as_of, "passed_count": r.passed_count, "picks": len(r.payload.get("picks", []))}
        for r in rows
    ]


@router.post("/review")
async def review_gems(
    limit: int = Query(default=20, ge=1, le=40),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Revision del LLM sobre la shortlist de joyas. Si el LLM falla o no es
    gratuito, cada pick vuelve marcado sin_revision_ia con su score determinista."""
    from datetime import UTC

    from app.llm import create_llm_provider
    from app.services.budget import BudgetController
    from app.services.llm_proposal_runner import paid_model_risk
    from app.services.propicks_review_service import (
        NO_REVIEW,
        ReviewCandidate,
        log_reviews,
        review_shortlist,
    )

    results, _ = run_funnel(db, top_n=limit)
    gems = find_gems(db, results, limit=limit)
    cands = [
        ReviewCandidate(
            g.ticker, g.name, g.score,
            [{"key": r["key"], "value": r["value"], "source": r["source"]} for r in g.reasons],
            g.price, g.price_date,
        )
        for g in gems
    ]
    provider = create_llm_provider()
    usable = provider.name != "disabled" and paid_model_risk(provider) is None
    budget = BudgetController()
    models: list[str] = []

    def _record(resp) -> None:
        models.append(resp.model)
        cost = budget.estimate_cost_eur(resp.model, resp.usage.input_tokens, resp.usage.output_tokens)
        budget.record(db, resp.model, "propicks_review", cost, resp.usage.total_tokens)

    if usable and cands and budget.can_spend(db, 0.05):
        db.commit()
        reviews = await review_shortlist(provider, cands, on_response=_record)
    else:
        from app.services.propicks_review_service import Review

        reviews = [Review(c.ticker, NO_REVIEW, reject_reason="llm_no_disponible") for c in cands]
    log_reviews(db, cands, reviews, model=models[-1] if models else None, now=datetime.now(UTC))
    by_t = {r.ticker: r for r in reviews}
    return [
        {
            "ticker": g.ticker, "name": g.name, "score": g.score, "reasons": g.reasons,
            "review_status": by_t[g.ticker].status,
            "decision": by_t[g.ticker].decision,
            "thesis": by_t[g.ticker].thesis,
            "risks": by_t[g.ticker].risks,
            "invalidation": by_t[g.ticker].invalidation,
            "confidence": by_t[g.ticker].confidence,
            "veto_reason": by_t[g.ticker].veto_reason,
        }
        for g in gems
    ]


@router.get("/review/brier")
def review_brier(db: Session = Depends(get_db)) -> dict:
    from app.services.propicks_review_service import brier_report, evaluate_outcomes

    evaluate_outcomes(db)
    return brier_report(db)
