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
from app.services.esef_fact_quarantine import fact_quarantine_reason
from app.services.reviewed_eps_adjustments import eligible_fact
from app.services.split_adjustment import split_factor_for_fact
from app.valuation.call_cache import cached
from app.valuation.share_scale import (
    PER_SHARE_REFERENCE_MAX_DAYS,
    SHARE_SCALE_REFERENCE_MAX_DAYS,
    ShareScale,
    per_share_scale_is_wrong,
    period_end,
    share_scale_factor,
)


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
    unit: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    # Recuento declarado en miles/millones y corregido (``share_scale``):
    # referencia y factor van a la traza. None = escala tal cual se declaro.
    share_scale: ShareScale | None = None

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
        if self.unit is not None:
            trace["unit"] = self.unit
        if self.share_scale is not None:
            trace["share_scale"] = self.share_scale.as_trace()
        if self.fiscal_year is not None:
            trace["fiscal_year"] = self.fiscal_year
            trace["fiscal_quarter"] = self.fiscal_quarter
        return trace



def usable_fact(fact: FinancialFact) -> bool:
    """Misma frontera que el snapshot del DCF: cuarentena ESEF y elegibilidad.

    ``financial_snapshot._facts_for_metric``, watchlist, TTM, screener y el
    market cap derivado rechazan estos hechos; una lectura directa que no lo
    haga valora con una fila que el resto de superficies declara envenenada
    (p. ej. el ``eps_diluted`` ESEF 1351 de EBRO, escala x1000: el PER saldria
    mil veces menor). Un hecho en cuarentena no es "el ultimo": es ausente,
    y se cae al limpio anterior si existe.
    """
    return not fact_quarantine_reason(fact) and eligible_fact(fact)


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
        confidence=fact_confidence(fact),
        source_type=fact.source_type or "unspecified",
        is_reported=bool(fact.is_reported),
        unit=fact.unit,
        fiscal_year=fact.fiscal_year,
        fiscal_quarter=fact.fiscal_quarter,
    )


def latest_fact(
    db: Session, company_id: int, *metrics: str, cutoff: date | None = None
) -> SourcedFact | None:
    """Latest usable fact for any of ``metrics``, trying them in order."""
    for metric in metrics:
        found = latest_facts(db, company_id, [metric], cutoff=cutoff).get(metric)
        if found is not None:
            return found
    return None


def latest_facts_multi(
    db: Session,
    company_id: int,
    metrics: Sequence[str],
    *,
    cutoff: date | None = None,
) -> dict[str, SourcedFact]:
    """Misma seleccion que ``latest_facts`` metrica a metrica, en UNA consulta.

    El cross-check de multiplos pedia cada alias por separado (medido: 157
    SELECTs a financial_facts en una valoracion con 8 peers). La ordenacion
    global (fiscal_year DESC NULLS LAST, created_at DESC) restringida a una
    metrica es exactamente la de la consulta individual, asi que agrupar en
    Python elige la misma fila usable; el ajuste por split sigue por metrica.
    """
    unique = sorted(set(metrics))
    rows = cached(
        db,
        "latest_facts_multi_rows",
        (company_id, tuple(unique)),
        lambda: list(
            db.scalars(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id == company_id,
                    FinancialFact.metric.in_(unique),
                )
                .order_by(
                    FinancialFact.fiscal_year.desc().nullslast(),
                    desc(FinancialFact.created_at),
                )
            ).all()
        ),
    )
    by_metric: dict[str, list[FinancialFact]] = {metric: [] for metric in unique}
    for row in rows:
        by_metric[row.metric].append(row)
    resolved: dict[str, SourcedFact] = {}
    for metric in metrics:
        row = next((candidate for candidate in by_metric[metric] if usable_fact(candidate)), None)
        if row is None:
            continue
        sourced = _to_sourced(row)
        if sourced is not None:
            resolved[metric] = _split_adjusted(db, company_id, row, sourced, cutoff=cutoff)
    return resolved


def latest_facts(
    db: Session,
    company_id: int,
    metrics: Sequence[str],
    *,
    cutoff: date | None = None,
) -> dict[str, SourcedFact]:
    """Latest usable fact per metric, in one query per metric.

    ``cutoff``: fecha del precio con el que se comparan acciones y magnitudes
    por accion (splits posteriores a esa fecha no cuentan); None = hoy.

    A single grouped query would be cheaper, but "latest" here means
    ``fiscal_year`` then ``created_at`` and the caller may ask for the same
    company for six metrics; six indexed lookups are cheaper than the
    window-function query that would express this portably.
    """
    resolved: dict[str, SourcedFact] = {}
    for metric in metrics:
        # Sin LIMIT 1: la fila mas reciente puede estar en cuarentena y la
        # usable es la anterior; el orden ya es "ultimo primero".
        # Un importe por accion con la escala rota (BPA x acciones = cientos
        # de veces el beneficio) tampoco es "el ultimo": se cae al anterior.
        # La eleccion de fila no depende de ``cutoff`` (eso es el ajuste por
        # split de despues): se cachea por llamada (app/valuation/call_cache.py).
        row = cached(
            db,
            "latest_facts_row",
            (company_id, metric),
            lambda metric=metric: next(
                (
                    candidate
                    for candidate in db.scalars(
                        select(FinancialFact)
                        .where(FinancialFact.company_id == company_id, FinancialFact.metric == metric)
                        .order_by(
                            FinancialFact.fiscal_year.desc().nullslast(),
                            desc(FinancialFact.created_at),
                        )
                    ).all()
                    if usable_fact(candidate)
                    and not per_share_fact_scale_is_wrong(db, company_id, candidate, cutoff=cutoff)
                ),
                None,
            ),
        )
        if row is None:
            continue
        sourced = _to_sourced(row)
        if sourced is not None:
            resolved[metric] = _scale_adjusted(
                db, company_id, row, _split_adjusted(db, company_id, row, sourced, cutoff=cutoff),
                cutoff=cutoff,
            )
    return resolved


