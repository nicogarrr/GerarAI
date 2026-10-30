"""Fundamentales «actuales» en TTM a partir de los hechos guardados.

Lee los trimestres (``fiscal_quarter`` Q1-Q4, ``period`` "<cierre>:Qn") y los
ejercicios (``fiscal_quarter`` "FY") de ``financial_facts`` y aplica la fórmula
pura de :mod:`app.services.ttm_fundamentals`. No escribe nada: es una vista.

Por (métrica, periodo) gana la fuente con mejor ``SOURCE_PRIORITY`` (filing
regulador > FMP > Yahoo) y, a empate, la ingesta más reciente; los hechos de
segmento (documento con ``metadata_.segment``) no entran en el consolidado.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, FinancialFact
from app.services.esef_fact_quarantine import fact_quarantine_reason
from app.services.financial_ingestion_service import SOURCE_PRIORITY
from app.services.reviewed_eps_adjustments import NOTE, SOURCE_TYPE, is_reviewed_eps_adjustment
from app.services.split_adjustment import fact_split_factor, split_events_by_company
from app.services.ttm_fundamentals import (
    FLOW_METRICS,
    POINT_METRICS,
    PeriodValue,
    TtmValue,
    combine_ttm,
    latest_point,
    trailing_twelve_months,
)

_END_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}

# Orden de presentación (y lo que devuelve el endpoint).
TTM_METRICS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
    "depreciation_amortization",
    "interest_expense",
    "stock_based_compensation",
    "dividends_paid",
    "cash_and_equivalents",
    "total_debt",
    "net_debt",
    "total_equity",
    "total_assets",
    "shares_outstanding",
    "shares_diluted",
)


def _period_end(fact: FinancialFact) -> date | None:
    match = _END_RE.match(fact.period or "")
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _is_segment(fact: FinancialFact) -> bool:
    source = fact.source
    if source is None:
        return False
    segment = (source.metadata_ or {}).get("segment")
    return bool(segment) and str(segment) != "consolidated"


# Cifras por accion: un trimestre presentado antes de un split sigue en la
# base vieja (el 10-Q siguiente no reexpresa los 3 meses previos) y sumarlo
# con trimestres posteriores mezclaba bases (un 10:1 con 3 trimestres viejos
# daba un BPA TTM ~7x). Regla unica fact_split_factor (consciente de `filed`).
_SPLIT_DIVIDE = frozenset({"eps_diluted"})
_SPLIT_MULTIPLY = frozenset({"shares_diluted"})


def _split_adjusted(fact: FinancialFact, split_events, cutoff: date | None) -> Decimal:
    value = Decimal(fact.value)
    if not split_events or fact.metric not in _SPLIT_DIVIDE | _SPLIT_MULTIPLY:
        return value
    factor = fact_split_factor(split_events, period=fact.period, filed=fact.filed, cutoff=cutoff)
    if factor <= 0 or factor == 1:
        return value
    return value / factor if fact.metric in _SPLIT_DIVIDE else value * factor


def _best_by_period(
    facts: list[FinancialFact],
    split_events=None,
    cutoff: date | None = None,
) -> dict[str, tuple[list[PeriodValue], list[PeriodValue]]]:
    best: dict[tuple[str, str, date], tuple[tuple[float, float], FinancialFact]] = {}
    for fact in facts:
        if fact.source_type == SOURCE_TYPE and not is_reviewed_eps_adjustment(fact):
            continue
        if fact_quarantine_reason(fact):
            continue
        quarter = (fact.fiscal_quarter or "").upper()
        if quarter not in _QUARTERS and quarter != "FY":
            continue
        end = _period_end(fact)
        if end is None or _is_segment(fact):
            continue
        kind = "FY" if quarter == "FY" else "Q"
        rank = (
            float(SOURCE_PRIORITY.get(fact.source_type or "", 50)),
            -(fact.created_at.timestamp() if fact.created_at else 0.0),
        )
        key = (fact.metric, kind, end)
        if key in best and best[key][0] <= rank:
            continue
        best[key] = (rank, fact)
    out: dict[str, tuple[list[PeriodValue], list[PeriodValue]]] = {}
    for (metric, kind, end), (_, fact) in best.items():
        quarters, annuals = out.setdefault(metric, ([], []))
        row = PeriodValue(
            end=end,
            value=_split_adjusted(fact, split_events, cutoff),
            unit=fact.unit or "USD",
            reported=bool(fact.is_reported),
            fact_id=fact.id,
        )
        (annuals if kind == "FY" else quarters).append(row)
    return out


def compute_company_ttm(
    facts: list[FinancialFact],
    split_events=None,
    cutoff: date | None = None,
) -> dict[str, TtmValue]:
    """TTM por métrica para una lista de hechos de UNA empresa.

    ``split_events`` (fecha, ratio) lleva BPA y acciones a la base actual.
    """
    grouped = _best_by_period(facts, split_events, cutoff)
    results: dict[str, TtmValue] = {}
    for metric in FLOW_METRICS:
        quarters, annuals = grouped.get(metric, ([], []))
        results[metric] = trailing_twelve_months(metric, quarters, annuals)
    for metric in POINT_METRICS:
        quarters, annuals = grouped.get(metric, ([], []))
        results[metric] = latest_point(metric, quarters, annuals)
    # Derivadas: solo si los componentes son del mismo periodo y unidad.
    # El capex se guarda en negativo (salida de caja): FCF = flujo op. + capex.
    results["free_cash_flow"] = combine_ttm(
        "free_cash_flow",
        results["operating_cash_flow"],
        results["capital_expenditure"],
        op="add",
    )
    results["net_debt"] = combine_ttm(
        "net_debt", results["total_debt"], results["cash_and_equivalents"], op="sub"
    )
    # Current fundamentals cannot combine a recent reporting window with a
    # metric from years ago. Allow 18 months for annual-only reporters and
    # normal publication lags; this is a display policy, not a revised fact.
    latest_end = max((v.period_end for v in results.values() if v.period_end), default=None)
    if latest_end is not None:
        for metric, value in results.items():
            if value.period_end is not None and (latest_end - value.period_end).days > 550:
                results[metric] = replace(
                    value, value=None, basis="SIN_DATOS", provenance="SIN_DATOS",
                    quarters=[],
                    note=(
                        f"Dato histórico hasta {value.period_end.isoformat()}; no se presenta como actual: "
                        f"más de 18 meses respecto al último periodo disponible ({latest_end.isoformat()})."
                    ),
                )
    return results


def _serialize(value: TtmValue) -> dict[str, Any]:
    return {
        "metric": value.metric,
        "value": value.value,
        "unit": value.unit,
        "basis": value.basis,
        "label": value.label,
        "provenance": value.provenance,
        "period_end": value.period_end,
        "note": value.note,
        "fact_ids": value.fact_ids,
        "quarters": [
            {
                "period_end": q.end,
                "value": q.value,
                "reported": q.reported,
                "origin": q.origin,
            }
            for q in value.quarters
        ],
    }


def build_company_ttm(db: Session, company: Company) -> dict[str, Any]:
    """Respuesta del endpoint ``GET /api/companies/{ticker}/ttm``."""
    metrics = set(FLOW_METRICS) | set(POINT_METRICS)
    facts = list(
        db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(sorted(metrics)),
            )
            .options(selectinload(FinancialFact.source))
        ).all()
    )
    results = compute_company_ttm(
        facts,
        split_events_by_company(db, [company.id]).get(company.id, []),
        date.today(),
    )
    reviewed_ids = {f.id for f in facts if is_reviewed_eps_adjustment(f)}
    for value in results.values():
        if reviewed_ids.intersection(value.fact_ids):
            value.note = NOTE + ((" " + value.note) if value.note else "")
    ttm_ends = [v.period_end for v in results.values() if v.basis == "TTM" and v.period_end]
    return {
        "ticker": company.ticker,
        "as_of": max(ttm_ends) if ttm_ends else None,
        "formula": (
            "Flujos: suma de los 4 últimos trimestres consecutivos "
            "(Q4 = FY − 9 meses cuando no hay 10-Q del cuarto trimestre). "
            "Balance: último trimestre. Sin 4 trimestres: último FY."
        ),
        "metrics": [_serialize(results[m]) for m in TTM_METRICS if m in results],
    }
