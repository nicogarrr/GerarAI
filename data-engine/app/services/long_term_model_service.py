"""Long-term fundamental modelling with explicit evidence and assumption lineage.

This service is intentionally conservative. It can calculate a forward model from
coherent annual facts, but it never fills missing company data with a plausible
number. Policy assumptions (scenario spreads, terminal growth, or a fallback tax
rate) are returned as policy inputs so callers can distinguish them from facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isfinite, sqrt
from statistics import median
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    CalculatedMetric,
    Company,
    CorporateAction,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    Position,
    ThesisChange,
)
from app.services.company_framework import CompanyFramework, resolve_company_framework
from app.services.driver_assumption_service import DriverAssumptionService
from app.services.driver_dimensions import driver_metadata
from app.services.driver_operating_model import DriverOperatingModel
from app.services.fundamental_model_repository import FundamentalModelRepository
from app.services.inferred_input_service import MIN_WACC_TERMINAL_SPREAD, InferredInputService
from app.services.market_opportunity_service import MarketOpportunityEngine
from app.services.number_format import format_percent_es
from app.services.owner_earnings import (
    OWNER_EARNINGS_FORMULA,
    WORKING_CAPITAL_SIGN_CONVENTION,
    owner_earnings,
)
from app.services.split_adjustment import fact_split_factor, split_after_price
from app.valuation.currency import fact_currency, resolve_fx
from app.valuation.engines.base import (
    adr_ratio,
    default_terminal_growth,
    default_wacc,
    is_adr_without_ratio,
)
from app.valuation.reverse_dcf import (
    ReverseDCFInputs,
    growth_sensitivity,
    implied_perpetual_growth,
    solve_required_growth,
    value_split,
)

MODEL_VERSION = "long-term-fundamental-model-v2"
ALGORITHM_VERSION = "driver-formulas-funding-rollforward-v2"
ANNUAL_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "ebitda",
    "net_income",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
    "working_capital",
    "net_debt",
    "shares_diluted",
)
RATIO_METRICS = (
    "gross_margin",
    "operating_margin",
    "ebitda_margin",
    "net_margin",
    "fcf_margin",
    "effective_tax_rate",
)
@dataclass(frozen=True)
class Assumption:
    value: float | None
    unit: str
    source_type: str
    basis: str
    source_fact_ids: list[int]
    confidence: float
    source_urls: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": self.value,
            "unit": self.unit,
            "source_type": self.source_type,
            "basis": self.basis,
            "source_fact_ids": self.source_fact_ids,
            "confidence": self.confidence,
        }
        if self.source_urls:
            # INFERIDO documentado (InferredInput): URLs https de la base.
            out["source_urls"] = list(self.source_urls)
        return out


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _current_price_with_date(
    db: Session, company_id: int
) -> tuple[float | None, str | None, str | None]:
    """Return ``(price, as_of, source)`` for the company's current quote.

    ``MarketPrice`` is the quote table and is preferred, ordered by date. The
    portfolio ``Position.market_price`` is only a holding mark: consulting it
    first (and without an ORDER BY, so non-deterministically when the company
    sits in several portfolios) made the reverse DCF answer "the current price
    requires 3% growth" off a three-year-old purchase price instead of today's
    close.
    """
    market = db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id)
        .order_by(desc(MarketPrice.date))
        .limit(1)
    )
    if market is not None:
        close = _float(market.close)
        if close is not None and close > 0:
            return close, _date_value(market.date), "market_price"

    position = db.scalar(
        select(Position)
        .where(Position.company_id == company_id, Position.market_price.is_not(None))
        .order_by(desc(Position.updated_at))
        .limit(1)
    )
    if position is not None:
        mark = _float(position.market_price)
        if mark is not None and mark > 0:
            return mark, _date_value(position.as_of), "position_mark_fallback"
    return None, None, None


def _unique_ids(*facts: FinancialFact | None, ids: list[int] | None = None) -> list[int]:
    result = list(ids or [])
    for fact in facts:
        if fact is not None and fact.id not in result:
            result.append(fact.id)
    return result


def _fact_evidence(fact: FinancialFact | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {
        "fact_id": fact.id,
        "metric": fact.metric,
        "period": fact.period,
        "fiscal_year": fact.fiscal_year,
        "document_id": fact.source_id,
        "source_type": fact.source_type,
        "confidence": _float(fact.confidence),
        "reported": bool(fact.is_reported),
        "adjusted": bool(fact.is_adjusted),
    }


def _fact_line(
    fact: FinancialFact | None,
    *,
    value: float | None = None,
    unit: str | None = None,
    calculation: str | None = None,
    source_fact_ids: list[int] | None = None,
) -> dict[str, Any]:
    if fact is None and value is None:
        return {
            "value": None,
            "unit": unit or "unknown",
            "status": "insufficient_data",
            "source_fact_ids": source_fact_ids or [],
            "calculation": calculation,
            "evidence": [],
        }
    evidence = [_fact_evidence(fact)] if fact is not None else []
    return {
        "value": value if value is not None else _float(fact.value),
        "unit": unit or (fact.unit if fact is not None else "unknown"),
        "status": "reported" if fact is not None and fact.is_reported else "calculated",
        "source_fact_ids": _unique_ids(fact, ids=source_fact_ids),
        "calculation": calculation,
        "evidence": [item for item in evidence if item is not None],
    }


def _calculated_line(
    value: float | None,
    *,
    unit: str,
    source_fact_ids: list[int],
    calculation: str,
    basis: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "status": "calculated" if value is not None else "insufficient_data",
        "source_fact_ids": source_fact_ids,
        "calculation": calculation,
        "basis": basis,
        "evidence": [],
    }


def _derived_fcf(ocf: FinancialFact | None, capex: FinancialFact | None) -> Decimal | None:
    """Free cash flow derived from the two reported legs: ``operating_cash_flow + capital_expenditure``.

    Capex is an outflow whatever sign it was stored with: OCF - |capex|. Returns ``None`` when either leg is missing or
    unreadable: substituting a silent 0 would publish a cash flow the issuer
    never reported, which is exactly what the reported line's absence was
    telling us.
    """
    operating = _float(ocf.value) if ocf is not None else None
    investing = _float(capex.value) if capex is not None else None
    if operating is None or investing is None:
        return None
    # Capex es salida de caja: un hecho guardado en positivo (sin normalizar)
    # sumaba en vez de restar. Siempre OCF - |capex|.
    return Decimal(str(operating)) - abs(Decimal(str(investing)))


def _is_annual(fact: FinancialFact) -> bool:
    quarter = (fact.fiscal_quarter or "").upper()
    period = (fact.period or "").upper()
    # Periodos «2022-12-31:Q1»: el trimestre va tras los dos puntos, no al inicio.
    period_is_quarter = period.startswith("Q") or bool(re.search(r":Q[1-4]$", period))
    return not quarter.startswith("Q") and not period_is_quarter


def _has_fy_marker(fact: FinancialFact) -> bool:
    """El hecho declara ser el ejercicio completo (no un trimestre suelto).

    Imports antiguos y algunos proveedores dejan filas trimestrales con
    fiscal_year puesto y fiscal_quarter NULL: sin esta marca un trimestre
    viejo podia ganar el ano y el DCF partia de unos "Ingresos" de un solo
    trimestre (caso real AAPL: 117,2B de un Q en vez de 416,16B del FY2025).
    """
    quarter = (fact.fiscal_quarter or "").upper()
    period = (fact.period or "").upper()
    return quarter == "FY" or period.endswith(":FY") or period.startswith("FY")


def _split_events(db: Session, company_id: int) -> list[CorporateAction]:
    return list(db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.company_id == company_id,
            CorporateAction.action_type.in_(["split", "reverse_split"]),
        )
        .order_by(CorporateAction.effective_date)
    ))


def _period_end_date(fact: FinancialFact) -> date | None:
    try:
        return date.fromisoformat((fact.period or "").split(":")[0])
    except ValueError:
        return None


@dataclass(frozen=True)
class _SplitAdjustedFact:
    """Vista de un hecho de recuento de acciones expresado en acciones
    ACTUALES: la SEC no reexpone periodos anteriores a los 2-3 anos del
    filing del split, asi que el 10-K de 2016 de AAPL sigue diciendo 5,5B
    pre-split 4:1 de 2020. Sin ajuste, la serie 2016-2025 finge dilucion
    (+11,8 % anual) cuando hubo recompra neta (22B -> 15,3B). Envuelve el
    hecho original: solo cambia `value`; el resto de atributos (id, period,
    provenance) pasan tal cual."""

    fact: FinancialFact
    value: Decimal
    split_factor: Decimal

    def __getattr__(self, name: str) -> Any:
        return getattr(self.fact, name)


def _driver_gap_reason(key: str, *, formula_input: bool) -> str:
    """Motivo legible de un driver del marco sin dato (sin jerga interna)."""
    if key == "traceable_wacc":
        return "falta un WACC con fuentes (tipo libre de riesgo y beta)"
    if formula_input:
        return (
            "falta una entrada de la fórmula operativa; la proyección usa el "
            "crecimiento histórico de los ingresos"
        )
    return (
        "dato operativo que no figura en los datos XBRL presentados al regulador; "
        "se publica en el texto del informe anual"
    )

@dataclass(frozen=True)
class _SharesOutstandingProxy:
    """Acciones en circulacion al cierre usadas como recuento de acciones de un
    ejercicio en el que el emisor no etiqueta la media ponderada diluida.

    Caso real: KKR dejo de presentar WeightedAverageNumberOfDilutedSharesOutstanding
    (y el BPA diluido) en us-gaap tras su conversion de 2018; solo publica
    CommonStockSharesOutstanding. Sin esto la tesis decia «faltan acciones
    diluidas» con el recuento en el 10-K. Es un hecho reportado de otra
    magnitud (saldo al cierre, sin dilucion potencial), asi que se marca como
    derivado con su formula y nunca sustituye a una media diluida reportada.
    """

    fact: FinancialFact
    derivation: str = (
        "derivado: acciones en circulación al cierre (CommonStockSharesOutstanding); "
        "el emisor no etiqueta la media ponderada diluida de ese ejercicio"
    )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.fact, name)


# Drivers obligatorios que no son un concepto us-gaap pero SI se obtienen por
# una identidad contable a partir de hechos reportados del MISMO ejercicio.
# clave -> (formula legible, metricas de entrada, signo de cada entrada).
DERIVED_DRIVERS: dict[str, tuple[str, tuple[str, ...], tuple[int, ...]]] = {
    "net_operating_income": (
        "lease_income − property_operating_expense − real_estate_tax_expense",
        ("lease_income", "property_operating_expense", "real_estate_tax_expense"),
        (1, -1, -1),
    ),
}


def _with_shares_outstanding_proxies(
    diluted: list[Any], outstanding: list[FinancialFact]
) -> list[Any]:
    """Completa los ejercicios sin media diluida con el saldo al cierre."""
    covered = {
        int(fact.fiscal_year)
        for fact in diluted
        if fact.fiscal_year is not None and _is_annual(fact)
    }
    proxies = [
        _SharesOutstandingProxy(fact=fact)
        for fact in outstanding
        if fact.fiscal_year is not None
        and _is_annual(fact)
        and int(fact.fiscal_year) not in covered
        and fact.value is not None
        and fact.value > 0
    ]
    return list(diluted) + proxies


def _has_unexplained_share_jump(series: list[dict[str, Any]]) -> bool:
    """Salto entre anos consecutivos incompatible con emision/recompra
    organica: tipico de un split (o reverse split) sin CorporateAction
    registrado. Los recuentos de acciones no cambian ~2x en un ano por
    gestion de capital; los splits comunes son 2:1...20:1 (y su inverso).
    Sin el split en BD el CAGR seria un numero enganoso: se degrada a N/D.
    """
    values = [item["value"] for item in series if item.get("value")]
    for previous, current in zip(values, values[1:]):
        if previous <= 0:
            continue
        ratio = current / previous
        if ratio >= 1.8 or ratio <= 1 / 1.8:
            return True
    return False


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _adjust_share_facts(
    facts: list[FinancialFact],
    splits: list[CorporateAction],
    *,
    cutoff: date | None = None,
) -> list[Any]:
    """Multiplica cada recuento historico por el factor acumulado de los
    splits posteriores al cierre de su periodo (ratio = acciones despues /
    antes; los reverse splits llevan ratio < 1 y se tratan igual). Los
    hechos sin fecha de periodo parseable se dejan como estan: ajustar a
    ciegas seria inventar."""
    if not splits:
        return list(facts)
    adjusted: list[Any] = []
    events = [
        (split.effective_date, Decimal(str(split.ratio)))
        for split in splits
        if split.effective_date is not None and split.ratio is not None
    ]
    for fact in facts:
        # Regla unica (fact_split_factor): el recuento de un 10-K publicado
        # DESPUES del split ya viene reexpresado (ASC 260) y no se multiplica
        # otra vez; solo se ajustan las cifras publicadas antes del split.
        factor = fact_split_factor(
            events, period=fact.period, filed=getattr(fact, "filed", None), cutoff=cutoff
        )
        if factor == 1 or fact.value is None:
            adjusted.append(fact)
            continue
        adjusted.append(
            _SplitAdjustedFact(
                fact=fact,
                value=Decimal(fact.value) * factor,
                split_factor=factor,
            )
        )
    return adjusted


class LongTermModelService:
    """Build the evidence-aware long-term model for one company."""

    def build(
        self,
        db: Session,
        company: Company,
        horizon: int = 5,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        horizon = max(5, min(10, int(horizon)))
        framework = resolve_company_framework(company)
        market_metrics = MarketOpportunityEngine.metrics_for_framework(framework)
        driver_metrics = {
            self._metric_key(metric)
            for metric in framework.revenue_drivers + framework.kpis + framework.required_fact_metrics
        }
        fact_cache = {
            metric: self._facts(db, company, metric)
            for metric in set(ANNUAL_METRICS)
            | market_metrics
            | driver_metrics
            | {
                "depreciation_amortization",
                "depreciation_and_amortization",
                "maintenance_capex",
                "change_in_working_capital",
                "common_stock_repurchased",
                "dividends_paid",
                "total_debt",
                "ebitda",
                "total_equity",
                "cash_and_equivalents",
                "income_tax_expense",
                "income_before_tax",
                "shares_outstanding",
            }
            | {metric for _f, inputs, _s in DERIVED_DRIVERS.values() for metric in inputs}
        }
        current_price, market_as_of, market_price_source = self._model_price(db, company)
        splits = _split_events(db, company.id)
        # Ultimo cierre anterior a un split ya efectivo: base desconocida (vieja
        # o ya ajustada por el proveedor). Acciones en la base actual y el
        # precio no se compara (DCF inverso N/D), como en ValuationService.
        price_basis_unknown = split_after_price(
            [
                (split.effective_date, Decimal(str(split.ratio)))
                for split in splits
                if split.effective_date is not None and split.ratio is not None
            ],
            _iso_date(market_as_of),
            date.today(),
        )
        if price_basis_unknown:
            current_price = None
        fact_cache["shares_diluted"] = _adjust_share_facts(
            _with_shares_outstanding_proxies(
                fact_cache["shares_diluted"], fact_cache["shares_outstanding"]
            ),
            splits,
            # Acciones en la base del precio con el que se comparan.
            cutoff=None if price_basis_unknown else _iso_date(market_as_of),
        )
        revenue_history = self._annual_by_year(fact_cache["revenue"])
        years = sorted(revenue_history)
        latest_year = years[-1] if years else None
        # Empresa sin ingresos reportados (pre-revenue, p.ej. biotecnologicas):
        # no hay ancla de ano por ingresos y el DCF no aplica. Antes todo lo
        # que se buscaba "para ese ano" (acciones diluidas, ano fiscal) salia
        # como faltante aunque el dato existiera. El ancla pasa a ser el ultimo
        # ano anual con cualquier hecho, y el unico motivo es la falta de ingresos.
        annual_years_any = sorted(
            {
                int(fact.fiscal_year)
                for facts in fact_cache.values()
                for fact in facts
                if fact.fiscal_year is not None and _is_annual(fact)
            }
        )
        # Sin ingresos anuales pero con anclaje posible. Solo es pre-revenue si no
        # hay NINGUN ingreso (ni trimestral): con ingresos solo trimestrales el
        # motivo honesto es que faltan los anuales.
        no_annual_revenue = not years and bool(annual_years_any)
        pre_revenue = no_annual_revenue and not fact_cache["revenue"]
        anchor_year = latest_year if latest_year is not None else (
            annual_years_any[-1] if no_annual_revenue else None
        )
        history = self._history_rows(fact_cache, years)

        current = history[-1] if history else {
            "period": None,
            "fiscal_year": None,
            "metrics": {},
        }

        assumptions, assumption_meta = self._assumptions(
            db=db,
            fact_cache=fact_cache,
            revenue_history=revenue_history,
            years=years,
            company=company,
        )
        driver_assumptions = DriverAssumptionService().active_overrides(db, company)
        driver_model = self._driver_model(company, framework, fact_cache)
        missing_mandatory_drivers = [
            driver["key"]
            for driver in driver_model
            if driver["required"] and driver["status"] == "missing"
        ]
        driver_preview = (
            DriverOperatingModel().build(
                framework,
                fact_cache,
                latest_year=latest_year,
                horizon=horizon,
                scenario="base",
                assumption_overrides=driver_assumptions,
            )
            if latest_year is not None
            else {
                "status": "missing_formula_inputs",
                "missing_inputs": [] if no_annual_revenue else ["fiscal_year"],
            }
        )
        missing_formula_inputs = list(driver_preview.get("missing_inputs") or [])
        missing_mandatory_drivers = list(
            dict.fromkeys(missing_mandatory_drivers + missing_formula_inputs)
        )
        missing_core = [
            name
            for name, value in (
                ("revenue_history_two_periods", assumptions["revenue_growth"].value),
                ("normalized_fcf_margin", assumptions["fcf_margin"].value),
                ("shares_diluted", self._value_for_year(fact_cache["shares_diluted"], anchor_year)),
            )
            if value is None
        ]
        if no_annual_revenue:
            # Un unico motivo honesto: sin ingresos no hay crecimiento ni margen
            # FCF sobre ingresos. Las acciones solo se listan si de verdad faltan.
            missing_core = [
                "no_revenue_reported" if pre_revenue else "annual_revenue_missing"
            ] + [
                name for name in missing_core if name == "shares_diluted"
            ]

        scenarios: dict[str, Any] = {}
        scenario_specs: list[tuple[str, dict[str, Any]]] = []
        if not missing_core and latest_year is not None:
            scenario_specs = self._scenario_specs(
                assumptions,
                framework=framework,
                missing_mandatory_drivers=missing_mandatory_drivers,
            )
            for name, spec in scenario_specs:
                driver_forecast = DriverOperatingModel().build(
                    framework,
                    fact_cache,
                    latest_year=latest_year,
                    horizon=horizon,
                    scenario=name,
                    assumption_overrides=driver_assumptions,
                )
                forecast = self._forecast(
                    fact_cache=fact_cache,
                    years=years,
                    latest_year=latest_year,
                    horizon=horizon,
                    scenario=name,
                    growth=spec["growth"],
                    fcf_margin=spec["fcf_margin"],
                    wacc=spec["wacc"],
                    assumptions=assumptions,
                    driver_forecast=driver_forecast,
                )
                scenarios[name] = self._scenario_payload(
                    name=name,
                    spec=spec,
                    forecast=forecast,
                    assumptions=assumptions,
                    fact_cache=fact_cache,
                    latest_year=latest_year,
                )
                scenarios[name]["driver_operating_model"] = driver_forecast

        if price_basis_unknown:
            comparable_price, price_basis = None, {
                "price_as_of": market_as_of,
                "missing_inputs": ["price_basis_after_split"],
            }
        else:
            comparable_price, price_basis = self._reverse_dcf_price(
                db, company, fact_cache=fact_cache, source_year=latest_year
            )
        reverse_dcf = self._reverse_dcf(
            current_price=comparable_price,
            assumptions=assumptions,
            fact_cache=fact_cache,
            horizon=horizon,
            source_year=latest_year,
            price_missing=price_basis.get("missing_inputs") or [],
        )
        reverse_dcf["price_basis"] = price_basis

        market_opportunity = MarketOpportunityEngine().build(
            db,
            company,
            framework,
            fact_cache=fact_cache,
            revenue_history=revenue_history,
            base_scenario=scenarios.get("base"),
            reverse_dcf=reverse_dcf,
            horizon=horizon,
        )

        revenue_ceiling = self._market_revenue_ceiling(market_opportunity)
        latest_revenue = self._value_for_year(fact_cache["revenue"], latest_year)
        if scenarios and revenue_ceiling and latest_revenue and latest_year is not None:
            constrained_specs = self._constrain_scenario_growth(
                scenario_specs,
                latest_revenue=latest_revenue,
                revenue_ceiling=revenue_ceiling,
                horizon=horizon,
            )
            if constrained_specs != scenario_specs:
                scenarios = {}
                for name, spec in constrained_specs:
                    driver_forecast = DriverOperatingModel().build(
                        framework,
                        fact_cache,
                        latest_year=latest_year,
                        horizon=horizon,
                        scenario=name,
                        assumption_overrides=driver_assumptions,
                    )
                    forecast = self._forecast(
                        fact_cache=fact_cache,
                        years=years,
                        latest_year=latest_year,
                        horizon=horizon,
                        scenario=name,
                        growth=spec["growth"],
                        fcf_margin=spec["fcf_margin"],
                        wacc=spec["wacc"],
                        assumptions=assumptions,
                        driver_forecast=driver_forecast,
                    )
                    scenarios[name] = self._scenario_payload(
                        name=name,
                        spec=spec,
                        forecast=forecast,
                        assumptions=assumptions,
                        fact_cache=fact_cache,
                        latest_year=latest_year,
                    )
                    scenarios[name]["driver_operating_model"] = driver_forecast
                market_opportunity = MarketOpportunityEngine().build(
                    db,
                    company,
                    framework,
                    fact_cache=fact_cache,
                    revenue_history=revenue_history,
                    base_scenario=scenarios.get("base"),
                    reverse_dcf=reverse_dcf,
                    horizon=horizon,
                )
                market_opportunity["model_constraint"] = {
                    "applied": True,
                    "revenue_ceiling": revenue_ceiling,
                    "source": "minimum sourced future market or bottom-up capacity",
                }

        coverage = self._coverage(history, assumptions, scenarios)
        # Solo los inputs CENTRALES (historial de ingresos, margen FCF,
        # acciones) bloquean el modelo: sin ellos no hay numero. Un KPI
        # operativo del marco sin dato (suscriptores, lanzamientos, AUM...)
        # no cambia la proyeccion, que usa el crecimiento historico; se
        # declara «sin dato (motivo)» en driver_gaps, recorta la probabilidad
        # del escenario base (_scenario_specs) y NO despublica la tesis
        # (27/10/2026: 14 de 19 tesis de Nico salian «sin datos suficientes»
        # por KPIs que no existen en XBRL).
        status = "ok" if not missing_core else "insufficient_data"
        driver_gaps = [
            {
                "key": key,
                "motivo": _driver_gap_reason(key, formula_input=key in missing_formula_inputs),
            }
            for key in missing_mandatory_drivers
        ]
        publication_blockers: list[str] = []
        if assumptions["wacc"].source_type != "calculated_metric":
            publication_blockers.append("traceable_wacc")
            if status == "ok":
                status = "preview_only"
        limitations = self._limitations(
            fact_cache=fact_cache,
            years=years,
            missing_core=missing_core,
            market_opportunity=market_opportunity,
        )

        payload = {
            "ticker": company.ticker,
            "company": company.name,
            "currency": company.currency,
            "status": status,
            "publishable": (
                status == "ok"
                and not publication_blockers
                and coverage["coverage_percent"] >= 60
            ),
            "model": "long_term_fundamental_modeling_engine",
            "model_version": MODEL_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "code_commit_sha": self._code_commit_sha(),
            "framework": framework.as_dict(),
            "horizon_years": horizon,
            "as_of_period": current.get("period"),
            "current_price": current_price,
            "missing_inputs": missing_core + missing_mandatory_drivers + publication_blockers,
            "publication_blockers": publication_blockers,
            "missing_mandatory_drivers": missing_mandatory_drivers,
            "driver_gaps": driver_gaps,
            "historical_review": {
                "years_covered": len(years),
                "first_year": years[0] if years else None,
                "last_year": latest_year,
                "rows": history,
                "source_rule": "Every reported line carries fact_id, document_id, period and source_type.",
            },
            "current_snapshot": current,
            "assumptions": {key: value.as_dict() for key, value in assumptions.items()},
            "assumption_summary": assumption_meta,
            "operating_model": {
                "revenue_drivers": list(framework.revenue_drivers),
                "kpis": list(framework.kpis),
                "unit_economics": list(framework.unit_economics),
                "segment_model": list(framework.segment_model),
                "binding_constraints": list(framework.binding_constraints),
                "active_modules": list(framework.active_modules),
            },
            "driver_model": driver_model,
            "driver_assumptions": driver_assumptions,
            "driver_formula": {
                "status": driver_preview.get("status"),
                "formula_key": driver_preview.get("formula_key"),
                "output_metric": driver_preview.get("output_metric"),
                "expression": driver_preview.get("expression"),
                "missing_inputs": missing_formula_inputs,
            },
            "scenario_configuration": {
                "names": [name for name, _ in scenario_specs],
                "probability_method": "company_evidence_confidence_and_growth_skew",
                "driver_scenario_shift": {"bear": -0.02, "base": 0.0, "bull": 0.02},
            },
            "funding_policy": {
                "minimum_cash": 0.0,
                "maximum_debt_to_ebitda": 3.0,
                "equity_issuance_price_basis": "latest_reported_book_value_per_share",
                "acquisitions": "unknown_unless_sourced; excluded from baseline",
            },
            "scenarios": scenarios,
            "reverse_dcf": reverse_dcf,
            "market_opportunity": market_opportunity,
            # Compatibility projection for clients that still read the old
            # market_share field. New consumers should use market_opportunity.
            "market_share": {
                **market_opportunity["market_share"],
                "implied_future_market_share": market_opportunity["market_share"].get("base_future_market_share"),
                "deprecated_alias": "market_opportunity",
            },
            "management_capital_allocation": self._capital_allocation(
                fact_cache=fact_cache,
                revenue_history=revenue_history,
                years=years,
            ),
            "quality_of_growth": self._quality_of_growth(
                fact_cache=fact_cache,
                revenue_history=revenue_history,
                years=years,
            ),
            "owner_earnings": self._owner_earnings(fact_cache, latest_year),
            "capex_analysis": self._capex_analysis(fact_cache, latest_year),
            "timeline": self._timeline(db, company.id),
            "what_must_be_true": self._what_must_be_true(
                assumptions=assumptions,
                reverse_dcf=reverse_dcf,
                base_scenario=scenarios.get("base"),
                fact_cache=fact_cache,
                latest_year=latest_year,
                market_opportunity=market_opportunity,
            ),
            "source_coverage": coverage,
            "limitations": limitations,
            "trace": {
                "engine": "long_term_fundamental_modeling",
                "model_version": MODEL_VERSION,
                "input_source": "financial_facts" if history else "insufficient_data",
                "fact_count": sum(len(items) for items in fact_cache.values()),
                "annual_periods": years,
                "wacc": assumption_meta.get("wacc_trace"),
                # The market fingerprint hashes this key. Without it two quotes
                # of the same price on different dates were indistinguishable,
                # so the valuation snapshot match overwrote history instead of
                # versioning it.
                "market_as_of": market_as_of,
                "market_price_source": market_price_source,
            },
        }
        persisted = FundamentalModelRepository().persist(db, company, payload, commit=commit)
        payload["persistence"] = {
            "model_version_id": persisted.id if persisted else None,
            "version": persisted.version if persisted else None,
            "input_fingerprint": persisted.input_fingerprint if persisted else None,
            "forecast_fingerprint": persisted.forecast_fingerprint if persisted else None,
            "market_snapshot_fingerprint": (
                persisted.market_snapshot_fingerprint if persisted else None
            ),
            "valuation_snapshot_fingerprint": (
                persisted.valuation_snapshot_fingerprint if persisted else None
            ),
            "code_commit_sha": persisted.code_commit_sha if persisted else None,
            "status": "persisted" if persisted else "tenant_context_required",
        }
        return payload

    @staticmethod
    def _code_commit_sha() -> str:
        import os

        return (
            os.getenv("GIT_COMMIT_SHA")
            or os.getenv("GITHUB_SHA")
            or os.getenv("RENDER_GIT_COMMIT")
            or "development"
        )[:80]

    @staticmethod
    def _metric_key(metric: str) -> str:
        return (
            metric.strip()
            .lower()
            .replace("&", "and")
            .replace("/", "_")
            .replace("-", "_")
            .replace(" ", "_")
        )

    def _driver_model(
        self,
        company: Company,
        framework: CompanyFramework,
        fact_cache: dict[str, list[FinancialFact]],
    ) -> list[dict[str, Any]]:
        revenue_keys = [self._metric_key(item) for item in framework.revenue_drivers]
        kpi_keys = [self._metric_key(item) for item in framework.kpis]
        required_keys = {self._metric_key(item) for item in framework.required_fact_metrics}
        ordered_keys = list(dict.fromkeys(revenue_keys + kpi_keys))
        drivers: list[dict[str, Any]] = []
        for key in ordered_keys:
            facts = fact_cache.get(key) or []
            # Match the annual model anchor, not whichever quarterly/undated
            # row happened to be ingested last.
            annual = self._annual_by_year(facts)
            fact = annual[max(annual)] if annual else (facts[-1] if facts else None)
            if fact is None and key in DERIVED_DRIVERS:
                derived = self._derived_driver(key, fact_cache)
                if derived is not None:
                    drivers.append(
                        {
                            "key": key,
                            "driver_type": "revenue_driver" if key in revenue_keys else "kpi",
                            "required": key in required_keys,
                            **derived,
                            **driver_metadata(
                                key,
                                raw_unit=derived["unit"],
                                company_currency=company.currency,
                                period=derived["trace"]["period"],
                                source_type="derived",
                            ),
                        }
                    )
                    continue
            drivers.append(
                {
                    "key": key,
                    "driver_type": "revenue_driver" if key in revenue_keys else "kpi",
                    "required": key in required_keys,
                    "status": "sourced" if fact else "missing",
                    "value": _float(fact.value) if fact else None,
                    "unit": fact.unit if fact else "unknown",
                    "confidence": _float(fact.confidence) if fact else 0.0,
                    "source_fact_ids": [fact.id] if fact else [],
                    **driver_metadata(
                        key,
                        raw_unit=fact.unit if fact else "unknown",
                        company_currency=company.currency,
                        period=fact.period if fact else None,
                        source_type=fact.source_type if fact else None,
                    ),
                    "trace": {
                        "period": fact.period if fact else None,
                        "fiscal_year": fact.fiscal_year if fact else None,
                        "source_type": fact.source_type if fact else None,
                    },
                }
            )
        return drivers

    def _derived_driver(
        self, key: str, fact_cache: dict[str, list[FinancialFact]]
    ) -> dict[str, Any] | None:
        """Driver por identidad contable con hechos reportados del mismo
        ejercicio (el ultimo en que estan TODAS las entradas, en la misma
        unidad). Sin todas las entradas no hay dato: nunca se completa."""
        formula, inputs, signs = DERIVED_DRIVERS[key]
        by_year = [self._annual_by_year(fact_cache.get(metric) or []) for metric in inputs]
        common = set(by_year[0]).intersection(*by_year[1:]) if by_year else set()
        for year in sorted(common, reverse=True):
            facts = [annual[year] for annual in by_year]
            units = {fact.unit for fact in facts}
            values = [_float(fact.value) for fact in facts]
            if len(units) != 1 or any(value is None for value in values):
                continue
            value = sum(sign * float(v) for sign, v in zip(signs, values) if v is not None)
            return {
                "status": "derived",
                "value": value,
                "unit": facts[0].unit,
                "confidence": min(_float(fact.confidence) or 0.0 for fact in facts),
                "source_fact_ids": _unique_ids(*facts),
                "derivation": {
                    "label": "derivado",
                    "formula": formula,
                    "fiscal_year": year,
                    "inputs": {
                        metric: {"fact_id": fact.id, "value": _float(fact.value)}
                        for metric, fact in zip(inputs, facts)
                    },
                },
                "trace": {
                    "period": facts[0].period,
                    "fiscal_year": year,
                    "source_type": "derived",
                },
            }
        return None

    @staticmethod
    def _market_revenue_ceiling(market_opportunity: dict[str, Any]) -> float | None:
        future_market = (market_opportunity.get("top_down") or {}).get("future_market") or {}
        candidates = [
            _float(future_market.get("value")),
            _float((market_opportunity.get("bottom_up") or {}).get("value")),
        ]
        positive = [value for value in candidates if value is not None and value > 0]
        return min(positive) if positive else None

    @staticmethod
    def _constrain_scenario_growth(
        specs: list[tuple[str, dict[str, Any]]],
        *,
        latest_revenue: float,
        revenue_ceiling: float,
        horizon: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        if latest_revenue <= 0 or revenue_ceiling <= latest_revenue:
            maximum_growth = 0.0
        else:
            maximum_growth = (revenue_ceiling / latest_revenue) ** (1 / horizon) - 1
        constrained: list[tuple[str, dict[str, Any]]] = []
        for name, original in specs:
            spec = dict(original)
            if spec["growth"] > maximum_growth:
                spec["growth"] = maximum_growth
                spec["drivers"] = list(spec["drivers"]) + ["market_opportunity_revenue_ceiling"]
                spec["market_constraint"] = {
                    "revenue_ceiling": revenue_ceiling,
                    "maximum_cagr": maximum_growth,
                }
            constrained.append((name, spec))
        return constrained

    def _facts(self, db: Session, company: Company, metric: str) -> list[FinancialFact]:
        # Bound the newest facts, not the oldest 200. SEC histories can exceed
        # that cap and include undated legacy quarters. Keep the consumer's
        # oldest-to-newest contract after selecting the current window.
        newest = list(db.scalars(
            select(FinancialFact)
            .where(FinancialFact.company_id == company.id, FinancialFact.metric == metric)
            .order_by(
                FinancialFact.fiscal_year.desc().nullslast(),
                FinancialFact.created_at.desc(),
                FinancialFact.id.desc(),
            )
            .limit(200)
        ).all())
        return list(reversed(newest))

    def _annual_by_year(self, facts: list[FinancialFact]) -> dict[int, FinancialFact]:
        # Facts are ordered oldest-to-newest. Within a year, a fact with an
        # explicit FY marker (fiscal_quarter FY / period ...:FY) always beats
        # an unmarked row - unmarked annual-slot rows are how a stale quarter
        # (fiscal_year set, fiscal_quarter NULL, from a legacy import or a
        # vendor) used to override the 10-K and seed the DCF with one
        # quarter's revenue. Among rows of the same markedness the most
        # recently ingested source wins, as before.
        by_year: dict[int, tuple[int, FinancialFact]] = {}
        for fact in facts:
            if fact.fiscal_year is None or not _is_annual(fact):
                continue
            rank = 1 if _has_fy_marker(fact) else 0
            year = int(fact.fiscal_year)
            previous = by_year.get(year)
            if previous is None or rank >= previous[0]:
                by_year[year] = (rank, fact)
        return {year: fact for year, (_, fact) in by_year.items()}

    def _value_for_year(self, facts: list[FinancialFact], year: int | None) -> float | None:
        if year is None:
            return None
        fact = self._annual_by_year(facts).get(year)
        return _float(fact.value) if fact else None

    def _fact_for_year(self, facts: list[FinancialFact], year: int | None) -> FinancialFact | None:
        if year is None:
            return None
        return self._annual_by_year(facts).get(year)

    def _history_rows(self, fact_cache: dict[str, list[FinancialFact]], years: list[int]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for year in years[-10:]:
            revenue_fact = self._fact_for_year(fact_cache["revenue"], year)
            period = revenue_fact.period if revenue_fact else f"FY{year}"
            metrics: dict[str, Any] = {}
            for metric in ANNUAL_METRICS:
                fact = self._fact_for_year(fact_cache[metric], year)
                if metric == "free_cash_flow" and fact is None:
                    ocf = self._fact_for_year(fact_cache["operating_cash_flow"], year)
                    capex = self._fact_for_year(fact_cache["capital_expenditure"], year)
                    derived = _derived_fcf(ocf, capex)
                    if derived is not None:
                        metrics[metric] = _calculated_line(
                            float(derived),
                            unit="USD",
                            source_fact_ids=_unique_ids(ocf, capex),
                            calculation="operating_cash_flow + capital_expenditure",
                            basis="derivado porque falta el flujo de caja libre reportado",
                        )
                        continue
                metrics[metric] = _fact_line(fact)
                split_factor = getattr(fact, "split_factor", None) if fact is not None else None
                derivation = getattr(fact, "derivation", None) if fact is not None else None
                if metric == "shares_diluted" and fact is not None and derivation:
                    metrics[metric] = _calculated_line(
                        float(fact.value),
                        unit="shares",
                        source_fact_ids=[fact.id],
                        calculation="shares_outstanding al cierre del ejercicio",
                        basis=derivation,
                    )
                elif metric == "shares_diluted" and split_factor is not None and split_factor != 1:
                    metrics[metric] = _calculated_line(
                        float(fact.value),
                        unit="shares",
                        source_fact_ids=[fact.id],
                        calculation=f"reported x cumulative_split_factor {split_factor}",
                        basis="ajustado por splits posteriores al cierre del periodo",
                    )

            revenue = metrics["revenue"]["value"]
            for metric, numerator in (
                ("gross_margin", "gross_profit"),
                ("operating_margin", "operating_income"),
                ("ebitda_margin", "ebitda"),
                ("net_margin", "net_income"),
                ("fcf_margin", "free_cash_flow"),
            ):
                numerator_line = metrics[numerator]
                ids = _unique_ids(ids=metrics["revenue"]["source_fact_ids"] + numerator_line["source_fact_ids"])
                value = (
                    numerator_line["value"] / revenue
                    if revenue not in (None, 0) and numerator_line["value"] is not None
                    else None
                )
                metrics[metric] = _calculated_line(
                    value,
                    unit="decimal",
                    source_fact_ids=ids,
                    calculation=f"{numerator} / revenue",
                    basis="mismo ejercicio fiscal",
                )
            rows.append({"period": period, "fiscal_year": year, "metrics": metrics})
        return rows

    def _series(
        self,
        fact_cache: dict[str, list[FinancialFact]],
        metric: str,
        years: list[int],
    ) -> list[dict[str, Any]]:
        series: list[dict[str, Any]] = []
        for year in years:
            fact = self._fact_for_year(fact_cache[metric], year)
            if fact is not None:
                series.append({"year": year, "value": _float(fact.value), "fact_ids": [fact.id]})
        return series

    def _derived_fcf_series(
        self,
        fact_cache: dict[str, list[FinancialFact]],
        years: list[int],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for year in years:
            fcf = self._fact_for_year(fact_cache["free_cash_flow"], year)
            if fcf:
                result.append({"year": year, "value": _float(fcf.value), "fact_ids": [fcf.id]})
                continue
            ocf = self._fact_for_year(fact_cache["operating_cash_flow"], year)
            capex = self._fact_for_year(fact_cache["capital_expenditure"], year)
            derived = _derived_fcf(ocf, capex)
            if derived is not None:
                result.append(
                    {
                        "year": year,
                        "value": float(derived),
                        "fact_ids": _unique_ids(ocf, capex),
                    }
                )
        return result

    def _assumptions(
        self,
        *,
        db: Session,
        fact_cache: dict[str, list[FinancialFact]],
        revenue_history: dict[int, FinancialFact],
        years: list[int],
        company: Company,
    ) -> tuple[dict[str, Assumption], dict[str, Any]]:
        revenue_series = [
            {"year": year, "value": _float(fact.value), "fact_ids": [fact.id]}
            for year, fact in sorted(revenue_history.items())
            if _float(fact.value) is not None and _float(fact.value) > 0
        ]
        growth_values: list[float] = []
        growth_ids: list[int] = []
        for previous, current in zip(revenue_series, revenue_series[1:]):
            if previous["value"] and current["value"] is not None:
                growth_values.append(current["value"] / previous["value"] - 1)
                growth_ids.extend(previous["fact_ids"] + current["fact_ids"])
        growth = None
        if len(revenue_series) >= 2:
            first = revenue_series[0]
            last = revenue_series[-1]
            span = max(1, last["year"] - first["year"])
            growth = (last["value"] / first["value"]) ** (1 / span) - 1
            growth_ids = _unique_ids(ids=first["fact_ids"] + last["fact_ids"])

        fcf_series = self._derived_fcf_series(fact_cache, years)
        revenue_by_year = {item["year"]: item for item in revenue_series}
        margin_points = [
            item
            for item in fcf_series
            if item["year"] in revenue_by_year and revenue_by_year[item["year"]]["value"]
        ]
        margin_values = [item["value"] / revenue_by_year[item["year"]]["value"] for item in margin_points]
        margin_ids: list[int] = []
        for item in margin_points[-5:]:
            margin_ids.extend(item["fact_ids"] + revenue_by_year[item["year"]]["fact_ids"])
        fcf_margin = median(margin_values[-5:]) if margin_values else None

        def ratio_assumption(metric: str, numerator: str, denominator: str) -> Assumption:
            points: list[tuple[float, list[int]]] = []
            numerator_series = self._derived_fcf_series(fact_cache, years) if numerator == "free_cash_flow" else self._series(fact_cache, numerator, years)
            denominator_series = self._series(fact_cache, denominator, years)
            denominator_by_year = {item["year"]: item for item in denominator_series}
            for item in numerator_series:
                denominator_item = denominator_by_year.get(item["year"])
                if denominator_item and denominator_item["value"] not in (None, 0):
                    points.append((item["value"] / denominator_item["value"], item["fact_ids"] + denominator_item["fact_ids"]))
            values = [value for value, _ in points]
            ids = [fact_id for _, point_ids in points[-5:] for fact_id in point_ids]
            used = min(5, len(values))
            # Gramatica es-ES: «últimas 1 observaciones» y «últimas 0
            # observaciones» llegaban tal cual a la UI (F13).
            if used == 0:
                basis = f"sin observaciones anuales de {metric}"
            elif used == 1:
                basis = f"mediana de la última observación anual de {metric}"
            else:
                basis = f"mediana de las últimas {used} observaciones anuales de {metric}"
            return Assumption(
                value=median(values[-5:]) if values else None,
                unit="decimal",
                source_type="financial_facts" if values else "missing",
                basis=basis,
                source_fact_ids=_unique_ids(ids=ids),
                confidence=self._confidence(fact_cache, ids),
            )

        gross_margin = ratio_assumption("gross_margin", "gross_profit", "revenue")
        operating_margin = ratio_assumption("operating_margin", "operating_income", "revenue")
        ebitda_margin = ratio_assumption("ebitda_margin", "ebitda", "revenue")
        net_margin = ratio_assumption("net_margin", "net_income", "revenue")

        tax_rate = ratio_assumption("effective_tax_rate", "income_tax_expense", "income_before_tax")
        if tax_rate.value is not None:
            raw_tax = tax_rate.value
            clamped_tax = max(0.0, min(raw_tax, 0.60))
            tax_rate = Assumption(
                value=clamped_tax,
                unit="decimal",
                source_type=tax_rate.source_type,
                basis=(
                    f"tipo efectivo {format_percent_es(raw_tax)} acotado al rango [0 %, 60 %]: los tipos "
                    "negativos proceden de cargas no operativas e inflarían el NOPAT"
                    if clamped_tax != raw_tax
                    else tax_rate.basis
                ),
                source_fact_ids=tax_rate.source_fact_ids,
                confidence=tax_rate.confidence,
            )
        else:
            tax_rate = Assumption(
                value=0.25,
                unit="decimal",
                source_type="model_policy",
                basis="tipo impositivo legal de reserva; sustituir con datos fiscales reportados",
                source_fact_ids=[],
                confidence=0.35,
            )

        shares_series = self._series(fact_cache, "shares_diluted", years)
        shares_cagr = (
            None if _has_unexplained_share_jump(shares_series) else self._cagr(shares_series)
        )
        shares_ids = [fact_id for item in shares_series for fact_id in item["fact_ids"]]
        wacc_metric = db.scalar(
            select(CalculatedMetric)
            .where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == "wacc",
                CalculatedMetric.value.is_not(None),
            )
            .order_by(
                desc(CalculatedMetric.fiscal_year),
                desc(CalculatedMetric.created_at),
            )
            .limit(1)
        )
        if wacc_metric is not None:
            wacc = Assumption(
                value=_float(wacc_metric.value),
                unit=wacc_metric.unit,
                source_type="calculated_metric",
                basis=(
                    f"CalculatedMetric #{wacc_metric.id}: {wacc_metric.formula}; "
                    f"definition={wacc_metric.definition_version}"
                ),
                source_fact_ids=list(wacc_metric.source_fact_ids or []),
                confidence=_float(wacc_metric.confidence) or 0.0,
            )
            wacc_trace = {
                "status": "traceable",
                "calculated_metric_id": wacc_metric.id,
                "period": wacc_metric.period,
                "formula": wacc_metric.formula,
                "source_fact_ids": list(wacc_metric.source_fact_ids or []),
                "calculation_trace": wacc_metric.calculation_trace or {},
            }
        elif (
            wacc_inferred := InferredInputService().latest_valid(db, company.id, "wacc")
        ) is not None:
            wacc = Assumption(
                value=_float(wacc_inferred.value),
                unit="decimal",
                source_type="inferred_input",
                basis=f"InferredInput #{wacc_inferred.id}: {wacc_inferred.base}",
                source_fact_ids=[],
                confidence=0.5,
                source_urls=tuple(wacc_inferred.source_urls or ()),
            )
            wacc_trace = {
                "status": "inferred_input",
                "calculated_metric_id": None,
                "inferred_input_id": wacc_inferred.id,
                "source_fact_ids": [],
                "source_urls": list(wacc_inferred.source_urls or []),
            }
        else:
            wacc = Assumption(
                value=default_wacc(company),
                unit="decimal",
                source_type="model_policy",
                basis="política de empresa solo de vista previa; se requiere una CalculatedMetric(wacc) trazable para publicar",
                source_fact_ids=[],
                confidence=0.20,
            )
            wacc_trace = {
                "status": "preview_only_default",
                "calculated_metric_id": None,
                "source_fact_ids": [],
            }
        terminal_inferred = InferredInputService().latest_valid(db, company.id, "terminal_growth")
        if terminal_inferred is not None:
            terminal = Assumption(
                value=_float(terminal_inferred.value),
                unit="decimal",
                source_type="inferred_input",
                basis=f"InferredInput #{terminal_inferred.id}: {terminal_inferred.base}",
                source_fact_ids=[],
                confidence=0.5,
                source_urls=tuple(terminal_inferred.source_urls or ()),
            )
        else:
            terminal = Assumption(
                value=default_terminal_growth(company),
                unit="decimal",
                source_type="model_policy",
                basis="política de crecimiento terminal del marco de la empresa",
                source_fact_ids=[],
                confidence=0.40,
            )

        # run_dcf exige WACC > g: un par inferido sin spread minimo se ignora
        # (primero g, luego wacc) y queda constancia en wacc_trace.
        ignored_inferred: list[str] = []
        if (
            wacc.value is not None
            and terminal.value is not None
            and wacc.value - terminal.value < MIN_WACC_TERMINAL_SPREAD - 1e-9
        ):
            if terminal.source_type == "inferred_input":
                terminal = Assumption(
                    value=default_terminal_growth(company),
                    unit="decimal",
                    source_type="model_policy",
                    basis="política de crecimiento terminal del marco de la empresa",
                    source_fact_ids=[],
                    confidence=0.40,
                )
                ignored_inferred.append("terminal_growth")
            if (
                # nosemgrep: gerarai-money-none-to-zero -- solo endurece el guardarrail WACC-g: con g desconocido el diferencial se mide contra 0, que es el caso mas conservador
                wacc.value - (terminal.value or 0.0) < MIN_WACC_TERMINAL_SPREAD - 1e-9
                and wacc.source_type == "inferred_input"
            ):
                wacc = Assumption(
                    value=default_wacc(company),
                    unit="decimal",
                    source_type="model_policy",
                    basis="política de empresa solo de vista previa; se requiere una CalculatedMetric(wacc) trazable para publicar",
                    source_fact_ids=[],
                    confidence=0.20,
                )
                wacc_trace = {
                    "status": "preview_only_default",
                    "calculated_metric_id": None,
                    "source_fact_ids": [],
                }
                ignored_inferred.append("wacc")
        if ignored_inferred:
            wacc_trace = {**wacc_trace, "inferred_inputs_ignored": ignored_inferred}

        capex_intensity = ratio_assumption("capex_to_revenue", "capital_expenditure", "revenue")
        if capex_intensity.value is not None:
            capex_intensity = Assumption(
                value=abs(capex_intensity.value),
                unit="decimal",
                source_type=capex_intensity.source_type,
                basis="mediana de capex absoluto / ingresos",
                source_fact_ids=capex_intensity.source_fact_ids,
                confidence=capex_intensity.confidence,
            )

        working_capital = ratio_assumption("working_capital_to_revenue", "working_capital", "revenue")
        assumptions = {
            "revenue_growth": Assumption(growth, "decimal", "financial_facts" if growth is not None else "missing", "annual revenue CAGR across available history", growth_ids, self._confidence(fact_cache, growth_ids)),
            "fcf_margin": Assumption(fcf_margin, "decimal", "financial_facts" if fcf_margin is not None else "missing", "median of latest annual FCF margins", _unique_ids(ids=margin_ids), self._confidence(fact_cache, margin_ids)),
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "ebitda_margin": ebitda_margin,
            "net_margin": net_margin,
            "effective_tax_rate": tax_rate,
            "capex_to_revenue": capex_intensity,
            "working_capital_to_revenue": working_capital,
            "shares_cagr": Assumption(shares_cagr, "decimal", "financial_facts" if shares_cagr is not None else "missing", "diluted share count CAGR across available history", _unique_ids(ids=shares_ids), self._confidence(fact_cache, shares_ids)),
            "wacc": wacc,
            "terminal_growth": terminal,
        }
        growth_spread = self._spread(growth_values)
        margin_spread = self._spread(margin_values)
        assumption_meta = {
            "growth_observations": growth_values,
            "growth_spread_policy": max(0.02, min(0.08, growth_spread * 0.75 if growth_values else 0.02)),
            "margin_spread_policy": max(0.02, min(0.06, margin_spread * 0.75 if margin_values else 0.02)),
            "normalization_window_years": min(5, len(years)),
            "share_count_observations": len(shares_series),
            "wacc_trace": wacc_trace,
        }
        return assumptions, assumption_meta

    def _confidence(self, fact_cache: dict[str, list[FinancialFact]], fact_ids: list[int]) -> float:
        if not fact_ids:
            return 0.0
        by_id = {fact.id: fact for facts in fact_cache.values() for fact in facts}
        values = [_float(by_id[fact_id].confidence) for fact_id in fact_ids if fact_id in by_id]
        return min(values) if values else 0.0

    @staticmethod
    def _cagr(series: list[dict[str, Any]]) -> float | None:
        if len(series) < 2:
            return None
        first, last = series[0], series[-1]
        if first["value"] in (None, 0) or last["value"] is None or first["year"] == last["year"]:
            return None
        if first["value"] < 0 or last["value"] < 0:
            return None
        return (last["value"] / first["value"]) ** (1 / (last["year"] - first["year"])) - 1

    @staticmethod
    def _spread(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        average = sum(values) / len(values)
        variance = sum((value - average) ** 2 for value in values) / len(values)
        return sqrt(max(0.0, variance))

    def _scenario_specs(
        self,
        assumptions: dict[str, Assumption],
        *,
        framework: CompanyFramework,
        missing_mandatory_drivers: list[str],
    ) -> list[tuple[str, dict[str, Any]]]:
        growth = assumptions["revenue_growth"].value
        margin = assumptions["fcf_margin"].value
        wacc = assumptions["wacc"].value
        terminal = assumptions["terminal_growth"].value
        assert growth is not None and margin is not None and wacc is not None and terminal is not None
        growth_spread = max(0.02, min(0.08, abs(growth) * 0.35))
        margin_spread = max(0.02, min(0.06, abs(margin) * 0.25))
        confidence_values = [
            assumption.confidence
            for assumption in assumptions.values()
            if assumption.value is not None
        ]
        evidence_confidence = (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        )
        base_probability = max(0.38, min(0.68, 0.38 + evidence_confidence * 0.30))
        remaining = 1.0 - base_probability
        upside_share = max(0.35, min(0.65, 0.50 + growth * 0.75))
        if missing_mandatory_drivers:
            base_probability = max(0.34, base_probability - 0.10)
            remaining = 1.0 - base_probability
            upside_share = min(upside_share, 0.40)
        bull_probability = remaining * upside_share
        bear_probability = remaining - bull_probability
        probability_basis = {
            "method": "company_evidence_confidence_and_growth_skew",
            "evidence_confidence": evidence_confidence,
            "historical_growth": growth,
            "framework": framework.key,
            "missing_mandatory_driver_count": len(missing_mandatory_drivers),
        }
        framework_drivers = list(framework.revenue_drivers[:3])
        return [
            ("bear", {"probability": bear_probability, "probability_basis": probability_basis, "growth": max(growth - growth_spread, -0.25), "fcf_margin": margin - margin_spread, "wacc": wacc + 0.02, "terminal_growth": max(terminal - 0.005, 0.0), "drivers": framework_drivers + ["execution_downside", "margin_compression", "higher_cost_of_capital"]}),
            ("base", {"probability": base_probability, "probability_basis": probability_basis, "growth": growth, "fcf_margin": margin, "wacc": wacc, "terminal_growth": terminal, "drivers": framework_drivers + ["historical_revenue_cagr", "normalized_fcf_margin"]}),
            ("bull", {"probability": bull_probability, "probability_basis": probability_basis, "growth": min(growth + growth_spread, 0.50), "fcf_margin": min(margin + margin_spread, 0.60), "wacc": max(wacc - 0.01, terminal + 0.01), "terminal_growth": terminal, "drivers": framework_drivers + ["execution_upside", "margin_expansion", "lower_cost_of_capital"]}),
        ]

    def _forecast(
        self,
        *,
        fact_cache: dict[str, list[FinancialFact]],
        years: list[int],
        latest_year: int,
        horizon: int,
        scenario: str,
        growth: float,
        fcf_margin: float,
        wacc: float,
        assumptions: dict[str, Assumption],
        driver_forecast: dict[str, Any],
    ) -> list[dict[str, Any]]:
        latest_revenue = self._value_for_year(fact_cache["revenue"], latest_year)
        latest_shares = self._value_for_year(fact_cache["shares_diluted"], latest_year)
        if latest_revenue is None or latest_shares in (None, 0):
            return []

        share_growth = assumptions["shares_cagr"].value
        capex_ratio = assumptions["capex_to_revenue"].value
        working_capital_ratio = assumptions["working_capital_to_revenue"].value
        tax_rate_value = assumptions["effective_tax_rate"].value
        tax_rate = tax_rate_value if tax_rate_value is not None else 0.25
        base_ids = _unique_ids(ids=assumptions["revenue_growth"].source_fact_ids)
        margin_ids = _unique_ids(ids=assumptions["fcf_margin"].source_fact_ids)
        share_ids = _unique_ids(ids=assumptions["shares_cagr"].source_fact_ids)
        capex_ids = _unique_ids(ids=assumptions["capex_to_revenue"].source_fact_ids)
        tax_ids = _unique_ids(ids=assumptions["effective_tax_rate"].source_fact_ids)

        previous_revenue = latest_revenue
        previous_shares = latest_shares
        previous_working_capital = self._value_for_year(fact_cache["working_capital"], latest_year)
        previous_cash = self._value_for_year(fact_cache["cash_and_equivalents"], latest_year)
        previous_debt = self._value_for_year(fact_cache["total_debt"], latest_year)
        latest_equity = self._value_for_year(fact_cache["total_equity"], latest_year)
        previous_invested_capital = (
            previous_debt + latest_equity - previous_cash
            if previous_debt is not None
            and latest_equity is not None
            and previous_cash is not None
            else None
        )
        book_value_per_share = (
            latest_equity / latest_shares
            if latest_equity is not None and latest_equity > 0 and latest_shares > 0
            else None
        )
        debt_series = self._series(fact_cache, "total_debt", years)
        debt_trend = self._cagr(debt_series)
        driver_rows = {
            int(row["year"]): row for row in (driver_forecast.get("years") or [])
        }
        forecasts: list[dict[str, Any]] = []
        for offset in range(1, horizon + 1):
            year = latest_year + offset
            driver_row = driver_rows.get(year)
            driver_output_metric = driver_forecast.get("output_metric")
            revenue = (
                float(driver_row["output"])
                if driver_row is not None and driver_output_metric == "revenue"
                else previous_revenue * (1 + growth)
            )
            organic_shares = (
                max(0.000001, previous_shares * (1 + share_growth))
                if share_growth is not None
                else previous_shares
            )
            fcf = revenue * fcf_margin
            capex = -revenue * capex_ratio if capex_ratio is not None else None
            operating_cash_flow = fcf - capex if capex is not None else None
            working_capital = revenue * working_capital_ratio if working_capital_ratio is not None else None
            working_capital_absorption = (
                working_capital - (previous_working_capital if previous_working_capital is not None else working_capital)
                if working_capital is not None
                else None
            )
            gross_profit = revenue * assumptions["gross_margin"].value if assumptions["gross_margin"].value is not None else None
            operating_income = revenue * assumptions["operating_margin"].value if assumptions["operating_margin"].value is not None else None
            ebitda = revenue * assumptions["ebitda_margin"].value if assumptions["ebitda_margin"].value is not None else None
            net_income = revenue * assumptions["net_margin"].value if assumptions["net_margin"].value is not None else (
                operating_income * (1 - tax_rate) if operating_income is not None else None
            )
            if driver_row is not None and driver_output_metric == "operating_income":
                operating_income = float(driver_row["output"])
            if driver_row is not None and driver_output_metric == "net_income":
                net_income = float(driver_row["output"])

            baseline_cash = (
                previous_cash + operating_cash_flow + capex
                if previous_cash is not None
                and operating_cash_flow is not None
                and capex is not None
                else None
            )
            planned_debt = (
                max(0.0, previous_debt * (1 + debt_trend))
                if previous_debt is not None and debt_trend is not None
                else None
            )
            planned_debt_change = (
                planned_debt - previous_debt
                if planned_debt is not None and previous_debt is not None
                else None
            )
            cash_after_planned_debt = (
                baseline_cash + planned_debt_change
                if baseline_cash is not None and planned_debt_change is not None
                else baseline_cash
            )
            funding_gap = (
                max(0.0, -cash_after_planned_debt)
                if cash_after_planned_debt is not None
                else None
            )
            # Unknown EBITDA does not mean zero borrowing capacity. Coercing it
            # to 0.0 turned a whole funding gap into primary equity issuance:
            # a company with 200 of EBITDA and no debt would have funded 50 of
            # gap with debt, but the same company without an ebitda fact
            # funded it 100% with equity and invented ~5% of dilution.
            debt_capacity = (
                max(0.0, ebitda * 3.0 - planned_debt)
                if ebitda is not None and planned_debt is not None
                else None
            )
            new_debt_for_gap = (
                min(funding_gap, debt_capacity)
                if funding_gap is not None and debt_capacity is not None
                else None
            )
            equity_issuance = (
                max(0.0, funding_gap - (new_debt_for_gap or 0.0))
                if funding_gap is not None
                else None
            )
            if funding_gap is not None and debt_capacity is None:
                # The split between debt and equity is unknown, so neither leg
                # can be asserted. Report the gap and refuse to guess the mix.
                equity_issuance = None
                funding_mix_status = "insufficient_data"
            else:
                funding_mix_status = "ok"
            incremental_shares = (
                equity_issuance / book_value_per_share
                if equity_issuance is not None
                and equity_issuance > 0
                and book_value_per_share not in (None, 0)
                else (0.0 if equity_issuance == 0 else None)
            )
            shares = (
                organic_shares + incremental_shares
                if incremental_shares is not None
                else None
            )
            closing_cash = (
                max(
                    0.0,
                    cash_after_planned_debt
                    + (new_debt_for_gap or 0.0)
                    + (equity_issuance or 0.0),
                )
                if cash_after_planned_debt is not None
                else None
            )
            closing_debt = (
                planned_debt + (new_debt_for_gap or 0.0)
                if planned_debt is not None
                else None
            )
            net_debt = (
                closing_debt - closing_cash
                if closing_debt is not None and closing_cash is not None
                else None
            )
            growth_investment = (
                abs(capex) + max(0.0, working_capital_absorption or 0.0)
                if capex is not None
                else None
            )
            invested_capital = (
                previous_invested_capital + growth_investment
                if previous_invested_capital is not None and growth_investment is not None
                else None
            )
            roic = (
                operating_income * (1 - tax_rate) / invested_capital
                if operating_income is not None
                and invested_capital is not None
                and invested_capital > 0
                else None
            )
            point_ids = _unique_ids(ids=base_ids + margin_ids)
            revenue_source_ids = (
                list(driver_row.get("source_fact_ids") or [])
                if driver_row is not None and driver_output_metric == "revenue"
                else base_ids
            )
            evidence = {
                "revenue": {
                    "source_fact_ids": revenue_source_ids,
                    "calculation": (
                        driver_row.get("calculation")
                        if driver_row is not None and driver_output_metric == "revenue"
                        else "prior revenue * (1 + scenario revenue growth)"
                    ),
                },
                "gross_profit": {"source_fact_ids": point_ids + assumptions["gross_margin"].source_fact_ids, "calculation": "revenue * historical gross margin"},
                "operating_income": {"source_fact_ids": point_ids + assumptions["operating_margin"].source_fact_ids, "calculation": "revenue * historical operating margin"},
                "ebitda": {"source_fact_ids": point_ids + assumptions["ebitda_margin"].source_fact_ids, "calculation": "revenue * historical EBITDA margin"},
                "net_income": {"source_fact_ids": point_ids + assumptions["net_margin"].source_fact_ids + tax_ids, "calculation": "revenue * historical net margin or NOPAT proxy"},
                "operating_cash_flow": {"source_fact_ids": point_ids + capex_ids, "calculation": "FCF - capital expenditure"},
                "capital_expenditure": {"source_fact_ids": capex_ids, "calculation": "-revenue * historical capex intensity"},
                "free_cash_flow": {"source_fact_ids": point_ids, "calculation": "revenue * scenario FCF margin"},
                "working_capital": {"source_fact_ids": assumptions["working_capital_to_revenue"].source_fact_ids, "calculation": "revenue * historical working capital / revenue"},
                "net_debt": {"source_fact_ids": self._balance_fact_ids(fact_cache, latest_year), "calculation": "closing debt - closing cash after funding roll-forward"},
                "shares_diluted": {"source_fact_ids": share_ids + self._balance_fact_ids(fact_cache, latest_year), "calculation": "organic diluted shares + equity funding / latest reported book value per share"},
                "fcf_per_share": {"source_fact_ids": point_ids + share_ids, "calculation": "free cash flow / diluted shares"},
                "roic": {"source_fact_ids": point_ids + tax_ids + self._balance_fact_ids(fact_cache, latest_year), "calculation": "NOPAT / rolled-forward invested capital"},
            }
            funding_model = {
                "status": (
                    "insufficient_data"
                    if funding_mix_status == "insufficient_data"
                    else (
                        "complete_baseline"
                        if previous_cash is not None
                        and previous_debt is not None
                        and debt_trend is not None
                        and (equity_issuance in (None, 0) or incremental_shares is not None)
                        else "partial_unknowns"
                    )
                ),
                "funding_mix_status": funding_mix_status,
                "funding_mix_missing_inputs": (
                    ["ebitda", "total_debt"]
                    if funding_mix_status == "insufficient_data" and funding_gap
                    else []
                ),
                "opening_cash": previous_cash,
                "operating_cash_generation": operating_cash_flow,
                "capital_expenditure": capex,
                "acquisitions": None,
                "acquisitions_policy": "unknown and excluded from baseline; never coerced to zero",
                "debt_repayment": (
                    abs(min(0.0, planned_debt_change))
                    if planned_debt_change is not None
                    else None
                ),
                "new_debt": (
                    max(0.0, planned_debt_change or 0.0) + (new_debt_for_gap or 0.0)
                    if planned_debt_change is not None
                    else new_debt_for_gap
                ),
                "equity_issuance": equity_issuance,
                "incremental_shares": incremental_shares,
                "closing_cash_pre_acquisitions": closing_cash,
                "closing_cash": None,
                "funding_gap": funding_gap,
                "debt_capacity": debt_capacity,
                "debt_trend": debt_trend,
                "debt_trend_status": (
                    "historical_cagr" if debt_trend is not None else "unknown"
                ),
                "equation": "opening cash + operating cash generation + capex - acquisitions - debt repayment + new debt + equity issuance = closing cash",
            }
            forecasts.append(
                {
                    "year": year,
                    "revenue": revenue,
                    "gross_profit": gross_profit,
                    "operating_income": operating_income,
                    "ebitda": ebitda,
                    "net_income": net_income,
                    "operating_cash_flow": operating_cash_flow,
                    "capital_expenditure": capex,
                    "free_cash_flow": fcf,
                    "working_capital": working_capital,
                    "working_capital_absorption": working_capital_absorption,
                    "net_debt": net_debt,
                    "shares_diluted": shares,
                    "fcf_per_share": fcf / shares if shares not in (None, 0) else None,
                    "fcf_margin": fcf / revenue if revenue else None,
                    "roic": roic,
                    "invested_capital": invested_capital,
                    "funding_model": funding_model,
                    "segments": driver_row.get("segments") if driver_row else {},
                    "evidence": evidence,
                    "scenario": scenario,
                    "wacc": wacc,
                }
            )
            previous_revenue = revenue
            if shares is not None:
                previous_shares = shares
            previous_working_capital = working_capital
            previous_cash = closing_cash
            previous_debt = closing_debt
            previous_invested_capital = invested_capital
        return forecasts

    def _balance_fact_ids(self, fact_cache: dict[str, list[FinancialFact]], year: int) -> list[int]:
        return _unique_ids(
            self._fact_for_year(fact_cache["total_debt"], year),
            self._fact_for_year(fact_cache["total_equity"], year),
            self._fact_for_year(fact_cache["cash_and_equivalents"], year),
        )

    def _derived_fcf_value(self, fact_cache: dict[str, list[FinancialFact]], year: int) -> float | None:
        fact = self._fact_for_year(fact_cache["free_cash_flow"], year)
        if fact:
            return _float(fact.value)
        ocf = self._fact_for_year(fact_cache["operating_cash_flow"], year)
        capex = self._fact_for_year(fact_cache["capital_expenditure"], year)
        derived = _derived_fcf(ocf, capex)
        return float(derived) if derived is not None else None

    def _scenario_payload(
        self,
        *,
        name: str,
        spec: dict[str, Any],
        forecast: list[dict[str, Any]],
        assumptions: dict[str, Assumption],
        fact_cache: dict[str, list[FinancialFact]],
        latest_year: int,
    ) -> dict[str, Any]:
        latest_revenue = self._value_for_year(fact_cache["revenue"], latest_year)
        net_debt = self._value_for_year(fact_cache["net_debt"], latest_year)
        current_shares = self._value_for_year(
            fact_cache.get("shares_diluted") or [], latest_year
        )
        dcf = None
        valuation_note = None
        terminal_shares = forecast[-1].get("shares_diluted") if forecast else None
        if forecast and net_debt is not None and terminal_shares not in (None, 0):
            if spec["wacc"] <= spec["terminal_growth"]:
                # Gordon growth needs wacc > g: never divide by zero or emit a
                # negative/nonsense terminal value as if it were a valuation.
                valuation_note = (
                    "DCF skipped: WACC must exceed terminal growth "
                    f"(wacc={spec['wacc']}, terminal_growth={spec['terminal_growth']})."
                )
            elif forecast[-1]["free_cash_flow"] <= 0:
                # A perpetuity on non-positive terminal FCFF is not a valuation;
                # never present it (or a floored 0% margin) as one.
                valuation_note = (
                    "DCF skipped: terminal free cash flow is not positive "
                    f"(fcf_margin={spec['fcf_margin']}); a profitability "
                    "transition must be modelled explicitly."
                )
            else:
                pv_explicit = sum(
                    point["free_cash_flow"] / ((1 + spec["wacc"]) ** index)
                    for index, point in enumerate(forecast, start=1)
                )
                terminal_fcf = forecast[-1]["free_cash_flow"] * (1 + spec["terminal_growth"])
                terminal_value = terminal_fcf / (spec["wacc"] - spec["terminal_growth"])
                pv_terminal = terminal_value / ((1 + spec["wacc"]) ** len(forecast))
                enterprise_value = pv_explicit + pv_terminal
                equity_value = enterprise_value - net_debt
                # The discounted stream is pure FCFF, so the equity value it
                # supports belongs to the shares outstanding *at the valuation
                # date*. Dividing by the fully diluted TERMINAL share count
                # charged the whole primary issuance against value per share
                # while its proceeds were never added to the stream: with a
                # 250M-share raise the same enterprise value reported 1.07
                # instead of 1.60 (-33%), a number produced entirely by a
                # dilution whose cash is not in the numerator.
                valuation_shares = current_shares if current_shares not in (None, 0) else terminal_shares
                dcf = {
                    "enterprise_value": enterprise_value,
                    "equity_value": equity_value,
                    "value_per_share": equity_value / valuation_shares,
                    "trace": {
                        "method": "explicit_driver_fcff_dcf",
                        "pv_explicit_fcf": pv_explicit,
                        "terminal_fcf": terminal_fcf,
                        "terminal_value": terminal_value,
                        "pv_terminal_value": pv_terminal,
                        "current_net_debt": net_debt,
                        "valuation_shares": valuation_shares,
                        "valuation_shares_basis": (
                            "shares_at_valuation_date"
                            if current_shares not in (None, 0)
                            else "terminal_shares_fallback_no_current_count"
                        ),
                        "terminal_diluted_shares": terminal_shares,
                        "forward_dilution_pct": (
                            (terminal_shares - valuation_shares) / valuation_shares
                            if terminal_shares is not None and valuation_shares
                            else None
                        ),
                        "terminal_value_share": (
                            pv_terminal / enterprise_value if enterprise_value else None
                        ),
                    },
                }
        first = forecast[0] if forecast else None
        return {
            "probability": spec["probability"],
            "probability_basis": spec.get("probability_basis", {}),
            "assumptions": {
                "revenue_growth": {
                    "value": spec["growth"],
                    "unit": "decimal",
                    "source_type": "model_policy_plus_history",
                    "basis": "base historical CAGR adjusted by explicit scenario spread",
                    "source_fact_ids": assumptions["revenue_growth"].source_fact_ids,
                },
                "fcf_margin": {
                    "value": spec["fcf_margin"],
                    "unit": "decimal",
                    "source_type": "model_policy_plus_history",
                    "basis": "normalized historical FCF margin adjusted by explicit scenario spread",
                    "source_fact_ids": assumptions["fcf_margin"].source_fact_ids,
                },
                "wacc": {
                    "value": spec["wacc"],
                    "unit": "decimal",
                    "source_type": assumptions["wacc"].source_type,
                    "basis": f"{assumptions['wacc'].basis}; scenario adjustment applied",
                    "source_fact_ids": assumptions["wacc"].source_fact_ids,
                    **(
                        {"source_urls": list(assumptions["wacc"].source_urls)}
                        if assumptions["wacc"].source_urls
                        else {}
                    ),
                },
                "terminal_growth": {
                    "value": spec["terminal_growth"],
                    "unit": "decimal",
                    "source_type": assumptions["terminal_growth"].source_type,
                    "basis": (
                        "terminal growth policy with bear adjustment"
                        if assumptions["terminal_growth"].source_type == "model_policy"
                        else f"{assumptions['terminal_growth'].basis}; scenario adjustment applied"
                    ),
                    "source_fact_ids": [],
                    **(
                        {"source_urls": list(assumptions["terminal_growth"].source_urls)}
                        if assumptions["terminal_growth"].source_urls
                        else {}
                    ),
                },
            },
            "drivers": spec["drivers"],
            "forecast": forecast,
            "year_5": next((item for item in forecast if item["year"] == latest_year + 5), forecast[-1] if forecast else None),
            "terminal_year": forecast[-1] if forecast else None,
            "revenue_bridge": self._revenue_bridge(latest_year, first, latest_revenue),
            "fcf_bridge": self._fcf_bridge(fact_cache, latest_year, first),
            "valuation": dcf,
            "valuation_note": valuation_note,
        }

    def _revenue_bridge(self, latest_year: int, first: dict[str, Any] | None, current_revenue: float | None) -> dict[str, Any]:
        if first is None or current_revenue is None:
            return {"status": "insufficient_data", "items": []}
        delta = first["revenue"] - current_revenue
        calculation = first["evidence"]["revenue"].get("calculation") or ""
        is_driver_based = calculation != "prior revenue * (1 + scenario revenue growth)"
        return {
            "status": "driver_based" if is_driver_based else "partial",
            "from_year": latest_year,
            "to_year": first["year"],
            "items": [
                {"label": "Revenue actual", "value": current_revenue, "source_fact_ids": first["evidence"]["revenue"]["source_fact_ids"]},
                {
                    "label": "Cambio producido por drivers" if is_driver_based else "Crecimiento no atribuido",
                    "value": delta,
                    "source_fact_ids": first["evidence"]["revenue"]["source_fact_ids"],
                    "note": calculation,
                },
                {"label": "Revenue modelado", "value": first["revenue"], "source_fact_ids": first["evidence"]["revenue"]["source_fact_ids"]},
            ],
            "unavailable_drivers": [] if is_driver_based else ["price", "volume", "mix", "fx", "m_and_a", "churn"],
        }

    def _fcf_bridge(self, fact_cache: dict[str, list[FinancialFact]], latest_year: int, first: dict[str, Any] | None) -> dict[str, Any]:
        current_revenue = self._value_for_year(fact_cache["revenue"], latest_year)
        current_fcf = self._derived_fcf_value(fact_cache, latest_year)
        if first is None or current_revenue is None or current_fcf is None:
            return {"status": "insufficient_data", "items": []}
        current_margin = current_fcf / current_revenue if current_revenue else 0
        revenue_effect = (first["revenue"] - current_revenue) * current_margin
        margin_effect = first["revenue"] * ((first["fcf_margin"] or 0) - current_margin)
        return {
            "status": "partial",
            "from_year": latest_year,
            "to_year": first["year"],
            "items": [
                {"label": "FCF actual", "value": current_fcf, "source_fact_ids": first["evidence"]["free_cash_flow"]["source_fact_ids"]},
                {"label": "Escala de revenue", "value": revenue_effect, "source_fact_ids": first["evidence"]["revenue"]["source_fact_ids"]},
                {"label": "Cambio de margen FCF", "value": margin_effect, "source_fact_ids": first["evidence"]["free_cash_flow"]["source_fact_ids"]},
                {"label": "FCF modelado", "value": first["free_cash_flow"], "source_fact_ids": first["evidence"]["free_cash_flow"]["source_fact_ids"]},
            ],
            "unavailable_drivers": ["working_capital", "taxes_separately", "maintenance_capex", "growth_capex"],
        }

    def _model_price(
        self, db: Session, company: Company
    ) -> tuple[float | None, str | None, str | None]:
        """Precio del modelo en la divisa PRINCIPAL del listado, como ValuationService.

        El cierre se guarda como lo da el proveedor (Londres en peniques): usarlo
        crudo publicaba «precio del modelo 1.500 £» para una acción de 15 £.
        """
        from app.services.valuation_service import resolve_model_price

        price = resolve_model_price(db, company.id)
        if price is None:
            # resolve_model_price ya mira cierres y marks; None significa que no
            # hay precio o que no se puede pasar a la divisa del listado (cierre
            # en USD de una ficha en EUR sin tipo FX). Caer al cierre crudo
            # publicaba 250 USD como precio en EUR: N/D, como ValuationService.
            return None, None, None
        source = "market_price" if price.source == "market_close" else "position_mark"
        return price.value, _date_value(price.as_of), source

    def _reverse_dcf_price(
        self,
        db: Session,
        company: Company,
        *,
        fact_cache: dict[str, list[FinancialFact]],
        source_year: int | None,
    ) -> tuple[float | None, dict[str, Any]]:
        """Precio en la base de los hechos: divisa de reporte y acción ordinaria.

        Ingresos, FCF y acciones vienen del filing (BABA: CNY y acciones
        ordinarias) y el precio es el del listado (ADR en USD, 1 ADR = 8
        ordinarias; Londres en peniques). Sin convertir, el DCF inverso resolvía
        el crecimiento que justifica un precio en otra divisa y otra base de
        acciones. Misma regla que ValuationService: precio en divisa principal
        del listado, FX point-in-time a la de reporte y / ratio ADR.
        """
        from app.services.valuation_service import resolve_model_price

        price = resolve_model_price(db, company.id)
        if price is None:
            return None, {"missing_inputs": []}
        basis: dict[str, Any] = {
            "listed_price": price.value,
            "listed_currency": price.currency,
            "price_as_of": price.as_of.isoformat() if price.as_of else None,
        }
        if is_adr_without_ratio(company):
            return None, {**basis, "missing_inputs": ["adr_ratio"]}
        revenue_fact = self._fact_for_year(fact_cache["revenue"], source_year) if source_year is not None else None
        reporting = fact_currency(getattr(revenue_fact, "unit", None)) or price.currency
        value = price.value
        if reporting.upper() != price.currency.upper():
            fx = resolve_fx(db, price.currency, reporting, price.as_of or date.today())
            if fx is None:
                return None, {
                    **basis,
                    "reporting_currency": reporting,
                    "missing_inputs": [f"fx_rate:{reporting}/{price.currency.upper()}"],
                }
            value *= fx.rate
            basis["fx"] = fx.as_trace()
        ratio = adr_ratio(company)
        if ratio:
            value /= ratio
        basis.update(
            {
                "reporting_currency": reporting,
                "adr_ratio": ratio,
                "comparable_price": value,
                "comparable_price_basis": "ordinary_share_reporting_currency",
                "missing_inputs": [],
            }
        )
        return value, basis

    def _reverse_dcf(
        self,
        *,
        current_price: float | None,
        assumptions: dict[str, Assumption],
        fact_cache: dict[str, list[FinancialFact]],
        horizon: int,
        source_year: int | None,
        price_missing: list[str] | None = None,
    ) -> dict[str, Any]:
        revenue = self._value_for_year(fact_cache["revenue"], source_year)
        shares = self._value_for_year(fact_cache["shares_diluted"], source_year)
        margin = assumptions["fcf_margin"].value
        wacc = assumptions["wacc"].value
        terminal = assumptions["terminal_growth"].value
        net_debt = self._value_for_year(fact_cache["net_debt"], source_year)
        # Un valor no positivo (ingreso anual 0 tras parar la actividad, acciones
        # <= 0, precio <= 0) no es un dato utilizable: sin esto el solver lanzaba
        # ValueError y tumbaba la generacion entera de la tesis (HYMC).
        if current_price is not None and current_price <= 0:
            current_price = None
        if revenue is not None and revenue <= 0:
            revenue = None
        if shares is not None and shares <= 0:
            shares = None
        if current_price is None or revenue is None or shares is None or margin is None or wacc is None or terminal is None or net_debt is None or wacc <= terminal:
            # Missing net debt is never treated as "debt-free": the forward
            # DCF refuses without it, the reverse DCF does the same.
            # Solo se declara lo que falta de verdad: la lista fija decia "falta el
            # precio de mercado" aunque el precio existiera (ASTS).
            missing = list(price_missing or []) + [
                name
                for name, value in (
                    ("market_price", current_price),
                    ("revenue", revenue),
                    ("fcf_margin", margin),
                    ("wacc", wacc),
                    ("terminal_growth", terminal),
                    ("shares_diluted", shares),
                    ("net_debt", net_debt),
                )
                if value is None and not (name == "market_price" and price_missing)
            ]
            return {"status": "insufficient_data", "market_price": current_price, "missing_inputs": missing, "trace": {"method": "binary_search_reverse_dcf", "source_fact_ids": assumptions["fcf_margin"].source_fact_ids}}
        reverse_inputs = ReverseDCFInputs(
            market_price=current_price,
            revenue=revenue,
            fcf_margin=margin,
            wacc=wacc,
            terminal_growth=terminal,
            net_debt=net_debt,
            shares_outstanding=shares,
            years=horizon,
        )
        solved = solve_required_growth(reverse_inputs)
        required = solved.get("required_revenue_growth")
        base_growth = assumptions["revenue_growth"].value
        # «Crecimiento implícito» (idea Jera Value): lectura simple g = WACC − FCF/EV, qué parte del
        # valor que paga el precio llega en los años 1–5, 6–10 y 11+, y la rejilla WACC × margen.
        enterprise_value = current_price * shares + net_debt
        implied = {
            "implied_perpetual_growth": implied_perpetual_growth(
                fcf=revenue * margin, enterprise_value=enterprise_value, wacc=wacc
            ),
            "value_split": (
                value_split(
                    revenue=revenue, growth=required, fcf_margin=margin, wacc=wacc,
                    terminal_growth=terminal, years=horizon,
                )
                if required is not None
                else None
            ),
            "sensitivity": growth_sensitivity(reverse_inputs) if margin > 0 else None,
        }
        return {
            "status": solved.get("status", "ok"),
            **solved,
            **implied,
            "base_revenue_growth": assumptions["revenue_growth"].value,
            "fcf_margin": margin,
            "wacc": wacc,
            # Sin crecimiento base conocido no hay brecha: antes se restaba 0 y
            # la brecha publicada era el crecimiento exigido entero.
            "growth_gap_vs_base": (
                (required - base_growth)
                if required is not None and base_growth is not None
                else None
            ),
            "source_fact_ids": _unique_ids(ids=assumptions["revenue_growth"].source_fact_ids + assumptions["fcf_margin"].source_fact_ids),
            "trace": {**solved["trace"], "source_fact_ids": assumptions["revenue_growth"].source_fact_ids + assumptions["fcf_margin"].source_fact_ids, "horizon_years": horizon},
        }

    def _capital_allocation(
        self,
        *,
        fact_cache: dict[str, list[FinancialFact]],
        revenue_history: dict[int, FinancialFact],
        years: list[int],
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        shares = self._series(fact_cache, "shares_diluted", years)
        metrics["share_count_cagr"] = self._metric_value(
            None if _has_unexplained_share_jump(shares) else self._cagr(shares),
            "decimal", [fact_id for item in shares for fact_id in item["fact_ids"]], "diluted shares CAGR")
        for metric, label in (("common_stock_repurchased", "buyback_to_revenue"), ("dividends_paid", "dividend_to_revenue")):
            values: list[float] = []
            ids: list[int] = []
            for year, revenue_fact in revenue_history.items():
                action_fact = self._fact_for_year(fact_cache[metric], year)
                revenue = _float(revenue_fact.value)
                action = _float(action_fact.value) if action_fact else None
                if revenue and action is not None:
                    values.append(abs(action) / revenue)
                    ids.extend([revenue_fact.id, action_fact.id])
            metrics[label] = self._metric_value(median(values[-5:]) if values else None, "decimal", _unique_ids(ids=ids), f"median {metric} / revenue")
        fcf = self._derived_fcf_series(fact_cache, years)
        net_income = self._series(fact_cache, "net_income", years)
        metrics["fcf_conversion"] = self._ratio_metric(fcf, net_income, "free_cash_flow / net_income")
        net_debt = self._series(fact_cache, "net_debt", years)
        ebitda = self._series(fact_cache, "ebitda", years)
        metrics["net_debt_to_ebitda"] = self._ratio_metric(net_debt, ebitda, "net_debt / ebitda")
        metrics["reinvestment_rate"] = {"value": None, "unit": "decimal", "status": "insufficient_data", "source_fact_ids": [], "note": "Requires maintenance capex and normalized working capital."}
        available = [item for item in metrics.values() if item.get("value") is not None]
        return {
            "status": "partial" if available else "insufficient_data",
            "metrics": metrics,
            "conclusion": "Review historical capital allocation against share count and FCF conversion; M&A ROI is not sourced yet.",
            "missing_inputs": ["m_and_a_purchase_price_and_post_deal_returns", "maintenance_capex", "normalized_working_capital"],
        }

    def _quality_of_growth(
        self,
        *,
        fact_cache: dict[str, list[FinancialFact]],
        revenue_history: dict[int, FinancialFact],
        years: list[int],
    ) -> dict[str, Any]:
        growth = self._cagr(self._series(fact_cache, "revenue", years))
        fcf = self._derived_fcf_series(fact_cache, years)
        revenue = self._series(fact_cache, "revenue", years)
        margin_by_year = {item["year"]: item["value"] / next(x["value"] for x in revenue if x["year"] == item["year"]) for item in fcf if next((x["value"] for x in revenue if x["year"] == item["year"]), None)}
        margin_change = None
        if len(margin_by_year) >= 2:
            margin_change = margin_by_year[max(margin_by_year)] - margin_by_year[min(margin_by_year)]
        _shares_series_qg = self._series(fact_cache, "shares_diluted", years)
        shares_cagr = (
            None if _has_unexplained_share_jump(_shares_series_qg) else self._cagr(_shares_series_qg)
        )
        if growth is None:
            quality = "unknown"
        elif margin_change is not None and (shares_cagr is None or shares_cagr <= 0) and margin_change >= -0.01:
            quality = "high"
        elif margin_change is not None or shares_cagr is not None:
            quality = "medium"
        else:
            quality = "unknown"
        ids = [fact.id for fact in revenue_history.values()]
        return {
            "status": "ok" if growth is not None else "insufficient_data",
            "quality": quality,
            "revenue_cagr": self._metric_value(growth, "decimal", ids, "annual revenue CAGR"),
            "fcf_margin_change": self._metric_value(margin_change, "decimal", [fact_id for item in fcf for fact_id in item["fact_ids"]] + ids, "latest FCF margin minus earliest FCF margin"),
            "share_count_cagr": self._metric_value(shares_cagr, "decimal", self._fact_ids_for_metric(fact_cache["shares_diluted"]), "diluted share count CAGR"),
            "unavailable_drivers": ["pricing", "volume", "mix", "fx", "m_and_a", "cyclical_vs_structural"],
            "conclusion": "Growth quality is a partial assessment until price/volume/mix, M&A and working-capital drivers are sourced.",
        }

    def _owner_earnings(self, fact_cache: dict[str, list[FinancialFact]], year: int | None) -> dict[str, Any]:
        """Beneficio del propietario de Buffett (carta de Berkshire de 1986).

        OE = beneficio neto + D&A + ΔCC (signo de flujo de caja) − |capex de
        mantenimiento|. Fórmula, signos y regla de estimación del
        mantenimiento en app/services/owner_earnings.py (la misma que usan
        las métricas calculadas). Sin ΔCC no hay número: tomarlo como 0
        afirmaría que el circulante no se movió.
        """
        net_income = self._fact_for_year(fact_cache["net_income"], year)
        # Ingestion writes the canonical key depreciation_amortization; the legacy
        # depreciation_and_amortization key is only a fallback (F410).
        dna = self._fact_for_year(fact_cache["depreciation_amortization"], year) or self._fact_for_year(
            fact_cache["depreciation_and_amortization"], year
        )
        maintenance = self._fact_for_year(fact_cache["maintenance_capex"], year)
        capex = self._fact_for_year(fact_cache["capital_expenditure"], year)
        wc = self._fact_for_year(fact_cache["change_in_working_capital"], year)
        missing = [
            label
            for label, present in (
                ("net_income", net_income is not None),
                ("depreciation_and_amortization", dna is not None),
                ("maintenance_capex_or_capital_expenditure", maintenance is not None or capex is not None),
                ("change_in_working_capital", wc is not None),
            )
            if not present
        ]
        base = {
            "formula": OWNER_EARNINGS_FORMULA,
            "working_capital_sign": WORKING_CAPITAL_SIGN_CONVENTION,
            "source": "Buffett, Berkshire Hathaway shareholder letter 1986",
        }
        if missing:
            return {**base, "status": "insufficient_data", "value": None, "missing_inputs": missing, "source_fact_ids": _unique_ids(net_income)}
        assert net_income is not None and dna is not None and wc is not None

        def _dec(fact: FinancialFact | None) -> Decimal | None:
            return Decimal(str(fact.value)) if fact is not None and fact.value is not None else None

        result = owner_earnings(
            net_income=_dec(net_income) or Decimal("0"),
            depreciation_amortization=_dec(dna) or Decimal("0"),
            change_in_working_capital=_dec(wc) or Decimal("0"),
            capital_expenditure=_dec(capex),
            maintenance_capex=_dec(maintenance),
        )
        if result is None:
            return {**base, "status": "insufficient_data", "value": None, "missing_inputs": ["maintenance_capex_or_capital_expenditure"], "source_fact_ids": _unique_ids(net_income)}
        return {
            **base,
            "status": "ok",
            "value": float(result.value),
            "maintenance_capex": float(result.maintenance_capex),
            "maintenance_capex_rule": result.maintenance_capex_rule,
            "estimated_growth_capex": float(result.estimated_growth_capex) if result.estimated_growth_capex is not None else None,
            "change_in_working_capital": float(_dec(wc) or 0),
            "source_fact_ids": _unique_ids(net_income, dna, maintenance, capex, wc),
            "period": net_income.period,
        }

    def _capex_analysis(self, fact_cache: dict[str, list[FinancialFact]], year: int | None) -> dict[str, Any]:
        total = self._fact_for_year(fact_cache["capital_expenditure"], year)
        maintenance = self._fact_for_year(fact_cache["maintenance_capex"], year)
        if total is None:
            return {"status": "insufficient_data", "total_capex": None, "maintenance_capex": None, "growth_capex": None, "missing_inputs": ["capital_expenditure"]}
        total_value = abs(_float(total.value) or 0)
        if maintenance is None:
            return {"status": "partial", "total_capex": total_value, "maintenance_capex": None, "growth_capex": None, "maintenance_vs_growth": "not_separately_reported", "missing_inputs": ["maintenance_capex"], "source_fact_ids": [total.id]}
        maintenance_value = abs(_float(maintenance.value) or 0)
        return {"status": "ok", "total_capex": total_value, "maintenance_capex": maintenance_value, "growth_capex": max(0, total_value - maintenance_value), "source_fact_ids": _unique_ids(total, maintenance)}

    def _what_must_be_true(
        self,
        *,
        assumptions: dict[str, Assumption],
        reverse_dcf: dict[str, Any],
        base_scenario: dict[str, Any] | None,
        fact_cache: dict[str, list[FinancialFact]],
        latest_year: int | None,
        market_opportunity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = []
        growth = assumptions["revenue_growth"].value
        margin = assumptions["fcf_margin"].value
        if growth is not None:
            conditions.append({"id": "revenue_growth", "condition": f"Revenue CAGR must be at least {growth:.1%}", "value": growth, "unit": "decimal", "source_fact_ids": assumptions["revenue_growth"].source_fact_ids, "status": "monitor"})
        if margin is not None:
            conditions.append({"id": "fcf_margin", "condition": f"Normalized FCF margin must remain at least {margin:.1%}", "value": margin, "unit": "decimal", "source_fact_ids": assumptions["fcf_margin"].source_fact_ids, "status": "monitor"})
        if base_scenario and base_scenario.get("terminal_year", {}).get("roic") is not None:
            roic = base_scenario["terminal_year"]["roic"]
            wacc = assumptions["wacc"].value
            conditions.append({"id": "roic_above_wacc", "condition": "ROIC must remain above WACC to create value", "value": roic, "comparison": wacc, "unit": "decimal", "source_fact_ids": base_scenario["terminal_year"]["evidence"]["roic"]["source_fact_ids"], "status": "monitor"})
        if reverse_dcf.get("status") == "ok" and reverse_dcf.get("required_revenue_growth") is not None:
            required = reverse_dcf["required_revenue_growth"]
            conditions.append({"id": "price_expectations", "condition": f"The current price requires revenue growth of about {required:.1%}", "value": required, "comparison": reverse_dcf.get("fcf_margin"), "unit": "decimal", "source_fact_ids": reverse_dcf.get("source_fact_ids", []), "status": "valuation_implied"})
        elif reverse_dcf.get("out_of_bounds"):
            # The price is outside every valueable scenario: there is no
            # required growth to state, and inventing one from the search
            # bound would read as a forecast.
            conditions.append({"id": "price_expectations", "condition": f"The current price is outside the valueable range: {reverse_dcf.get('reason', 'no achievable growth reproduces this price')}", "value": None, "unit": "decimal", "source_fact_ids": reverse_dcf.get("source_fact_ids", []), "status": "out_of_bounds"})
        if self._fact_for_year(fact_cache["shares_diluted"], latest_year) is not None:
            conditions.append({"id": "share_count", "condition": "Share count must not expand faster than the model assumption", "value": assumptions["shares_cagr"].value, "unit": "decimal", "source_fact_ids": assumptions["shares_cagr"].source_fact_ids, "status": "monitor"})
        market_share = market_opportunity.get("market_share", {})
        conditions.append({
            "id": "competitive_position",
            "condition": "Market share must not deteriorate materially",
            "value": market_share.get("base_future_market_share"),
            "unit": "decimal",
            "source_fact_ids": market_share.get("source_fact_ids", []),
            "status": "monitor" if market_share.get("base_future_market_share") is not None else "blocked_missing_market_opportunity_data",
        })
        conditions.append({
            "id": "binding_constraint",
            "condition": f"The binding constraint must support the base case: {market_opportunity.get('constraints', {}).get('binding_constraint') or 'unknown'}",
            "value": None,
            "unit": "constraint",
            "source_fact_ids": market_opportunity.get("source_fact_ids", []),
            "status": "monitor" if market_opportunity.get("constraints", {}).get("binding_constraint") else "blocked_missing_market_opportunity_data",
        })
        return conditions

    def _timeline(self, db: Session, company_id: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for event in db.scalars(select(NewsEvent).where(NewsEvent.company_id == company_id).order_by(desc(NewsEvent.date)).limit(30)).all():
            events.append({"date": _date_value(event.date), "type": event.event_type, "title": event.title, "source": event.source, "source_url": event.url, "financial_impact": event.affected_assumptions, "thesis_impact": event.impact_direction, "moat_impact": "unknown", "management_credibility": "unknown"})
        for change in db.scalars(select(ThesisChange).where(ThesisChange.company_id == company_id).order_by(desc(ThesisChange.created_at)).limit(30)).all():
            events.append({"date": _date_value(change.created_at), "type": change.change_type, "title": change.summary, "source": "thesis_change", "source_url": None, "financial_impact": change.affected_metrics, "thesis_impact": change.impact_direction, "moat_impact": "unknown", "management_credibility": "unknown"})
        return sorted(events, key=lambda item: item.get("date") or "", reverse=True)[:40]

    def _coverage(self, history: list[dict[str, Any]], assumptions: dict[str, Assumption], scenarios: dict[str, Any]) -> dict[str, Any]:
        total = 0
        sourced = 0
        for row in history:
            for line in row.get("metrics", {}).values():
                if line.get("value") is not None:
                    total += 1
                    sourced += bool(line.get("source_fact_ids"))
        for assumption in assumptions.values():
            if assumption.value is not None:
                total += 1
                sourced += bool(assumption.source_fact_ids) or assumption.source_type == "model_policy"
        for scenario in scenarios.values():
            for item in scenario.get("forecast", []):
                for key in ("revenue", "free_cash_flow", "fcf_per_share"):
                    if item.get(key) is not None:
                        total += 1
                        sourced += bool(item.get("evidence", {}).get(key, {}).get("source_fact_ids"))
        return {"coverage_percent": round((sourced / total) * 100, 1) if total else 0, "sourced_values": sourced, "numeric_values": total, "rule": "Policy assumptions are disclosed separately; company numbers require source_fact_ids."}

    def _limitations(
        self,
        *,
        fact_cache: dict[str, list[FinancialFact]],
        years: list[int],
        missing_core: list[str],
        market_opportunity: dict[str, Any],
    ) -> list[str]:
        limitations = list(missing_core)
        if not fact_cache["working_capital"]:
            limitations.append("working_capital_and_absorption")
        if not fact_cache["maintenance_capex"]:
            limitations.append("maintenance_vs_growth_capex_split")
        if market_opportunity["status"] == "insufficient_data":
            limitations.append("market_opportunity")
        if len(years) < 5:
            limitations.append("full_10_year_history")
        return sorted(set(limitations))

    @staticmethod
    def _metric_value(value: float | None, unit: str, source_fact_ids: list[int], calculation: str) -> dict[str, Any]:
        return {"value": value, "unit": unit, "status": "calculated" if value is not None else "insufficient_data", "source_fact_ids": _unique_ids(ids=source_fact_ids), "calculation": calculation}

    def _ratio_metric(self, numerator: list[dict[str, Any]], denominator: list[dict[str, Any]], calculation: str) -> dict[str, Any]:
        denominator_by_year = {item["year"]: item for item in denominator}
        values: list[float] = []
        ids: list[int] = []
        for item in numerator:
            other = denominator_by_year.get(item["year"])
            if other and other["value"] not in (None, 0) and item["value"] is not None:
                values.append(item["value"] / other["value"])
                ids.extend(item["fact_ids"] + other["fact_ids"])
        return self._metric_value(median(values[-5:]) if values else None, "decimal", ids, calculation)

    @staticmethod
    def _fact_ids_for_metric(facts: list[FinancialFact]) -> list[int]:
        return [fact.id for fact in facts if fact.fiscal_year is not None and _is_annual(fact)]