def _share_count_rows(db: Session, company_id: int) -> list[FinancialFact]:
    return cached(
        db,
        "share_scale_share_rows",
        company_id,
        lambda: list(
            db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == company_id,
                    FinancialFact.metric.in_(sorted(SHARE_COUNT_METRICS)),
                )
            ).all()
        ),
    )


def _nearest_reference(
    rows: Iterable[FinancialFact],
    end: date,
    *,
    max_days: int,
    exclude_id: int | None = None,
    prefer: str | None = None,
) -> FinancialFact | None:
    """Hecho usable de cierre mas cercano a ``end`` (``prefer`` primero)."""
    best: tuple[int, int, int] | None = None
    chosen: FinancialFact | None = None
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        if row.value is None or not usable_fact(row):
            continue
        try:
            value = float(row.value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        row_end = period_end(row.period)
        if row_end is None:
            continue
        days = abs((row_end - end).days)
        if days > max_days:
            continue
        key = (0 if prefer is not None and row.metric == prefer else 1, days, -(row.id or 0))
        if best is None or key < best:
            best, chosen = key, row
    return chosen


def detect_share_scale(
    db: Session,
    company_id: int,
    row: FinancialFact,
    *,
    cutoff: date | None = None,
    filed_not_after: date | None = None,
) -> ShareScale | None:
    """Escala de un recuento de acciones frente al recuento de cierre mas cercano.

    Referencia: ``shares_outstanding`` (portada dei / balance) del cierre mas
    cercano; si no hay, el recuento mas cercano de otra metrica de acciones.
    Ambos en la base de splits del precio. ``filed_not_after``: corte
    point-in-time (no se contrasta con un filing posterior). None = escala
    correcta o sin referencia (no se adivina).
    """
    if row.metric not in SHARE_COUNT_METRICS or row.value is None:
        return None
    end = period_end(row.period)
    if end is None:
        return None
    rows = [
        r for r in _share_count_rows(db, company_id)
        if filed_not_after is None or r.filed is None or r.filed <= filed_not_after
    ]
    reference = _nearest_reference(
        rows, end, max_days=SHARE_SCALE_REFERENCE_MAX_DAYS, exclude_id=row.id, prefer="shares_outstanding"
    )
    if reference is None:
        return None
    value = split_scaled_value(db, company_id, row, cutoff=cutoff)
    ref_value = split_scaled_value(db, company_id, reference, cutoff=cutoff)
    factor = share_scale_factor(value, ref_value)
    if factor == 1.0:
        return None
    return ShareScale(
        factor=factor,
        reference_metric=reference.metric,
        reference_value=ref_value,
        reference_period=reference.period,
        reference_fact_id=reference.id,
    )


def _scale_adjusted(
    db: Session,
    company_id: int,
    row: FinancialFact,
    sourced: SourcedFact,
    *,
    cutoff: date | None = None,
) -> SourcedFact:
    """Recuento declarado en miles/millones -> acciones (``detect_share_scale``)."""
    scale = detect_share_scale(db, company_id, row, cutoff=cutoff)
    if scale is None:
        return sourced
    return replace(sourced, value=sourced.value * scale.factor, share_scale=scale)


def per_share_fact_scale_is_wrong(
    db: Session, company_id: int, row: FinancialFact, *, cutoff: date | None = None
) -> bool:
    """BPA (o importe por accion de beneficio) con la escala rota.

    Beneficio implicito = |BPA| x acciones del cierre mas cercano; si es
    cientos de veces el beneficio neto declarado mas cercano, el BPA no se
    usa. Sin beneficio o sin acciones de referencia no se juzga.
    """
    if row.metric not in EARNINGS_PER_SHARE_METRICS or row.value is None:
        return False
    end = period_end(row.period)
    if end is None:
        return False
    income_rows = cached(
        db,
        "share_scale_income_rows",
        company_id,
        lambda: list(
            db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == company_id, FinancialFact.metric == "net_income"
                )
            ).all()
        ),
    )
    income = _nearest_income(income_rows, end)
    if income is None:
        return False
    shares_row = _nearest_reference(
        _share_count_rows(db, company_id), end, max_days=PER_SHARE_REFERENCE_MAX_DAYS, prefer="shares_diluted"
    )
    if shares_row is None:
        return False
    shares = split_scaled_value(db, company_id, shares_row, cutoff=cutoff)
    scale = detect_share_scale(db, company_id, shares_row, cutoff=cutoff)
    if scale is not None:
        shares *= scale.factor
    per_share = split_scaled_value(db, company_id, row, cutoff=cutoff)
    return per_share_scale_is_wrong(per_share, income, shares)


