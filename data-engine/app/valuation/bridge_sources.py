"""Resolutor multi-fuente de las piezas criticas del puente de valoracion.

Regla del propietario (Nico, 3-nov-2026): «asegurate bien antes de decir que
tienen 0 deuda y cosas asi, busca en mas fuentes». Para deuda total, deuda
neta, caja y acciones diluidas:

- Nunca se acepta un 0 (ni una ausencia) de UNA sola fuente: un cero solo
  vale si dos fuentes independientes coinciden en ~0.
- Con dos o mas fuentes que coinciden (tolerancia ``AGREEMENT_TOLERANCE``)
  el dato queda ``confirmado`` y cita ambas.
- Si discrepan, manda la presentacion OFICIAL mas reciente (SEC/ESEF/CNMV) y
  la discrepancia queda en la traza; sin oficial, la mas reciente y marcada.
- Con una sola fuente no oficial se usa, marcada «una sola fuente, no oficial».

Es un modulo puro: recibe hechos ya filtrados (cuarentena, corte filed) y
devuelve la eleccion con su procedencia; el snapshot decide cuando usarla.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models import FinancialFact

CRITICAL_INPUTS: tuple[str, ...] = ("total_debt", "net_debt", "cash_and_equivalents", "shares_diluted")
PRIMARY_SOURCES: frozenset[str] = frozenset({"SEC", "ESEF", "CNMV"})
AGREEMENT_TOLERANCE = 0.10
# Ventana del modo relajado: un balance de hasta ~15 meses antes del ancla
# (p. ej. cierre anual frente a un ancla trimestral posterior).
MAX_STALENESS_DAYS = 460

_SOURCE_LABELS = {
    "SEC": "SEC (10-K/10-Q)",
    "ESEF": "cuentas anuales ESEF",
    "CNMV": "CNMV",
    "FMP": "Financial Modeling Prep (no oficial)",
    "YAHOO_FUNDAMENTALS": "Yahoo Finance (no oficial)",
}
_PERIOD_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def source_label(source_type: str | None) -> str:
    key = (source_type or "").strip()
    return _SOURCE_LABELS.get(key, key or "fuente desconocida")


def _source_key(fact: FinancialFact) -> str:
    raw = (getattr(fact, "source_type", None) or "").strip()
    upper = raw.upper()
    if upper.startswith("SEC"):
        return "SEC"
    if upper.startswith("FMP"):
        return "FMP"
    return upper or "DESCONOCIDA"


def _period_end(fact: FinancialFact) -> date | None:
    match = _PERIOD_DATE.match(str(getattr(fact, "period", "") or ""))
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    year = getattr(fact, "fiscal_year", None)
    return date(int(year), 12, 31) if year else None


def _finite(fact: FinancialFact) -> float | None:
    try:
        value = float(fact.value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def values_agree(a: float, b: float, *, scale: float | None = None) -> bool:
    """Coinciden si la diferencia cabe en la tolerancia relativa.

    ``scale`` (p. ej. la deuda bruta) evita que una deuda neta cercana a cero
    convierta diferencias pequenas en discrepancias del 300 %.
    """
    reference = max(abs(a), abs(b), abs(scale or 0.0))
    if reference == 0:
        return True
    return abs(a - b) <= AGREEMENT_TOLERANCE * reference


@dataclass
class Candidate:
    source: str
    value: float
    period: str | None
    period_end: date | None
    fact: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_label": source_label(self.source),
            "value": self.value,
            "period": self.period,
            "fact_id": getattr(self.fact, "id", None),
        }


@dataclass
class ResolvedInput:
    metric: str
    chosen: Candidate
    status: str  # confirmed | single_source | discrepancy | primary_only
    candidates: list[Candidate] = field(default_factory=list)
    note: str = ""

    @property
    def official(self) -> bool:
        return self.chosen.source in PRIMARY_SOURCES

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.chosen.value,
            "period": self.chosen.period,
            "source": self.chosen.source,
            "source_label": source_label(self.chosen.source),
            "official": self.official,
            "status": self.status,
            "note": self.note,
            "sources": [c.as_dict() for c in self.candidates],
        }


def newest_per_source(
    facts: list[FinancialFact], *, not_after: date | None = None, not_before: date | None = None
) -> list[Candidate]:
    """El hecho mas reciente de cada fuente (dentro de la ventana, si la hay)."""
    best: dict[str, Candidate] = {}
    for fact in facts:
        value = _finite(fact)
        if value is None:
            continue
        end = _period_end(fact)
        if not_after is not None and end is not None and end > not_after:
            continue
        if not_before is not None and (end is None or end < not_before):
            continue
        source = _source_key(fact)
        current = best.get(source)
        if current is None or (end or date.min) > (current.period_end or date.min):
            best[source] = Candidate(source, value, getattr(fact, "period", None), end, fact)
    return sorted(best.values(), key=lambda c: (c.period_end or date.min), reverse=True)


def resolve(
    metric: str, candidates: list[Candidate], *, scale: float | None = None
) -> ResolvedInput | None:
    """Aplica la regla de fuentes; None si no hay nada aceptable."""
    if not candidates:
        return None
    primaries = [c for c in candidates if c.source in PRIMARY_SOURCES]
    chosen = (primaries or candidates)[0]  # ya vienen del mas reciente al mas antiguo
    others = [c for c in candidates if c is not chosen]
    agreeing = [c for c in others if values_agree(chosen.value, c.value, scale=scale)]
    is_zero = abs(chosen.value) < 1e-9
    if is_zero and not agreeing:
        # Un cero de una sola fuente no es un dato: puede ser un hueco de mapeo.
        return None
    if agreeing:
        names = ", ".join(source_label(c.source) for c in [chosen, *agreeing])
        return ResolvedInput(metric, chosen, "confirmed", candidates, f"confirmado por {names}")
    if others:
        detail = "; ".join(f"{source_label(c.source)} {c.value:,.0f} ({c.period})" for c in others)
        rule = "manda la presentación oficial más reciente" if primaries else "se usa la más reciente"
        return ResolvedInput(
            metric,
            chosen,
            "discrepancy",
            candidates,
            f"discrepancia entre fuentes ({rule}): {source_label(chosen.source)} "
            f"{chosen.value:,.0f} ({chosen.period}) frente a {detail}",
        )
    if chosen.source in PRIMARY_SOURCES:
        return ResolvedInput(metric, chosen, "primary_only", candidates, f"fuente oficial: {source_label(chosen.source)}")
    return ResolvedInput(
        metric, chosen, "single_source", candidates,
        f"una sola fuente, no oficial ({source_label(chosen.source)})",
    )
