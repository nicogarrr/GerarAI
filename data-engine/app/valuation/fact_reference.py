"""Shared ``FinancialFact`` resolution for engines that read facts directly.

``FinancialSnapshot`` is the right entry point for the FCFF DCF: it enforces
temporal coherence between a duration metric (revenue) and its companions.
The sector engines (banks, insurers, REITs, commodities) and the new
DDM/FCFE, regulated-utility and relative-multiple engines do not use it
because their inputs are not a cash-flow statement: a tangible book value, a
combined ratio, a rate base or a peer multiple are point-in-time or
cross-company readings, and the snapshot would either drop them (they are not
in ``DURATION_METRICS``/``INSTANT_METRICS``) or silently pair them with a
revenue anchor from another fiscal year.

This module centralises the one thing all those engines were re-implementing:
"the latest fact for this company for this metric, with its provenance".

Three contracts:

1. **Order**: ``fiscal_year DESC NULLS LAST`` then ``created_at DESC`` — the
   same order ``sector_specific._latest`` and ``commodity`` used, so a value
   does not change because a file was refactored.
2. **Aliases are the caller's business, not this module's.** ``resolve_aliases``
   returns the fact with its **real** metric name, so a provenance map keyed by
   the alias the engine asked for (e.g. ``production_volume`` for a
   ``sales_volume`` row) cannot become a lie in ``trace["fact_ids"]``. This is
   the rule the commodity engine had to fix by hand.
3. **A non-finite stored value is a missing input.** Postgres
   ``Numeric(24, 6)`` admits NaN/inf and every clamp in this package is
   NaN-transparent (``min(nan, 0.5)`` is ``nan``), so a poisoned row must be
   dropped at the boundary rather than at each engine.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import FinancialFact
from app.services.split_adjustment import split_factor_for_fact


@dataclass(frozen=True)
class SourcedFact:
    """A single financial fact plus everything a valuation trace needs to cite it."""

    metric: str
    value: float
    fact_id: int
    period: str
    confidence: float
    source_type: str
    is_reported: bool
    # Splits posteriores al hecho ya aplicados a ``value`` (acciones x factor,
    # importes por accion / factor). 1.0 = sin ajuste.
    split_factor: float = 1.0

    def as_trace(self) -> dict:
        trace = {
            "metric": self.metric,
            "value": self.value,
            "fact_id": self.fact_id,
            "period": self.period,
            "confidence": self.confidence,
            "source_type": self.source_type,
            "is_reported": self.is_reported,
        }
        if self.split_factor != 1.0:
            trace["split_factor"] = self.split_factor
        return trace


def _to_sourced(fact: FinancialFact) -> SourcedFact | None:
    """Reduce a row to a ``SourcedFact``, or ``None`` if its value is unusable.

    ``None`` for a non-finite or NULL value is the point of this function: the
    caller sees a missing input, not a NaN it has to remember to check.
    """
    if fact.value is None:
        return None
    value = float(fact.value)
    if not math.isfinite(value):
        return None
    return SourcedFact(
        metric=fact.metric,
        value=value,
        fact_id=fact.id,
        period=fact.period,
        confidence=float(fact.confidence) if fact.confidence is not None else 0.0,
        source_type=fact.source_type or "unspecified",
        is_reported=bool(fact.is_reported),
    )


def latest_fact(db: Session, company_id: int, *metrics: str) -> SourcedFact | None:
    """Latest usable fact for any of ``metrics``, trying them in order."""
    for metric in metrics:
        found = latest_facts(db, company_id, [metric]).get(metric)
        if found is not None:
            return found
    return None


def latest_facts(db: Session, company_id: int, metrics: Sequence[str]) -> dict[str, SourcedFact]:
    """Latest usable fact per metric, in one query per metric.

    A single grouped query would be cheaper, but "latest" here means
    ``fiscal_year`` then ``created_at`` and the caller may ask for the same
    company for six metrics; six indexed lookups are cheaper than the
    window-function query that would express this portably.
    """
    resolved: dict[str, SourcedFact] = {}
    for metric in metrics:
        row = db.scalar(
            select(FinancialFact)
            .where(FinancialFact.company_id == company_id, FinancialFact.metric == metric)
            .order_by(
                FinancialFact.fiscal_year.desc().nullslast(),
                desc(FinancialFact.created_at),
            )
            .limit(1)
        )
        if row is None:
            continue
        sourced = _to_sourced(row)
        if sourced is not None:
            resolved[metric] = _split_adjusted(db, company_id, row, sourced)
    return resolved


# Recuentos de acciones y magnitudes POR ACCION: un split posterior al hecho
# cambia su escala frente al precio de hoy (el precio ya esta dividido).
SHARE_COUNT_METRICS = frozenset({"shares_diluted", "shares_outstanding", "shares_basic"})
PER_SHARE_METRICS = frozenset(
    {
        "eps",
        "eps_diluted",
        "eps_basic",
        "dividend_per_share",
        "dividends_per_share",
        "annual_dividend_per_share",
        "book_value_per_share",
        "nav_per_share",
    }
)


def _split_adjusted(db: Session, company_id: int, row: FinancialFact, sourced: SourcedFact) -> SourcedFact:
    """Pone acciones y magnitudes por accion en la base del precio de hoy.

    El precio de mercado ya refleja un split 4:1 posterior al ejercicio; el
    hecho del 10-K no. Sin el ajuste un BPA de 8 frente a un precio de 25
    (antes 100) daba PER 3 en vez de 12, y un DDM o un valor por accion x4.
    Misma regla que el snapshot del DCF (split_factor_for_fact).
    """
    if sourced.metric not in SHARE_COUNT_METRICS and sourced.metric not in PER_SHARE_METRICS:
        return sourced
    factor = float(
        split_factor_for_fact(db, company_id, period=row.period, filed=row.filed, cutoff=date.today())
    )
    if factor == 1.0 or factor <= 0:
        return sourced
    value = sourced.value * factor if sourced.metric in SHARE_COUNT_METRICS else sourced.value / factor
    return replace(sourced, value=value, split_factor=factor)


def resolve_aliases(
    rows: Mapping[str, SourcedFact],
    aliases: Mapping[str, Sequence[str]],
) -> dict[str, SourcedFact]:
    """Map ``{canonical_name: (metric1, metric2, ...)}`` onto available facts.

    Only the canonical key is produced; the returned ``SourcedFact.metric`` is
    the real stored name, so ``fact_ids`` can be keyed by the canonical name
    while the provenance trail still points at the row that was actually read.
    """
    resolved: dict[str, SourcedFact] = {}
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            found = rows.get(candidate)
            if found is not None:
                resolved[canonical] = found
                break
    return resolved


def mean_confidence(facts: Iterable[SourcedFact]) -> float:
    """Average source confidence over the facts a model actually reads.

    Averaging in rows the model never consumes would move the scenario
    probabilities just because a balance sheet happened to be ingested, which
    is why every engine passes its own ``MODEL_INPUT_METRICS`` set.
    """
    values = [fact.confidence for fact in facts]
    return sum(values) / len(values) if values else 0.0


def provenance_trace(facts: Mapping[str, SourcedFact]) -> dict[str, dict]:
    """Per-input provenance block for ``trace`` (metric, period, fact id, source)."""
    return {name: fact.as_trace() for name, fact in facts.items()}


def fact_ids_and_periods(facts: Mapping[str, SourcedFact]) -> tuple[dict, dict]:
    """Split provenance into the two ``trace`` keys every engine publishes.

    ``periods`` is not decoration: ``valuation_service``'s no-lookahead guard
    reads ``trace["periods"]`` and rejects a valuation built from a fiscal year
    after the requested ``as_of``.
    """
    ids = {name: fact.fact_id for name, fact in facts.items()}
    periods = {name: fact.period for name, fact in facts.items()}
    return ids, periods
