"""Adaptador BD -> contrato propicks-unified-v1 (solo lectura, por tenant).

No calcula cifras nuevas: lee el último run completado del tenant, el
veredicto quality-v1, el último precio persistido, P/B valuation-v1 y el
snapshot DCA público, y deja que ``propicks_unified`` fije estados.
Identidad: solo existe Company.id => ``company:{id}`` provisional (unverified)
hasta que el resolver de instrumentos (Mercados) aporte identidad verificada.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    CalculatedMetric,
    Company,
    MarketPrice,
    Position,
    ProPickCandidate,
    ProPickRun,
    WatchItem,
)
from app.schemas.propicks_unified import UnifiedResult
from app.services.propicks_radar_quality import quality_for_companies
from app.services.propicks_radar_store import latest_public_signals
from app.services.propicks_unified import PickInput, build_result, classify_fetch
from app.services.valuation_metrics_service import METRIC_PB, METRIC_VERSION, STATUS_DISAGREE

logger = logging.getLogger(__name__)

QUALITY_POLICY_VERSION = "quality-v1"


def _latest_run(db: Session) -> ProPickRun | None:
    return db.scalar(
        select(ProPickRun)
        .where(ProPickRun.status == "completed", *tenant_filters(db, ProPickRun))
        .order_by(ProPickRun.as_of.desc(), ProPickRun.id.desc())
        .limit(1)
    )


def _latest_prices(db: Session, company_ids: list[int]) -> dict[int, MarketPrice]:
    numbered = (
        select(
            MarketPrice.id.label("id"),
            func.row_number()
            .over(
                partition_by=MarketPrice.company_id,
                order_by=(MarketPrice.date.desc().nullslast(), desc(MarketPrice.id)),
            )
            .label("rn"),
        )
        .where(MarketPrice.company_id.in_(company_ids), MarketPrice.close.is_not(None))
        .subquery("unified_latest_price")
    )
    rows = db.scalars(
        select(MarketPrice).join(numbered, numbered.c.id == MarketPrice.id).where(numbered.c.rn == 1)
    ).all()
    return {r.company_id: r for r in rows}


def _latest_pb(db: Session, company_ids: list[int]) -> dict[int, CalculatedMetric]:
    rows = db.scalars(
        select(CalculatedMetric)
        .where(
            CalculatedMetric.company_id.in_(company_ids),
            CalculatedMetric.metric == METRIC_PB,
            CalculatedMetric.definition_version == METRIC_VERSION,
            *tenant_filters(db, CalculatedMetric),
        )
        .order_by(CalculatedMetric.period.desc())
    ).all()
    out: dict[int, CalculatedMetric] = {}
    for row in rows:
        out.setdefault(row.company_id, row)
    return out


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _dca_inputs(db: Session, company_ids: set[int], as_of: date) -> dict[int, dict]:
    signals = latest_public_signals(db, as_of=as_of)
    return {s["company_id"]: s for s in signals if s["company_id"] in company_ids}


def load_unified(db: Session, *, as_of: date, limit: int = 200) -> UnifiedResult:
    run = _latest_run(db)
    if run is None:
        return build_result([], run_id=None, as_of=as_of, universe=None)
    rows = db.execute(
        select(ProPickCandidate, Company)
        .join(Company, Company.id == ProPickCandidate.company_id)
        .where(ProPickCandidate.run_id == run.id, *tenant_filters(db, ProPickCandidate))
        .order_by(
            ProPickCandidate.passed.desc(),
            ProPickCandidate.score.desc().nulls_last(),
            Company.ticker,
        )
        .limit(limit)
    ).all()
    ids = [c.company_id for c, _ in rows]
    tickers = {co.ticker for _, co in rows}
    verdicts = quality_for_companies(db, ids, as_of=as_of) if ids else {}
    prices = _latest_prices(db, ids) if ids else {}
    pbs = _latest_pb(db, ids) if ids else {}
    held = set(
        db.scalars(
            select(Position.company_id).where(
                Position.company_id.in_(ids), Position.quantity != 0, *tenant_filters(db, Position)
            )
        ).all()
    ) if ids else set()
    watched = set(
        db.scalars(
            select(WatchItem.symbol).where(WatchItem.symbol.in_(tickers), *tenant_filters(db, WatchItem))
        ).all()
    ) if tickers else set()

    blocks = {}
    dca: dict[int, dict] = {}
    if ids:
        try:
            with db.begin_nested():
                dca = _dca_inputs(db, set(ids), as_of)
        except Exception as exc:
            logger.warning("propicks unified: DCA no disponible (%s)", type(exc).__name__)
            blocks["dca"] = classify_fetch(exc=exc, as_of=as_of)

    inputs: list[PickInput] = []
    for cand, co in rows:
        verdict = verdicts.get(cand.company_id)
        price = prices.get(cand.company_id)
        pb = pbs.get(cand.company_id)
        pb_day = _parse_day(pb.period) if pb is not None else None
        snap = dca.get(cand.company_id)
        payload = (snap or {}).get("payload") or {}
        dca_ok = payload.get("status") == "ok"
        current = payload.get("current") or {}
        confirmed = payload.get("confirmed") or {}
        delisted = co.delisted_at is not None and co.delisted_at.date() <= as_of
        inputs.append(
            PickInput(
                ticker=co.ticker, name=co.name, exchange=co.exchange, currency=co.currency,
                company_id=co.id,
                listing_status="delisted" if delisted else "unknown",
                quality_passed=verdict["passed"] if verdict else None,
                # El score solo se etiqueta con la política del run que lo produjo.
                quality_score=cand.score if run.funnel_version else None,
                quality_policy_version=QUALITY_POLICY_VERSION,
                quality_score_policy_version=(
                    run.funnel_version if cand.score is not None and run.funnel_version else None
                ),
                quality_reasons=tuple(verdict["reasons"]) if verdict else (),
                price=float(price.close) if price is not None and price.close is not None else None,
                price_as_of=price.date if price is not None else None,
                price_to_book=float(pb.value) if pb is not None and pb.value is not None else None,
                valuation_as_of=pb_day,
                valuation_formula_version=METRIC_VERSION if pb is not None else None,
                disputed_fields=("priceToBook",) if pb is not None and pb.status == STATUS_DISAGREE else (),
                field_statuses=(
                    (("priceToBook", pb.status or "unverified"),)
                    if pb is not None and pb.status != STATUS_DISAGREE else ()
                ),
                dca_status=(("ok" if dca_ok else "invalid") if snap else None),
                dca_level=current.get("level") if dca_ok else None,
                dca_period_state=current.get("status") if dca_ok else None,
                dca_confirmed_level=confirmed.get("level") if dca_ok else None,
                dca_price_verified=payload.get("price_verified") if dca_ok else None,
                dca_scan_as_of=_parse_day(snap["scan_date"]) if snap else None,
                dca_formula_version=payload.get("formula_version") if dca_ok else None,
                held=cand.company_id in held,
                watched=co.ticker in watched,
                evidence_flags=(f"funnel:{run.funnel_version}",),
            )
        )
    return build_result(inputs, run_id=run.id, as_of=as_of, universe=run.universe_size, blocks=blocks)
