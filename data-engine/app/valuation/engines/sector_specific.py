"""Dedicated fact-driven valuation engines for financials and REITs.

Anclaje temporal: el balance (tangible book / book value / NOI del ejercicio) es
el *ancla* del motor, y el resto de magnitudes de estados financieros se resuelven
en ese mismo ejercicio. Una entrada que sólo existe en otro año se declara
ausente en vez de mezclarse: ``book_per_share`` con acciones de otro ejercicio no
es un dato, es un cociente entre dos fechas, y un P/B justificado construido
sobre un ROE de dos años con el libro de otro aplica un flujo de retorno a un
stock que ese retorno no midió. El ancla y los periodos excluidos por
desalineación viajan en el trace para que la negativa sea auditable.

``cost_of_equity`` y ``cap_rate`` son observaciones de mercado, no cifras de
estados financieros: no son stocks ni flujos de un ejercicio, así que se toman
en su último periodo y su periodo viaja en el trace en lugar de forzarlos al
año del balance.

Supuestos por motor (todos con inputs 100% de FinancialFact, sin bootstrap):

- BankValuationEngine: modelo de price-to-book justificado ``P/B = (ROE - g) /
  (CoE - g)`` con P/B acotado a [0.25, 3.0]. Supuestos: ``book_per_share`` =
  tangible book / acciones diluidas del mismo ejercicio; ``g`` = crecimiento del
  book value **declarado** (financial_facts del ancla; si falta, el motor se
  niega, porque un ``g = 0`` inventado mueve el P/B hasta un 36%); escenarios
  bear/base/bull mueven ROE ±(2.5-3pp), CoE ∓(1-1.5pp) y g ∓1pp/+0.5pp.
  Sensibilidad: tabla de 3 filas variando CoE (-1pp / base / +1.5pp).
- InsurerValuationEngine: mismo P/B justificado multiplicado por un factor de
  calidad de suscripción ``clamp(1 + (1 - combined_ratio) * 2, 0.75, 1.25)``,
  con las mismas reglas de anclaje y de ``g`` declarado. Supuestos: ROE, CoE y
  combined ratio de facts; escenarios mueven ROE ±(2-2.5pp), CoE ∓(1-1.5pp) y
  combined ratio ±(2.5-3pp). Sensibilidad: tabla de 3 filas variando CoE.
- ReitValuationEngine: NAV directo ``(NOI / cap_rate - net_debt) / acciones``.
  Supuestos: cap rate de mercado de facts (debe ser > 0); NOI, net debt y
  acciones del mismo ejercicio; escenarios mueven NOI ×(0.94/1.0/1.06) y cap
  rate ∓(50-75bp). Sensibilidad: tabla de 3 filas variando cap rate
  (-50bp / base / +75bp).

Probabilidades: ``source_confidence_plus_company_quality`` — peso base de la
confianza media de los facts de origen más una señal direccional propia de
cada motor (spread ROE-CoE en bancos, 1-combined_ratio en aseguradoras,
-cap_rate en REITs).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import desc, select

from app.models import FinancialFact
from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    adr_ratio,
    context_split_cutoff,
    insufficient_result,
    is_adr_without_ratio,
    margin_of_safety,
)
from app.valuation.fact_reference import split_scaled_value, usable_fact
from app.valuation.moat_framework import empty_moat_framework

# Nombre de la regla de coherencia temporal, para que el trace diga qué se
# aplicó en vez de dejar que el lector lo infiera del resultado.
ANCHOR_POLICY = "statement_metrics_share_one_fiscal_period"
# Periodos alternativos de un input excluido que se exponen en el trace:
# los suficientes para diagnosticar una ingesta desalineada sin inflarlo.
MAX_EXPOSED_PERIODS = 3


@dataclass(frozen=True)
class SourcedValue:
    value: float
    fact_id: int
    period: str
    confidence: float


@dataclass(frozen=True)
class PeriodAnchor:
    """Ejercicio que da nombre a la valoración de un motor.

    Es el balance: un *stock* medido en una fecha. Sólo él puede arbitrar el
    snapshot, porque el resto de magnitudes (acciones, ROE, growth, combined
    ratio, net debt) no significan nada por separado del periodo que comparten
    con él. El libro es un instant y el ROE un ratio de flujo: multiplicarlos
    sólo es legítimo si el flujo termina en la fecha del instant.
    """

    metric: str
    fact_id: int
    period: str
    fiscal_year: int | None
    fiscal_quarter: str | None

    def as_trace(self) -> dict:
        return {
            "metric": self.metric,
            "fact_id": self.fact_id,
            "period": self.period,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
        }


@dataclass(frozen=True)
class ResolvedInputs:
    values: dict[str, SourcedValue | None]
    anchor: PeriodAnchor | None
    dropped: dict[str, list[dict]]
    market_rates: dict[str, dict]

    def as_trace(self) -> dict:
        return {
            "period_anchor_policy": ANCHOR_POLICY,
            "period_anchor": self.anchor.as_trace() if self.anchor else None,
            "inputs_excluded_out_of_anchor_period": self.dropped,
            "market_rates_not_period_anchored": self.market_rates,
        }


def _period_kind(fact: FinancialFact) -> str:
    """``FY`` / ``Q`` / ``TTM``: un anual no es intercambiable con un trimestre."""
    text = (fact.period or "").upper()
    if "TTM" in text:
        return "TTM"
    quarter = (fact.fiscal_quarter or "").upper()
    if quarter and quarter not in {"FY", "ANNUAL"}:
        return "Q"
    if text.startswith("Q") or any(token in text for token in ("Q1", "Q2", "Q3", "Q4")):
        return "Q"
    return "FY"


def _same_anchor_period(anchor: FinancialFact, candidate: FinancialFact) -> bool:
    """True si ``candidate`` mide lo mismo que el ancla, en el mismo ejercicio."""
    if _period_kind(anchor) != _period_kind(candidate):
        return False
    if anchor.fiscal_year is not None and candidate.fiscal_year is not None:
        return candidate.fiscal_year == anchor.fiscal_year
    return (anchor.period or "").upper() == (candidate.period or "").upper()


def _sourced(fact: FinancialFact | None) -> SourcedValue | None:
    if fact is None:
        return None
    return SourcedValue(float(fact.value), fact.id, fact.period, float(fact.confidence))


def _fact_trace(fact: FinancialFact) -> dict:
    return {
        "fact_id": fact.id,
        "metric": fact.metric,
        "period": fact.period,
        "fiscal_year": fact.fiscal_year,
        "fiscal_quarter": fact.fiscal_quarter,
    }


def _resolve_inputs(
    context: ValuationContext,
    *,
    anchor_metrics: tuple[str, ...],
    inputs: dict[str, tuple[str, ...]],
    market_rates: tuple[str, ...] = (),
) -> ResolvedInputs:
    """Resuelve el snapshot completo del motor en una consulta y lo ancla a un periodo.

    Antes cada motor hacía cinco ``_latest`` independientes, y cada uno devolvía la
    fila más reciente *entre todos sus alias*: tangible book de FY2024 con
    acciones de FY2025 (tras una recompra) salía como ``book_per_share`` legítimo,
    y el alias de ROE podía traer el retorno de un año aplicado al libro de otro.
    El resultado era ``status="ok"``, ``publishable=True`` y
    ``missing_inputs=[]``: un número sin ninguna señal de estar mezclado.

    Aquí el conjunto se resuelve de una vez, el ancla es el último balance
    disponible y cada entrada se busca **en ese ejercicio**: si no existe ahí se
    devuelve ``None`` y el motor cae en el ``insufficient_result`` que ya
    existía, declarando el input como ausente en vez de sustituirlo por el dato
    de otro año. Los periodos encontrados y descartados se exponen en el trace.

    ``market_rates`` son observaciones de mercado (coste de equity, cap rate):
    no son stocks ni flujos de un ejercicio, así que se toman en su último
    periodo y su periodo se expone en el trace en vez de anclarlas al balance.
    """
    aliases = {alias for group in inputs.values() for alias in group} | set(anchor_metrics)
    rows = [
        row
        for row in context.db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == context.company.id,
                FinancialFact.metric.in_(sorted(aliases)),
            )
            .order_by(
                FinancialFact.fiscal_year.desc().nullslast(),
                desc(FinancialFact.created_at),
            )
        ).all()
        # Misma frontera que el snapshot: un hecho en cuarentena (p. ej.
        # acciones derivadas de un BPA ESEF en conflicto de escala) no es un
        # input del ejercicio; es ausente y el motor cae en insufficient.
        if usable_fact(row)
    ]
    anchor_row = next((row for row in rows if row.metric in anchor_metrics), None)
    anchor = (
        PeriodAnchor(
            metric=anchor_row.metric,
            fact_id=anchor_row.id,
            period=anchor_row.period,
            fiscal_year=anchor_row.fiscal_year,
            fiscal_quarter=anchor_row.fiscal_quarter,
        )
        if anchor_row
        else None
    )
    values: dict[str, SourcedValue | None] = {}
    dropped: dict[str, list[dict]] = {}
    rate_traces: dict[str, dict] = {}
    for key, group in inputs.items():
        # `rows` viene ordenado por ejercicio/creación, así que este listado
        # conserva el "último disponible" para cualquier clave.
        pool = [row for row in rows if row.metric in group]
        if key in market_rates or anchor_row is None:
            chosen = pool[0] if pool else None
            if chosen is not None:
                rate_traces[key] = _fact_trace(chosen)
        else:
            chosen = next((row for row in pool if _same_anchor_period(anchor_row, row)), None)
            if chosen is None and pool:
                dropped[key] = [_fact_trace(row) for row in pool[:MAX_EXPOSED_PERIODS]]
        sourced = _sourced(chosen)
        if sourced is not None and chosen is not None:
            # Acciones/por accion del ejercicio frente al precio de hoy: un split
            # posterior al cierre cambia la escala (misma regla que el DCF).
            scaled = split_scaled_value(
                context.db, context.company.id, chosen, cutoff=context_split_cutoff(context)
            )
            if scaled != sourced.value:
                sourced = replace(sourced, value=scaled)
        values[key] = sourced
    return ResolvedInputs(values=values, anchor=anchor, dropped=dropped, market_rates=rate_traces)


def _probabilities(values: list[SourcedValue], directional_quality: float = 0.0) -> dict[str, float]:
    confidence = sum(value.confidence for value in values) / len(values)
    base = max(0.40, min(0.64, 0.38 + confidence * 0.26))
    upside_share = max(0.35, min(0.65, 0.50 + directional_quality * 0.25))
    tail = 1.0 - base
    bull = tail * upside_share
    return {"bear": tail - bull, "base": base, "bull": bull}


def _pb_sensitivity_rows(
    *,
    book_per_share: float,
    roe: float,
    cost_of_equity: float,
    growth: float,
    underwriting_factor: float = 1.0,
) -> dict:
    """Tabla de sensibilidad 1-D sobre el coste del equity (±100bp/±150bp).

    Revalúa el P/B justificado ``(ROE - g) / (CoE - g)`` acotado a [0.25, 3.0]
    en tres puntos de CoE; el resto de supuestos (ROE, g, factor de
    suscripción en aseguradoras) se mantiene en base. Devuelve el formato
    estándar ``{"rows": [...], "trace": {...}}``.
    """
    rows = []
    for label, cost in (
        ("low_coe", max(cost_of_equity - 0.01, growth + 0.005)),
        ("base_coe", cost_of_equity),
        ("high_coe", cost_of_equity + 0.015),
    ):
        justified_pb = max(0.25, min(3.0, (roe - growth) / (cost - growth)))
        rows.append(
            {
                "scenario": label,
                "cost_of_equity": cost,
                "roe": roe,
                "growth": growth,
                "justified_pb": justified_pb,
                "value_per_share": book_per_share * justified_pb * underwriting_factor,
            }
        )
    return {"rows": rows, "trace": {"method": "pb_cost_of_equity_sensitivity"}}


def _reit_sensitivity_rows(
    *,
    noi: float,
    cap_rate: float,
    net_debt: float,
    shares: float,
) -> dict:
    """Tabla de sensibilidad 1-D sobre el cap rate (-50bp / base / +75bp).

    Revalúa ``(NOI / cap_rate - net_debt) / acciones`` con el NOI base;
    el suelo de cap rate es 0.001 para evitar división por cero.
    """
    rows = []
    for label, cap in (
        ("low_cap_rate", max(cap_rate - 0.005, 0.001)),
        ("base_cap_rate", cap_rate),
        ("high_cap_rate", cap_rate + 0.0075),
    ):
        rows.append(
            {
                "scenario": label,
                "cap_rate": cap,
                "noi": noi,
                "value_per_share": max(0.0, noi / cap - net_debt) / shares,
            }
        )
    return {"rows": rows, "trace": {"method": "reit_cap_rate_sensitivity"}}


def _adr_refusal(context: ValuationContext, engine_key: str) -> dict | None:
    """Mismo rechazo que el DCF: libro y acciones vienen en ordinarias y el
    precio es el del ADR; sin ratio, valor y precio no son comparables."""
    if not is_adr_without_ratio(context.company):
        return None
    return insufficient_result(
        ticker=context.company.ticker,
        model_type=context.company.valuation_model,
        engine_key=engine_key,
        current_price=context.current_price,
        missing_inputs=["adr_ratio"],
        reason=(
            f"{context.company.ticker} is quoted as an ADR but the ordinary-shares-per-ADR "
            "ratio is unknown, so per-share book/NAV and the quoted price are not on the "
            "same basis."
        ),
        snapshot=context.snapshot,
    )


def _result(
    context: ValuationContext,
    *,
    engine_key: str,
    scenario_values: dict[str, float],
    probabilities: dict[str, float],
    fact_ids: dict[str, int],
    periods: dict[str, str],
    assumptions: dict,
    sensitivity: dict | None = None,
    period_anchor: dict | None = None,
) -> dict:
    expected = sum(scenario_values[name] * probabilities[name] for name in scenario_values)
    company = context.company
    sensitivity = sensitivity if sensitivity is not None else {"rows": []}
    trace = {
        "method": company.valuation_model,
        "engine": engine_key,
        "input_source": "financial_facts",
        "publishable": True,
        "status": "ok",
        "model_version": MODEL_VERSION,
        "scenario_style": f"{engine_key}_causal",
        "fact_ids": fact_ids,
        "periods": periods,
        "assumptions": assumptions,
        "probabilities": probabilities,
        "probability_method": "source_confidence_plus_company_quality",
    }
    # El ancla viaja también en el resultado publicado: sin ella, un lector del
    # snapshot no puede saber que libro, acciones y ROE son del mismo ejercicio.
    if period_anchor:
        trace.update(period_anchor)
    # Valor por acción ORDINARIA (libro / acciones del filing); un ADR cotiza
    # N ordinarias. El margen se mide contra el precio por ordinaria, como en
    # standard_dcf/utilities; antes se comparaba con el precio del ADR (error xN).
    ratio = adr_ratio(company)
    price = context.current_price
    comparable_price = price / ratio if (ratio and price) else price
    trace["adr_ratio"] = ratio
    trace["comparable_price"] = comparable_price
    return {
        "ticker": company.ticker,
        "model_type": company.valuation_model,
        "status": "ok",
        "publishable": True,
        "current_price": context.current_price,
        "bear_value": scenario_values["bear"],
        "base_value": scenario_values["base"],
        "bull_value": scenario_values["bull"],
        "expected_value": expected,
        "margin_of_safety": margin_of_safety(expected, comparable_price),
        "missing_inputs": [],
        "adr_ratio": ratio,
        "value_per_share_basis": "ordinary_share",
        "listed_share_values": (
            {name: value * ratio for name, value in (*scenario_values.items(), ("expected", expected))}
            if ratio
            else None
        ),
        "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
        "reverse_dcf": {},
        "sensitivity": sensitivity,
        "moat": empty_moat_framework(
            company.company_type,
            company.factor_tags or [],
            company.special_risks or [],
        ),
        "trace": trace,
    }


class BankValuationEngine(ValuationEngine):
    """Bancos: P/B justificado sobre tangible book value.

    Supuestos: ``P/B = (ROE - g) / (CoE - g)`` acotado a [0.25, 3.0], con
    tangible book, acciones, ROTE/ROE y crecimiento del book del **mismo
    ejercicio** que el balance (ancla temporal) y ``g`` declarado: sin growth
    de facts el motor se niega, porque un ``g = 0`` supuesto cambia el P/B de
    forma material (con ROE 14% y CoE 10%, 1,40 con g=0 frente a 1,80 con
    g=5%, y el múltiplo se dispara más cuanto más cerca del CoE esté el growth
    real).
    Escenarios bear/base/bull: ROE ∓3pp/+2.5pp, CoE ±1.5pp/∓1pp, g ∓1pp/+0.5pp.
    Sensibilidad: tabla CoE (-100bp / base / +150bp) a ROE y g base.
    """

    key = "bank"

    def value(self, context: ValuationContext) -> dict:
        refused = _adr_refusal(context, self.key)
        if refused is not None:
            return refused
        resolved = _resolve_inputs(
            context,
            anchor_metrics=("tangible_book_value", "tangible_common_equity"),
            inputs={
                "tangible_book_value": ("tangible_book_value", "tangible_common_equity"),
                "shares_diluted": ("shares_diluted",),
                "roe": ("return_on_tangible_equity", "roe"),
                "cost_of_equity": ("cost_of_equity",),
                "book_value_growth": ("book_value_growth", "tangible_book_growth"),
            },
            market_rates=("cost_of_equity",),
        )
        sourced = resolved.values
        missing = [key for key, value in sourced.items() if value is None]
        if missing:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=missing,
                reason=(
                    "Bank valuation requires sourced tangible book, diluted shares, ROTE/ROE, "
                    "cost of equity and book value growth. Every input is resolved in the fiscal "
                    "period of the balance sheet anchor, so a metric that only exists in another "
                    "year counts as missing instead of being crossed into the book value."
                ),
                snapshot=context.snapshot,
                extra_trace=resolved.as_trace(),
            )
        tangible_book = sourced["tangible_book_value"]
        shares = sourced["shares_diluted"]
        roe = sourced["roe"]
        cost_equity = sourced["cost_of_equity"]
        growth = sourced["book_value_growth"]
        assert tangible_book and shares and roe and cost_equity and growth
        growth_value = growth.value
        if cost_equity.value <= growth_value or shares.value <= 0:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=["cost_of_equity_above_book_value_growth"],
                reason="A justified price-to-book model requires cost of equity above sustainable growth.",
                snapshot=context.snapshot,
                extra_trace=resolved.as_trace(),
            )
        book_per_share = tangible_book.value / shares.value
        specs = {
            "bear": (roe.value - 0.03, cost_equity.value + 0.015, growth_value - 0.01),
            "base": (roe.value, cost_equity.value, growth_value),
            "bull": (roe.value + 0.025, cost_equity.value - 0.01, growth_value + 0.005),
        }
        # Every scenario needs cost of equity strictly above its own growth;
        # the bull growth bump alone used to make them equal (division by zero).
        specs = {
            name: (scenario_roe, max(scenario_cost, scenario_growth + 0.005), scenario_growth)
            for name, (scenario_roe, scenario_cost, scenario_growth) in specs.items()
        }
        values = {
            name: book_per_share * max(0.25, min(3.0, (scenario_roe - scenario_growth) / (scenario_cost - scenario_growth)))
            for name, (scenario_roe, scenario_cost, scenario_growth) in specs.items()
        }
        available = [value for value in sourced.values() if value is not None]
        probabilities = _probabilities(available, roe.value - cost_equity.value)
        sensitivity = _pb_sensitivity_rows(
            book_per_share=book_per_share,
            roe=roe.value,
            cost_of_equity=cost_equity.value,
            growth=growth_value,
        )
        return _result(
            context,
            engine_key=self.key,
            scenario_values=values,
            probabilities=probabilities,
            fact_ids={key: value.fact_id for key, value in sourced.items() if value},
            periods={key: value.period for key, value in sourced.items() if value},
            assumptions={
                "book_per_share": book_per_share,
                "scenario_roe_cost_growth": specs,
                "growth_source": "financial_facts",
            },
            sensitivity=sensitivity,
            period_anchor=resolved.as_trace(),
        )


class InsurerValuationEngine(ValuationEngine):
    """Aseguradoras: P/B justificado ajustado por calidad de suscripción.

    Supuestos: ``valor = book/acc × P/B_justificado × factor_suscripción`` con
    ``factor = clamp(1 + (1 - combined_ratio) × 2, 0.75, 1.25)``; book value,
    acciones, ROE, combined ratio y ``g`` del **mismo ejercicio** que el balance
    (ancla temporal) y ``g`` declarado, no 0.0 supuesto. Escenarios: ROE
    ∓2.5pp/+2pp, CoE ±1.5pp/∓1pp, combined ratio ±3pp/∓2.5pp. Sensibilidad:
    tabla CoE a ROE, g y combined ratio base.
    """

    key = "insurer"

    def value(self, context: ValuationContext) -> dict:
        refused = _adr_refusal(context, self.key)
        if refused is not None:
            return refused
        resolved = _resolve_inputs(
            context,
            # total_equity: nombre canonico del hecho reportado SEC
            # (StockholdersEquity); book_value es el mismo stock con otro
            # nombre, asi que el motor lo acepta como alias en vez de pedir
            # una copia derivada del mismo dato.
            anchor_metrics=("book_value", "common_equity", "total_equity"),
            inputs={
                "book_value": ("book_value", "common_equity", "total_equity"),
                "shares_diluted": ("shares_diluted",),
                "roe": ("roe",),
                "cost_of_equity": ("cost_of_equity",),
                "combined_ratio": ("combined_ratio",),
                "book_value_growth": ("book_value_growth",),
            },
            market_rates=("cost_of_equity",),
        )
        sourced = resolved.values
        missing = [key for key, value in sourced.items() if value is None]
        if missing:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=missing,
                reason=(
                    "Insurer valuation requires sourced book value, shares, ROE, cost of equity, "
                    "combined ratio and book value growth. Every input is resolved in the fiscal "
                    "period of the balance sheet anchor, so a metric that only exists in another "
                    "year counts as missing instead of being crossed into the book value."
                ),
                snapshot=context.snapshot,
                extra_trace=resolved.as_trace(),
            )
        book = sourced["book_value"]
        shares = sourced["shares_diluted"]
        roe = sourced["roe"]
        cost_equity = sourced["cost_of_equity"]
        combined_ratio = sourced["combined_ratio"]
        growth = sourced["book_value_growth"]
        assert book and shares and roe and cost_equity and combined_ratio and growth
        growth_value = growth.value
        if shares.value <= 0 or cost_equity.value <= growth_value:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=["valid_shares_and_cost_of_equity_spread"],
                reason="Insurer price-to-book model inputs are economically inconsistent.",
                snapshot=context.snapshot,
                extra_trace=resolved.as_trace(),
            )
        book_per_share = book.value / shares.value
        specs = {
            "bear": (roe.value - 0.025, cost_equity.value + 0.015, combined_ratio.value + 0.03),
            "base": (roe.value, cost_equity.value, combined_ratio.value),
            "bull": (roe.value + 0.02, max(cost_equity.value - 0.01, growth_value + 0.005), combined_ratio.value - 0.025),
        }
        values = {}
        for name, (scenario_roe, scenario_cost, scenario_combined) in specs.items():
            justified_pb = (scenario_roe - growth_value) / (scenario_cost - growth_value)
            underwriting_quality = max(0.75, min(1.25, 1 + (1 - scenario_combined) * 2))
            values[name] = book_per_share * max(0.25, min(3.0, justified_pb)) * underwriting_quality
        available = list(sourced.values())
        probabilities = _probabilities(available, 1 - combined_ratio.value)
        base_uw = max(0.75, min(1.25, 1 + (1 - combined_ratio.value) * 2))
        sensitivity = _pb_sensitivity_rows(
            book_per_share=book_per_share,
            roe=roe.value,
            cost_of_equity=cost_equity.value,
            growth=growth_value,
            underwriting_factor=base_uw,
        )
        return _result(
            context,
            engine_key=self.key,
            scenario_values=values,
            probabilities=probabilities,
            fact_ids={key: value.fact_id for key, value in sourced.items() if value},
            periods={key: value.period for key, value in sourced.items() if value},
            assumptions={
                "book_per_share": book_per_share,
                "scenario_roe_cost_combined_ratio": specs,
                "growth_source": "financial_facts",
            },
            sensitivity=sensitivity,
            period_anchor=resolved.as_trace(),
        )


class ReitValuationEngine(ValuationEngine):
    """REITs: NAV directo por capitalización de NOI.

    Supuestos: ``valor/acc = max(0, NOI / cap_rate - net_debt) / acciones``
    con cap rate de mercado de facts (> 0) y NOI, net debt y acciones del
    **mismo ejercicio** (ancla temporal: el NOI cierra el NAV contra el balance
    de esa fecha, así que un net debt de otro año resta deuda que no es la de
    ese NAV). Escenarios: NOI ×(0.94/1.0/1.06), cap rate +75bp/base/−50bp (suelo
    0.001). Sensibilidad: tabla cap rate (-50bp / base / +75bp) a NOI base.
    """

    key = "reit"

    def value(self, context: ValuationContext) -> dict:
        refused = _adr_refusal(context, self.key)
        if refused is not None:
            return refused
        resolved = _resolve_inputs(
            context,
            anchor_metrics=("net_operating_income", "noi"),
            inputs={
                "net_operating_income": ("net_operating_income", "noi"),
                "cap_rate": ("capitalization_rate", "cap_rate"),
                "net_debt": ("net_debt",),
                "shares_diluted": ("shares_diluted",),
            },
            market_rates=("cap_rate",),
        )
        sourced = resolved.values
        missing = [key for key, value in sourced.items() if value is None]
        if missing:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=missing,
                reason=(
                    "REIT NAV requires sourced NOI, cap rate, net debt and diluted shares. Net "
                    "debt and shares are resolved in the fiscal period of the NOI anchor, so a "
                    "balance sheet from another year counts as missing instead of being netted "
                    "against this NAV."
                ),
                snapshot=context.snapshot,
                extra_trace=resolved.as_trace(),
            )
        noi = sourced["net_operating_income"]
        cap_rate = sourced["cap_rate"]
        net_debt = sourced["net_debt"]
        shares = sourced["shares_diluted"]
        assert noi and cap_rate and net_debt and shares
        if cap_rate.value <= 0 or shares.value <= 0:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=["positive_cap_rate_and_shares"],
                reason="REIT NAV inputs must be positive.",
                snapshot=context.snapshot,
                extra_trace=resolved.as_trace(),
            )
        specs = {
            "bear": (noi.value * 0.94, cap_rate.value + 0.0075),
            "base": (noi.value, cap_rate.value),
            "bull": (noi.value * 1.06, max(cap_rate.value - 0.005, 0.001)),
        }
        values = {
            name: max(0.0, scenario_noi / scenario_cap_rate - net_debt.value) / shares.value
            for name, (scenario_noi, scenario_cap_rate) in specs.items()
        }
        probabilities = _probabilities(list(sourced.values()), -cap_rate.value)
        sensitivity = _reit_sensitivity_rows(
            noi=noi.value,
            cap_rate=cap_rate.value,
            net_debt=net_debt.value,
            shares=shares.value,
        )
        return _result(
            context,
            engine_key=self.key,
            scenario_values=values,
            probabilities=probabilities,
            fact_ids={key: value.fact_id for key, value in sourced.items() if value},
            periods={key: value.period for key, value in sourced.items() if value},
            assumptions={"scenario_noi_cap_rate": specs, "net_debt": net_debt.value},
            sensitivity=sensitivity,
            period_anchor=resolved.as_trace(),
        )