def _nearest_income(rows: Iterable[FinancialFact], end: date) -> float | None:
    best: tuple[int, int] | None = None
    value: float | None = None
    for row in rows:
        if row.value is None or not usable_fact(row):
            continue
        row_end = period_end(row.period)
        if row_end is None:
            continue
        current = float(row.value)
        if not math.isfinite(current) or current == 0:
            continue
        days = abs((row_end - end).days)
        if days > PER_SHARE_REFERENCE_MAX_DAYS:
            continue
        key = (days, -(row.id or 0))
        if best is None or key < best:
            best, value = key, current
    return value


# Recuentos de acciones y magnitudes POR ACCION: un split posterior al hecho
# cambia su escala frente al precio de hoy (el precio ya esta dividido).
SHARE_COUNT_METRICS = frozenset({"shares_diluted", "shares_outstanding", "shares_basic"})
# Importes por accion que son beneficio / accion: los unicos que se contrastan
# con beneficio neto / acciones (un dividendo o un VC por accion no).
EARNINGS_PER_SHARE_METRICS = frozenset({"eps", "eps_diluted", "eps_basic"})
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


def _split_adjusted(
    db: Session,
    company_id: int,
    row: FinancialFact,
    sourced: SourcedFact,
    *,
    cutoff: date | None = None,
) -> SourcedFact:
    """Pone acciones y magnitudes por accion en la base del precio de hoy.

    El precio de mercado ya refleja un split 4:1 posterior al ejercicio; el
    hecho del 10-K no. Sin el ajuste un BPA de 8 frente a un precio de 25
    (antes 100) daba PER 3 en vez de 12, y un DDM o un valor por accion x4.
    Misma regla que el snapshot del DCF (split_factor_for_fact).
    """
    factor = post_split_factor(db, company_id, row, cutoff=cutoff)
    if factor == 1.0:
        return sourced
    value = sourced.value * factor if sourced.metric in SHARE_COUNT_METRICS else sourced.value / factor
    return replace(sourced, value=value, split_factor=factor)


def post_split_factor(
    db: Session, company_id: int, row: FinancialFact, *, cutoff: date | None = None
) -> float:
    """Factor de splits posteriores para un recuento de acciones o una magnitud
    por accion; 1.0 para cualquier otra metrica (importes totales no cambian)."""
    if row.metric not in SHARE_COUNT_METRICS and row.metric not in PER_SHARE_METRICS:
        return 1.0
    factor = float(
        split_factor_for_fact(
            db, company_id, period=row.period, filed=row.filed, cutoff=cutoff or date.today()
        )
    )
    return factor if factor > 0 else 1.0


def split_scaled_value(
    db: Session, company_id: int, row: FinancialFact, *, cutoff: date | None = None
) -> float:
    """``row.value`` en la base del precio (ver ``_split_adjusted``)."""
    factor = post_split_factor(db, company_id, row, cutoff=cutoff)
    value = float(row.value)
    if factor == 1.0:
        return value
    return value * factor if row.metric in SHARE_COUNT_METRICS else value / factor


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


def fact_confidence(fact: object) -> float:
    """Confianza de un hecho (fila o transitorio) como ``float`` sin reventar.

    Un hecho derivado en memoria (``DERIVED``, puente de fuentes) no pasa por el
    INSERT, así que el ``default`` de la columna no se aplica y su
    ``confidence`` puede ser ``None``. La regla es la misma que ``_to_sourced``:
    sin confianza registrada (o no finita) cuenta como 0,0 — no se inventa una —
    y quien la promedia lo deja dicho con :func:`missing_confidence_metrics`.
    """
    raw = getattr(fact, "confidence", None)
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def has_confidence(fact: object) -> bool:
    raw = getattr(fact, "confidence", None)
    if raw is None:
        return False
    try:
        return math.isfinite(float(raw))
    except (TypeError, ValueError):
        return False


def mean_fact_confidence(facts: Iterable[object]) -> float:
    """Media de :func:`fact_confidence` (0,0 si no hay hechos)."""
    values = [fact_confidence(fact) for fact in facts]
    return sum(values) / len(values) if values else 0.0


def missing_confidence_metrics(facts: Iterable[object]) -> list[str]:
    """Métricas cuyo hecho no trae confianza registrada (ordenadas, sin repetir)."""
    return sorted({str(getattr(f, "metric", "") or "?") for f in facts if not has_confidence(f)})


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
