"""Estrategia Deep value: cribado por descuento a libros y dividendo.

NO es el embudo de calidad ProPicks: aqui entran a proposito empresas que el
embudo rechazaria (apalancadas, ciclicas, inmobiliarias). Solo lee las
metricas de valoracion persistidas por valuation_metrics_service
(``price_to_book`` / ``dividend_yield_ttm``, definition ``valuation-v1``);
no calcula ni imputa nada. Una metrica con as_of viejo no se sirve
(``MAX_METRIC_AGE_DAYS``): mejor "sin datos" que un dato de otra semana.

Score declarado (pesos fijos, renormalizados si falta el yield):
  60% descuento a libros dentro del umbral pedido + 40% yield normalizado a
  YIELD_FULL. Es un orden de cribado, no una recomendacion.
Filas disputadas, extremas o con base P/B sin verificar: score=None,
review_reasons y seccion separada, nunca una ganga. limit acota CADA seccion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CalculatedMetric, Company
from app.services.valuation_metrics_service import (
    DISAGREE_REL_TOL,
    EXTREME_YIELD,
    FINNHUB_LABEL,
    METRIC_PB,
    METRIC_VERSION,
    METRIC_YIELD,
    STATUS_DISAGREE,
    STATUS_OK,
    YAHOO_LABEL,
)

STRATEGY_ID = "deep-value-v1"
STRATEGY_LABEL = (
    "Estrategia Deep value: descuento a valor en libros y dividendo. "
    "No es el filtro de calidad ProPicks: acepta apalancamiento y ciclicidad "
    "que el embudo rechaza. El dividendo viene de Yahoo Finance (fuente no "
    "oficial) con contraste Finnhub cuando existe."
)
MAX_METRIC_AGE_DAYS = 7
YIELD_FULL = Decimal("0.10")  # 10%: yield a partir del cual el componente puntua al maximo
W_DISCOUNT = 0.6
W_YIELD = 0.4


@dataclass
class DeepValueRow:
    ticker: str
    name: str
    exchange: str
    currency: str
    sector: str | None
    score: float | None
    price_to_book: Decimal
    pb_price_date: str | None
    pb_fiscal_year: int | None
    dividend_yield: Decimal | None
    yield_status: str | None
    desacuerdo_fuentes: bool
    yield_extremo_revisar: bool
    finnhub_yield_indicated: Decimal | None = None
    fuentes: list[str] = field(default_factory=list)
    metric_as_of: str | None = None
    review_reasons: list[str] = field(default_factory=list)


def _latest_metrics(db: Session) -> dict[int, dict[str, CalculatedMetric]]:
    """Ultima metrica valuation-v1 de cada tipo por empresa (period mas reciente)."""
    rows = db.scalars(
        select(CalculatedMetric)
        .where(
            CalculatedMetric.metric.in_([METRIC_PB, METRIC_YIELD]),
            CalculatedMetric.definition_version == METRIC_VERSION,
            *tenant_filters(db, CalculatedMetric),
        )
        .order_by(CalculatedMetric.period.desc())
    ).all()
    out: dict[int, dict[str, CalculatedMetric]] = {}
    for row in rows:
        per = out.setdefault(row.company_id, {})
        per.setdefault(row.metric, row)
    return out


def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _pb_review_reasons(row: CalculatedMetric, pb: Decimal, trace: dict, today: date) -> list[str]:
    reasons = []
    if row.status != STATUS_OK:
        reasons.append("pb_status_unverified")
    if trace.get("price_date"):
        try:
            age = (today - date.fromisoformat(trace["price_date"])).days
        except (ValueError, TypeError):
            age = -1
        if not 0 <= age <= MAX_METRIC_AGE_DAYS:
            reasons.append("pb_price_stale_or_invalid")
    factor = _finite_decimal(trace.get("split_factor", "1"))
    if factor is None or factor <= 0:
        return reasons + ["pb_split_factor_invalid"]
    # Legacy traces do not expose the filed-aware basis used for the split.
    # Quarantine rather than guess whether shares were already restated.
    if factor != 1 and not (
        trace.get("shares_period") and trace.get("shares_filed")
        and trace.get("split_basis") == "fact_split_factor_filed_aware"
    ):
        reasons.append("pb_split_basis_unverified")
    keys = ("price", "total_equity", "shares_diluted")
    if all(k in trace for k in keys):
        price, equity, shares = (_finite_decimal(trace[k]) for k in keys)
        ratio = _finite_decimal(trace.get("adr_ratio") or "1")
        if any(v is None or v <= 0 for v in (price, equity, shares, ratio)):
            reasons.append("pb_inputs_inconsistent")
        else:
            expected = price * shares * factor / equity / ratio
            # calculated_metrics stores eight decimals. Only permit its
            # quantization error, not a discretionary percent tolerance.
            if abs(pb - expected) > Decimal("0.00000001"):
                reasons.append("pb_inputs_inconsistent")
    return reasons


def find_deep_value(
    db: Session,
    *,
    pb_max: Decimal = Decimal("1.0"),
    yield_min: Decimal = Decimal("0"),
    limit: int = 50,
    today: date | None = None,
) -> list[DeepValueRow]:
    today = today or date.today()
    latest = _latest_metrics(db)
    if not latest:
        return []
    companies = {
        c.id: c
        for c in db.scalars(select(Company).where(Company.id.in_(list(latest)))).all()
    }
    rows: list[DeepValueRow] = []
    for company_id, metrics in latest.items():
        company = companies.get(company_id)
        pb_row = metrics.get(METRIC_PB)
        if company is None or pb_row is None or pb_row.value is None:
            continue
        as_of = date.fromisoformat(pb_row.period)
        if (today - as_of).days > MAX_METRIC_AGE_DAYS:
            continue  # metrica de otra semana: no se sirve
        pb = Decimal(str(pb_row.value))
        if pb <= 0 or pb > pb_max:
            continue
        yield_row = metrics.get(METRIC_YIELD)
        if yield_row is not None:
            yield_as_of = date.fromisoformat(yield_row.period)
            if (today - yield_as_of).days > MAX_METRIC_AGE_DAYS:
                # Yield de otra semana con P/B fresco: se sirve como "sin
                # datos" (N/D), nunca como cifra. Misma regla fail-closed
                # que la frescura del P/B.
                yield_row = None
        yield_val = (
            Decimal(str(yield_row.value))
            if yield_row is not None and yield_row.value is not None
            else None
        )
        pb_trace = pb_row.calculation_trace or {}
        y_trace = (yield_row.calculation_trace or {}) if yield_row is not None else {}
        # Fail closed for ranking, not for visibility. A suspicious dividend
        # disqualifies the WHOLE row: merely removing its yield weight would
        # still reward a distorted P/B after a liquidation or split.
        other_yield = _finite_decimal(y_trace.get("finnhub_yield_indicated"))
        disagree = bool(y_trace.get("desacuerdo_fuentes", False)) or (
            yield_row is not None and yield_row.status == STATUS_DISAGREE
        )
        if yield_val is not None and other_yield is not None:
            top = max(yield_val, other_yield)
            disagree = disagree or (top > 0 and abs(yield_val - other_yield) / top > DISAGREE_REL_TOL)
        extreme = bool(y_trace.get("yield_extremo_revisar", False)) or (
            yield_val is not None and yield_val > EXTREME_YIELD
        )
        review_reasons = []
        if disagree:
            review_reasons.append("yield_sources_disagree")
        if extreme:
            review_reasons.append("yield_extreme")
        non_recurring = any(
            event.get("distribution_type") in {"liquidating", "special", "return_of_capital"}
            for event in y_trace.get("dividend_events", [])
            if isinstance(event, dict)
        )
        if non_recurring:
            review_reasons.append("dividend_non_recurring")
        review_reasons.extend(_pb_review_reasons(pb_row, pb, pb_trace, today))
        # A disputed dividend cannot meet a minimum-yield screen. Keep it
        # separately visible with its warning instead of presenting a match.
        if not review_reasons and yield_min > 0 and (yield_val is None or yield_val < yield_min):
            continue
        parts: dict[str, float] = {
            "descuento": max(0.0, min(1.0, float((pb_max - pb) / pb_max)))
        }
        if yield_val is not None:
            parts["yield"] = max(0.0, min(1.0, float(yield_val / YIELD_FULL)))
        total_w = sum(W_DISCOUNT if k == "descuento" else W_YIELD for k in parts)
        score = 100.0 * sum(
            (W_DISCOUNT if k == "descuento" else W_YIELD) * v for k, v in parts.items()
        ) / total_w
        rows.append(
            DeepValueRow(
                ticker=company.ticker,
                name=company.name,
                exchange=company.exchange,
                currency=company.currency,
                sector=company.sector,
                score=None if review_reasons else round(score, 2),
                price_to_book=pb,
                pb_price_date=pb_trace.get("price_date"),
                pb_fiscal_year=pb_trace.get("fiscal_year"),
                dividend_yield=yield_val,
                yield_status=yield_row.status if yield_row is not None else None,
                desacuerdo_fuentes=disagree,
                yield_extremo_revisar=extreme,
                finnhub_yield_indicated=other_yield,
                fuentes=[YAHOO_LABEL, FINNHUB_LABEL]
                + ([pb_trace["equity_source"]] if pb_trace.get("equity_source") else []),
                metric_as_of=pb_row.period,
                review_reasons=review_reasons,
            )
        )
    ranked = sorted((r for r in rows if not r.review_reasons), key=lambda r: (-(r.score or 0), r.ticker))
    pending = sorted((r for r in rows if r.review_reasons), key=lambda r: r.ticker)
    # Independent bounds: anomalies never consume a slot of the valid ranking.
    return ranked[:limit] + pending[:limit]
