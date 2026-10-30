"""Valuation engine contracts and shared helpers."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company
from app.services.inferred_input_service import InferredInputService, pick_rate_pair
from app.valuation.adr_ratios import table_adr_ratio
from app.valuation.financial_snapshot import FinancialSnapshot, FinancialSnapshotBuilder
from app.valuation.moat_framework import empty_moat_framework

# v2: net_debt is a required DCF input (no longer coerced to zero debt), the
# FCF-margin clamp no longer flips the sign of a known-negative margin, the
# traceable WACC is preferred over the tag default, and the reverse DCF
# withholds its value when the price is out of bounds. Snapshots persisted
# under v1 were computed with a fabricated net_debt and are not comparable.
MODEL_VERSION = "valuation-engines-v2"


def _cutoff_end_of_day(as_of: date) -> datetime:
    return datetime.combine(as_of, time.max, tzinfo=UTC)


def traceable_wacc(
    db: Session, company: Company, *, as_of: date | None = None
) -> float | None:
    """Return the persisted, traceable WACC for this company, if any.

    ``metric_calculation_service`` / ``WaccInputService`` already compute a
    dated, sourced WACC (risk-free + ERP + beta + capital-structure weights).
    The valuation engines must prefer it over the tag-based policy default so
    the same company is not discounted at 10% and 6.2% depending on which
    module answers.
    """
    conditions = [
        CalculatedMetric.company_id == company.id,
        CalculatedMetric.metric == "wacc",
        CalculatedMetric.status == "ok",
        CalculatedMetric.value.is_not(None),
    ]
    if as_of is not None:
        # Con cutoff, un WACC calculado DESPUES de esa fecha es lookahead.
        conditions.append(CalculatedMetric.created_at <= _cutoff_end_of_day(as_of))
    metric = db.scalar(
        select(CalculatedMetric)
        .where(*conditions)
        .order_by(
            CalculatedMetric.fiscal_year.desc().nullslast(),
            desc(CalculatedMetric.created_at),
        )
        .limit(1)
    )
    if metric is None or metric.value is None:
        return None
    value = float(metric.value)
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        return None
    return value


def clamp_fcf_margin(margin: float, *, ceiling: float) -> tuple[float, bool]:
    """Clamp a known FCF margin without ever flipping its sign.

    A negative FCF margin is a *known fact* (the company burns cash), not a
    degenerate input, so it is preserved. Only the ceiling is applied.
    """
    clamped = min(margin, ceiling)
    return clamped, clamped != margin


# A fact's `shares_diluted` comes from the filing in ORDINARY shares while the
# quote is an ADR price. Dividing one by the other is an N-times error, so the
# ratio has to be explicit. It is encoded in factor_tags as "adr:N" (N ordinary
# shares per ADR) to avoid a schema change; a company tagged "adr" without a
# ratio is refused instead of being valued at the wrong multiple.
ADR_TAG_PREFIX = "adr:"


def adr_ratio(company: Company) -> float | None:
    """Ordinary shares represented by one ADR, or ``None`` if not applicable.

    Precedencia: la etiqueta ``adr:N`` de ``factor_tags`` y, si no la hay, la
    tabla citada de :mod:`app.valuation.adr_ratios` (BABA 8, TM 10, TSM 5...).
    Una etiqueta mal formada (``adr:0``, ``adr:x``) o dos ratios distintos
    devuelven None aunque la tabla tenga fila: un dato contradictorio no se
    tapa con la tabla.
    """
    ratios: set[float] = set()
    for tag in company.factor_tags or []:
        text = str(tag).strip().lower()
        if text.startswith(ADR_TAG_PREFIX):
            try:
                ratio = float(text[len(ADR_TAG_PREFIX):])
            except ValueError:
                return None
            if not math.isfinite(ratio) or ratio <= 0:
                return None
            ratios.add(ratio)
    if ratios:
        return next(iter(ratios)) if len(ratios) == 1 else None
    row = table_adr_ratio(company.ticker)
    return float(row.ordinary_per_adr) if row is not None else None


def is_adr_without_ratio(company: Company) -> bool:
    """True for any ADR marker (bare ``adr`` or ``adr:N``) with no usable ratio.

    A malformed ratio must refuse too: falling back to "no ratio" would let an
    ``adr:0`` slip through as if the company were not an ADR.
    """
    tags = {str(tag).strip().lower() for tag in (company.factor_tags or [])}
    is_adr = "adr" in tags or any(tag.startswith(ADR_TAG_PREFIX) for tag in tags)
    return is_adr and adr_ratio(company) is None


def adr_comparable_price(
    company: Company, current_price: float | None
) -> tuple[float | None, float | None]:
    """Return ``(comparable_price, ratio)`` for ADR-aware price comparison.

    ``comparable_price`` is the price per ordinary share (``current_price / ratio``)
    when the company is an ADR with a usable ratio, otherwise ``current_price``.
    """
    ratio = adr_ratio(company)
    if ratio and current_price:
        return current_price / ratio, ratio
    return current_price, ratio


@dataclass
class ValuationContext:
    db: Session
    company: Company
    snapshot: FinancialSnapshot
    current_price: float | None
    engine_key: str
    # Cutoff point-in-time (None = vigente). Los inputs con marca de tiempo
    # (WACC trazable) solo cuentan si existian a esa fecha.
    as_of: date | None = None
    # Fecha del precio del modelo: los splits posteriores no cuentan al poner
    # acciones y magnitudes por accion en la base del precio.
    price_as_of: date | None = None

    @property
    def split_cutoff(self) -> date | None:
        return self.price_as_of or self.as_of


def insufficient_result(
    *,
    ticker: str,
    model_type: str,
    engine_key: str,
    current_price: float | None,
    missing_inputs: list[str],
    reason: str,
    snapshot: FinancialSnapshot | None = None,
    extra_trace: dict | None = None,
) -> dict:
    trace: dict[str, Any] = {
        "method": model_type,
        "engine": engine_key,
        "input_source": "insufficient_data",
        "publishable": False,
        "status": "insufficient_data",
        "missing_inputs": missing_inputs,
        "reason": reason,
        "model_version": MODEL_VERSION,
        "fact_ids": snapshot.fact_ids() if snapshot else {},
        "periods": snapshot.periods() if snapshot else {},
        "snapshot": {
            "as_of": snapshot.as_of_period if snapshot else None,
            "income_statement": snapshot.income_statement if snapshot else None,
            "balance_sheet": snapshot.balance_sheet if snapshot else None,
            "shares": snapshot.shares_period if snapshot else None,
            "warnings": snapshot.warnings if snapshot else [],
            "excluded_inputs": list(snapshot.excluded_present) if snapshot else [],
        },
    }
    if extra_trace:
        trace.update(extra_trace)

    return {
        "ticker": ticker,
        "model_type": model_type,
        "status": "insufficient_data",
        "publishable": False,
        "current_price": current_price,
        "bear_value": None,
        "base_value": None,
        "bull_value": None,
        "expected_value": None,
        "margin_of_safety": None,
        "missing_inputs": missing_inputs,
        "excluded_inputs": list(snapshot.excluded_present) if snapshot else [],
        "reverse_dcf": {},
        "sensitivity": {"rows": []},
        "trace": trace,
        "moat": empty_moat_framework(
            # company fields filled by caller via extra if needed
            "",
            [],
            [],
        ),
    }


class ValuationEngine(ABC):
    key: str = "base"

    @abstractmethod
    def value(self, context: ValuationContext) -> dict:
        raise NotImplementedError

    def currency_input_units(self, context: ValuationContext) -> list[str | None]:
        """Unidades de los hechos monetarios que el motor lee FUERA del snapshot.

        El filtro de divisa del servicio solo ve el snapshot. Un motor que valora
        con otros hechos (NAV publicado, segmentos) los declara aqui para que el
        precio se convierta a su divisa, o la valoracion se bloquee si no hay
        tipo de cambio.
        """
        return []

    def build_context(
        self,
        db: Session,
        company: Company,
        current_price: float | None,
        as_of: date | None = None,
        *,
        price_as_of: date | None = None,
    ) -> ValuationContext:
        # El corte viaja al snapshot: solo hechos publicados (filed) hasta
        # as_of entran en la valoracion (V1). Sin as_of, comportamiento actual.
        # price_as_of: fecha del precio, para poner las acciones en su base.
        snapshot = FinancialSnapshotBuilder().build(
            db, company, as_of=as_of, price_as_of=price_as_of
        )
        return ValuationContext(
            db=db,
            company=company,
            snapshot=snapshot,
            current_price=current_price,
            engine_key=self.key,
            as_of=as_of,
            price_as_of=price_as_of,
        )


def context_split_cutoff(context: Any) -> date | None:
    """Fecha del precio (o del as_of) de un contexto; None = hoy.

    Tolera contextos duck-typed (tests, llamadas directas a un motor)."""
    return getattr(context, "price_as_of", None) or getattr(context, "as_of", None)


def default_growth(company: Company) -> float:
    """Crecimiento de ingresos por defecto cuando el snapshot no trae ``revenue_growth``.

    Supuesto por tags: pre-FCF/speculative 20%, software/IA 10%,
    commodities 4%, resto 7%. El motor lo acota a [-15%, +45%]
    (+60% en pre-revenue).
    """
    tags = company.factor_tags or []
    if "pre_fcf" in tags or "speculative" in tags:
        return 0.20
    if "software" in tags or "ai" in tags:
        return 0.10
    if "commodities" in tags:
        return 0.04
    return 0.07


def default_wacc(company: Company) -> float:
    """WACC por defecto (fuente ``tag_default`` en el trace).

    Supuesto por tags: pre-FCF/speculative 13%, commodities/china 11%,
    quality 8.5%, resto 10%. El DCF exige ``WACC > crecimiento terminal``;
    los escenarios lo mueven +2pp (bear) / −1pp (bull, con suelo).
    """
    tags = company.factor_tags or []
    if "pre_fcf" in tags or "speculative" in tags:
        return 0.13
    if "commodities" in tags or "china" in tags:
        return 0.11
    if "quality" in tags:
        return 0.085
    return 0.10


def default_terminal_growth(company: Company) -> float:
    """Crecimiento terminal por defecto (Gordon en el valor terminal).

    Supuesto por tags: commodities 1.5%, pre-FCF/speculative 2.5%,
    resto 3%. Fijo en los tres escenarios; el DCF lo valida con
    ``WACC > terminal``.
    """
    tags = company.factor_tags or []
    if "commodities" in tags:
        return 0.015
    if "pre_fcf" in tags or "speculative" in tags:
        return 0.025
    return 0.03


def margin_of_safety(expected_value: float | None, current_price: float | None) -> float | None:
    """Margen de seguridad estándar: (V − P) / V.

    Es el descuento del precio sobre el valor estimado (Graham, *The
    Intelligent Investor*, cap. 20; Klarman, *Margin of Safety*). No es el
    potencial de revalorización V/P − 1, que la versión anterior calculaba
    con el mismo nombre: con V = 130 y P = 100, el margen es 23,1 % y el
    potencial 30 %. El signo coincide en los dos (V > P ⇔ margen > 0), así
    que el veredicto atractivo/caro no cambia de lado. Con V ≤ 0 el cociente
    no tiene lectura y se devuelve None (N/D).
    """
    if expected_value is None or current_price is None:
        return None
    # NaN/inf (un 0/0 de pandas, un "Infinity" en un JSON) no son cifras: N/D,
    # nunca un margen NaN que pasa los filtros "> 0" en silencio.
    if not (math.isfinite(expected_value) and math.isfinite(current_price)):
        return None
    if current_price <= 0 or expected_value <= 0:
        return None
    return (expected_value - current_price) / expected_value


def upside_from_margin_of_safety(margin: float) -> float:
    """Potencial V/P − 1 equivalente a un margen (V − P)/V: 1/(1 − m) − 1."""
    return 1 / (1 - margin) - 1


def margin_of_safety_from_upside(upside: float) -> float:
    """Margen (V − P)/V equivalente a un potencial V/P − 1: 1 − 1/(1 + u)."""
    return 1 - 1 / (1 + upside)


def margin_of_safety_reference(valuation: dict[str, Any]) -> tuple[str, float] | None:
    """Valor contra el que se calculo ``margin_of_safety`` y su etiqueta.

    Todos los motores calculan MoS = (valor esperado − precio) / valor
    esperado. Un texto que lo presente «respecto al escenario base» con un MoS
    de valor esperado muestra una cifra que no sale de los numeros citados
    (MSFT con base 309,10 y precio 529,05: el margen respecto a la base es
    (309,10 − 529,05)/309,10 = −71,2 %, no el del valor esperado). Sin valor
    esperado (valoraciones parciales) se cae al escenario base, como antes.
    """
    expected = valuation.get("expected_value")
    if isinstance(expected, (int, float)):
        return "valor esperado", float(expected)
    base = valuation.get("base_value")
    if isinstance(base, (int, float)):
        return "escenario base", float(base)
    return None


_SCENARIO_LABEL_ES = {"bear": "bajista", "base": "base", "bull": "alcista"}


def num_es(value: float, digits: int = 2) -> str:
    """Cifra en formato español (coma decimal), sin notación científica."""
    return f"{value:.{digits}f}".replace(".", ",")


def scenario_value_or_nd(
    name: str, value: float | None, *, cause: str | None = None
) -> tuple[float | None, str | None]:
    """(valor a publicar, nota) con la convención d2656966: un valor por acción
    <= 0 no es una valoración publicable (igual que un P/E negativo no es un
    múltiplo): el escenario sale N/D con explicación, nunca cifra negativa.

    El bruto debe seguir ponderando el esperado: excluirlo lo inflaría y
    rompería el orden bear <= base."""
    if value is not None and value > 0:
        return value, None
    label = _SCENARIO_LABEL_ES.get(name, name)
    if value is None:
        return None, f"Escenario {label}: el modelo no produjo un valor por acción calculable: N/D."
    detail = f" {cause}" if cause else " Con los supuestos de este escenario"
    return None, (
        f"Escenario {label}:{detail} el valor por acción sale {num_es(value)}. "
        "Una cifra negativa no es una valoración publicable: N/D. "
        "El valor esperado sí la tiene en cuenta."
    )


def expected_value_or_nd(expected_raw: float) -> tuple[float | None, str | None]:
    """Mismo criterio para el esperado ponderado: <= 0 es N/D explicado."""
    if expected_raw > 0:
        return expected_raw, None
    return None, (
        "El valor esperado (ponderado por probabilidad) sale "
        f"{num_es(expected_raw)} con estos supuestos: N/D, no se publica una cifra negativa."
    )


def normalize_scenario_display(
    scenario_values: dict[str, float | None],
    *,
    causes: dict[str, str] | None = None,
    scenario_traces: dict | None = None,
) -> tuple[dict[str, float | None], dict[str, str]]:
    """(valores a publicar, notas N/D) para bear/base/bull.

    ``scenario_values`` conserva los brutos (el esperado se pondera con ellos).
    Si se pasan ``scenario_traces`` (dicts por escenario con ``value_per_share``),
    el bruto se mueve a ``value_per_share_raw`` y la nota a ``value_note``."""
    display: dict[str, float | None] = {}
    notes: dict[str, str] = {}
    for name, raw in scenario_values.items():
        display[name], note = scenario_value_or_nd(
            name, raw, cause=(causes or {}).get(name)
        )
        if note is None:
            continue
        notes[name] = note
        if scenario_traces is not None and name in scenario_traces:
            scenario_traces[name]["value_per_share_raw"] = raw
            scenario_traces[name]["value_per_share"] = None
            scenario_traces[name]["value_note"] = note
    return display, notes


def apply_publication_blockers(result: dict[str, Any]) -> dict[str, Any]:
    """A valuation with publication blockers is not a publishable valuation.

    The engines already compute their blockers, but until now they only
    *reported* them: a DCF discounted at a tag-default WACC carried
    ``traceable_wacc`` in its trace and was still published as a final
    valuation, so the one input that decides the discount rate was an
    assumption nobody could trace back to a dated source. The numbers stay in
    the result, because an orientation with its assumptions named is worth more
    than a refusal; what changes is the label, which is the part every consumer
    (thesis, red team, snapshot, persistence) treats as "this is final".
    """
    blockers = [
        str(item).strip()
        for item in (result.get("publication_blockers") or [])
        if str(item).strip()
    ]
    if not blockers:
        return result
    result["publication_blockers"] = blockers
    if result.get("publishable"):
        result["publishable"] = False
        if result.get("status") == "ok":
            result["status"] = "partial"
    trace = result.get("trace")
    if isinstance(trace, dict):
        trace["publishable"] = result.get("publishable")
        trace["status"] = result.get("status")
        trace["publication_blockers"] = blockers
        trace.setdefault(
            "notice",
            "Valuation computed on inputs that are not traceable to a dated "
            "source; the numbers are an orientation, not a final valuation.",
        )
    return result


def resolve_rates(db, company, *, as_of: date | None = None) -> tuple[float, str, float, str, list[str]]:
    """(wacc, wacc_source, terminal, terminal_source, inferidos_descartados).

    Prioridad: CalculatedMetric trazable > InferredInput (base + URLs) > tags.
    Un par que no deje spread minimo wacc - g descarta el inferido (nunca
    llega a run_dcf, que lanzaria ValueError). ``db=None`` solo en unit tests.
    """
    wacc_default = default_wacc(company)
    terminal_default = default_terminal_growth(company)
    if db is None:
        return wacc_default, "tag_default", terminal_default, "tag_default", []
    service = InferredInputService()
    traceable = traceable_wacc(db, company, as_of=as_of)
    inferred_w = service.latest_valid(db, company.id, "wacc") if traceable is None else None
    inferred_g = service.latest_valid(db, company.id, "terminal_growth")
    if traceable is not None:
        wacc, wacc_source = traceable, "calculated_metric"
    elif inferred_w is not None:
        wacc, wacc_source = float(inferred_w.value), "inferred_input"
    else:
        wacc, wacc_source = wacc_default, "tag_default"
    if inferred_g is not None:
        terminal, terminal_source = float(inferred_g.value), "inferred_input"
    else:
        terminal, terminal_source = terminal_default, "tag_default"
    wacc, terminal, dropped = pick_rate_pair(
        wacc=wacc,
        wacc_inferred=wacc_source == "inferred_input",
        terminal=terminal,
        terminal_inferred=terminal_source == "inferred_input",
        default_wacc_value=wacc_default,
        default_terminal_value=terminal_default,
    )
    if "wacc" in dropped:
        wacc_source = "tag_default"
    if "terminal_growth" in dropped:
        terminal_source = "tag_default"
    return wacc, wacc_source, terminal, terminal_source, dropped
