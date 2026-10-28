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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CalculatedMetric, Company
from app.services.valuation_metrics_service import (
    FINNHUB_LABEL,
    METRIC_PB,
    METRIC_VERSION,
    METRIC_YIELD,
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
    score: float
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
        if yield_min > 0 and (yield_val is None or yield_val < yield_min):
            continue
        pb_trace = pb_row.calculation_trace or {}
        y_trace = (yield_row.calculation_trace or {}) if yield_row is not None else {}
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
                score=round(score, 2),
                price_to_book=pb,
                pb_price_date=pb_trace.get("price_date"),
                pb_fiscal_year=pb_trace.get("fiscal_year"),
                dividend_yield=yield_val,
                yield_status=yield_row.status if yield_row is not None else None,
                desacuerdo_fuentes=bool(y_trace.get("desacuerdo_fuentes", False)),
                yield_extremo_revisar=bool(y_trace.get("yield_extremo_revisar", False)),
                finnhub_yield_indicated=(
                    Decimal(y_trace["finnhub_yield_indicated"])
                    if y_trace.get("finnhub_yield_indicated") is not None
                    else None
                ),
                fuentes=[YAHOO_LABEL, FINNHUB_LABEL]
                + ([pb_trace["equity_source"]] if pb_trace.get("equity_source") else []),
                metric_as_of=pb_row.period,
            )
        )
    rows.sort(key=lambda r: (-r.score, r.ticker))
    return rows[:limit]
