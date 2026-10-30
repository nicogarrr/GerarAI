import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.core.units import is_from_percent, to_fraction
from app.models import CalculatedMetric, Company, FinancialFact
from app.services.moat_profile import NONCOMPARABLE_PROFILES, PROFILE_LABELS, financial_quality_profile
from app.services.owner_earnings import WORKING_CAPITAL_SIGN_CONVENTION, owner_earnings

MetricFormula = tuple[str, str, tuple[str, ...], str]

CFROI_REQUIRED_INPUTS = (
    "gross_investment",
    "non_depreciating_assets",
    "inflation_adjusted_gross_cash_flow",
    "asset_life",
    "terminal_non_depreciating_assets",
)

# Métricas del marco de calidad: medias de ratios anuales en una
# ventana de hasta 5 años fiscales (mínimo 3). metric -> (numerador, denominador)
WINDOWED_RATIO_METRICS: dict[str, tuple[str, str]] = {
    "fcf_margin_5y": ("free_cash_flow", "revenue"),
    "net_margin_5y": ("net_income", "revenue"),
    "roe_5y": ("net_income", "total_equity"),
    "roa_5y": ("net_income", "total_assets"),
}

WINDOW_MIN_YEARS = 3
WINDOW_MAX_YEARS = 5

# Umbrales MARCO_V2 (criterios estandar value/Buffett, elegidos el 2026-09-25).
# Documentados en /metodologia para que pueda ajustarlos despues:
# - owner earnings (Buffett, carta 1986): la media de hasta 5 anos debe ser
#   positiva.
# - intensidad de capex: |capex|/D&A medio <= 1.5 (1.0 = solo mantenimiento;
#   hasta 1.5 admite crecimiento sin ser devorador de capital).
# - CFROI (aprox declarada) > WACC: creacion de valor en terminos de caja,
#   complementario al ROIC > WACC contable.
V2_OWNER_EARNINGS_MIN = Decimal("0")
V2_CAPEX_TO_DA_MAX = Decimal("1.5")

# Metricas compuestas con ventana propia (no caben en WINDOWED_RATIO_METRICS).
WINDOWED_COMPOSED_METRICS = ("owner_earnings_5y", "capex_to_da_5y")

# F153: con periodos coherentes, un margen > 100% puede ser REAL (venta de
# activos, reversion fiscal, liberacion de circulante). No se declara «sin
# datos» - eso violaria veracidad: se calcula y se etiqueta de atipico en la
# traza, con numerador y denominador visibles para su verificacion.
MARGIN_METRICS = ("gross_margin", "operating_margin", "net_margin", "fcf_margin")

# Ratios cuyo denominador negativo no es interpretable: se publican N/D en
# vez de una cifra engañosa (Damodaran, "Return Measures": NI −50 / patrimonio
# −200 = +25 % con pérdidas; EBITDA −10 con deuda neta 100 = −10x, que parece
# mejor que 2x). Márgenes sobre ingresos negativos, igual.
POSITIVE_DENOMINATOR_METRICS = frozenset(
    {
        "roe",
        "roa",
        "roic",
        "roic_adjusted",
        "net_debt_to_ebitda",
        "fcf_conversion",
        "fcf_margin",
        "net_margin",
        "operating_margin",
        "gross_margin",
    }
)

METRIC_DEFINITIONS: dict[str, MetricFormula] = {
    "fcf_margin": ("FCF_MARGIN_V1", "free_cash_flow / revenue", ("free_cash_flow", "revenue"), "decimal"),
    "net_margin": ("NET_MARGIN_V1", "net_income / revenue", ("net_income", "revenue"), "decimal"),
    "operating_margin": ("OPERATING_MARGIN_V1", "operating_income / revenue", ("operating_income", "revenue"), "decimal"),
    "gross_margin": ("GROSS_MARGIN_V1", "gross_profit / revenue", ("gross_profit", "revenue"), "decimal"),
    "roe": ("ROE_V1", "net_income / total_equity", ("net_income", "total_equity"), "decimal"),
    "roa": ("ROA_V1", "net_income / total_assets", ("net_income", "total_assets"), "decimal"),
    "fcf_conversion": ("FCF_CONVERSION_V1", "free_cash_flow / net_income", ("free_cash_flow", "net_income"), "decimal"),
    "net_debt_to_ebitda": ("NET_DEBT_TO_EBITDA_V1", "net_debt / ebitda", ("net_debt", "ebitda"), "x"),
    "roic": (
        "ROIC_STANDARD_V2",
        "operating_income * (1 - effective_tax_rate) / average(total_debt + total_equity - cash_and_equivalents), using current invested capital when no coherent prior period exists",
        ("operating_income", "total_debt", "total_equity", "cash_and_equivalents"),
        "decimal",
    ),
    "roic_adjusted": (
        "ROIC_ADJUSTED_V1",
        "operating_income * (1 - effective_tax_rate) / adjusted_invested_capital, where adjusted_invested_capital = total_debt + total_equity - cash_and_equivalents - goodwill - intangible_assets + operating_lease_liabilities",
        (
            "operating_income",
            "total_debt",
            "total_equity",
            "cash_and_equivalents",
            "goodwill",
            "intangible_assets",
            "operating_lease_liabilities",
        ),
        "decimal",
    ),
    "wacc": (
        "WACC_STANDARD_V1",
        "equity_weight * (risk_free_rate + beta * equity_risk_premium + country_risk_premium) + debt_weight * cost_of_debt * (1 - tax_rate)",
        ("risk_free_rate", "beta", "equity_risk_premium", "total_debt"),
        "decimal",
    ),
    "cfroi": (
        "CFROI_V1",
        "inflation-adjusted internal rate of return on gross investment; no proxy calculation is permitted",
        CFROI_REQUIRED_INPUTS,
        "decimal",
    ),
    "fcf_margin_5y": (
        "FCF_MARGIN_5Y_V1",
        "mean of annual free_cash_flow / revenue over up to 5 most recent fiscal years, minimum 3; coverage declared in trace",
        ("free_cash_flow", "revenue"),
        "decimal",
    ),
    "net_margin_5y": (
        "NET_MARGIN_5Y_V1",
        "mean of annual net_income / revenue over up to 5 most recent fiscal years, minimum 3; coverage declared in trace",
        ("net_income", "revenue"),
        "decimal",
    ),
    "roe_5y": (
        "ROE_5Y_V1",
        "mean of annual net_income / total_equity over up to 5 most recent fiscal years, minimum 3; coverage declared in trace",
        ("net_income", "total_equity"),
        "decimal",
    ),
    "roa_5y": (
        "ROA_5Y_V1",
        "mean of annual net_income / total_assets over up to 5 most recent fiscal years, minimum 3; coverage declared in trace",
        ("net_income", "total_assets"),
        "decimal",
    ),
    # Beneficio del propietario (Buffett, carta de Berkshire Hathaway de
    # 1986). Definicion unica en app/services/owner_earnings.py: el ΔCC va en
    # signo de flujo de caja y se SUMA; sin ΔCC no hay numero (V1 lo omitia).
    "owner_earnings": (
        "OWNER_EARNINGS_V2",
        "net_income + depreciation_amortization + change_in_working_capital - maintenance_capex, where change_in_working_capital is in cash-flow sign (negative = working capital absorbed cash) and maintenance_capex = min(abs(capital_expenditure), depreciation_amortization); maintenance capex is not separately reported - declared conservative estimate (Buffett owner earnings, Berkshire Hathaway 1986 letter)",
        ("net_income", "depreciation_amortization", "capital_expenditure", "change_in_working_capital"),
        "USD",
    ),
    "cfroi_approx": (
        "CFROI_APPROX_V1",
        "approximate CFROI: (net_income + depreciation_amortization + interest_expense * (1 - effective_tax_rate)) / total_assets; DECLARED approximation - invested capital proxied by total_assets, no inflation adjustment, not comparable to Credit Suisse CFROI",
        ("net_income", "depreciation_amortization", "interest_expense", "total_assets"),
        "decimal",
    ),
    "owner_earnings_5y": (
        "OWNER_EARNINGS_5Y_V2",
        "mean of annual (net_income + depreciation_amortization + change_in_working_capital - min(abs(capital_expenditure), depreciation_amortization)) over up to 5 most recent fiscal years, minimum 3; change_in_working_capital in cash-flow sign; maintenance capex is a declared conservative estimate (Buffett owner earnings, Berkshire Hathaway 1986 letter)",
        ("net_income", "depreciation_amortization", "capital_expenditure", "change_in_working_capital"),
        "USD",
    ),
    "capex_to_da_5y": (
        "CAPEX_TO_DA_5Y_V1",
        "mean of annual abs(capital_expenditure) / depreciation_amortization over up to 5 most recent fiscal years, minimum 3; 1.0 = maintenance-only investment, higher = growth or capital intensity",
        ("capital_expenditure", "depreciation_amortization"),
        "decimal",
    ),
    # FCF antes de gasto de crecimiento (apuntes manuscritos, oct 2026):
    # la caja que generaria el negocio invirtiendo solo en mantenerse.
    # La separacion mantenimiento/crecimiento no se publica: estimacion
    # declarada, misma regla que owner_earnings.
    "fcf_before_growth_capex": (
        "FCF_BEFORE_GROWTH_CAPEX_V1",
        "free_cash_flow + estimated_growth_capex, where estimated_growth_capex = abs(capital_expenditure) - maintenance_capex and maintenance_capex = min(abs(capital_expenditure), depreciation_amortization); the maintenance/growth split is not separately reported - declared estimate",
        ("free_cash_flow", "capital_expenditure", "depreciation_amortization"),
        "USD",
    ),
    # Marco de calidad (apuntes manuscritos, sept 2026): 5 checks
    # trazables. Cada check no evaluable queda declarado como null, nunca
    # cuenta como superado.
    "quality_moat_score": (
        "MARCO_V1",
        "count of passed checks: fcf_margin_5y > 0.05, net_margin_5y > 0.15, roe_5y > 0.15, roa_5y > 0.07, roic > wacc; each check traceable with its value and threshold",
        (),
        "score",
    ),
    # V2 (2026-09-25): los 5 checks de V1 mas tres de caja y disciplina de
    # capital. Umbrales elegidos el 2026-09-25 y documentados en
    # /metodologia; cada check no evaluable queda null, nunca cuenta.
    "quality_moat_score_v2": (
        "MARCO_V2",
        "V1 checks (fcf_margin_5y > 0.05, net_margin_5y > 0.15, roe_5y > 0.15, roa_5y > 0.07, roic > wacc) plus cfroi_approx > wacc, owner_earnings_5y > 0, capex_to_da_5y <= 1.5; each check traceable with its value and threshold",
        (),
        "score",
    ),
}


@dataclass
class MetricResult:
    metric: str
    status: str
    period: str
    value: Decimal | None
    unit: str
    definition_version: str
    formula: str
    numerator: Decimal | None
    denominator: Decimal | None
    source_fact_ids: list[int]
    calculation_trace: dict
    confidence: Decimal
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    id: int | None = None


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


# Fuentes cuyos importes monetarios llegan en unidades absolutas: market data
# (yfinance, Finnhub) y hechos SEC/FMP. Entre ellas, con la misma unidad, un
# ratio extremo entre capitalizacion y deuda es estructura de capital real
# (una mega-cap casi sin deuda), NO un error de unidades.
_ABSOLUTE_AMOUNT_SOURCES = frozenset({"yfinance", "Finnhub", "SEC", "FMP"})


# Rango plausible de una beta de MERCADO. Fuera de el el fact no es una beta:
# o la ventana de regresion es tan corta que la covarianza con el mercado no
# llega a ser significativa (beta 0,15), o el proveedor entrego otra magnitud
# con la escala mal leida (una beta de 5 suele ser un 0,5 con la escala x10),
# y una beta negativa no describe un equity. El impacto no es academico: con
# rf 3,0%, ERP 5,5% y beta 0,15 el coste de equity cae a 3,8%, el WACC a 3,9%,
# el spread sobre g=2,5% queda en 1,4pp y el PV del valor terminal se
# multiplica por ~3,4 con el DCF marcado publicable. No se recorta al extremo
# mas cercano: recortar es inventar una beta. El input se declara ausente.
BETA_PLAUSIBLE_RANGE = (Decimal("0.2"), Decimal("3.0"))


def _beta_is_plausible(beta: Decimal) -> bool:
    low, high = BETA_PLAUSIBLE_RANGE
    return low <= beta <= high


def _gated_input(
    name: str,
    reason: str,
    detail: str,
    *,
    value: Decimal | None = None,
) -> dict:
    """Entrada que el gate de honestidad del WACC se niega a usar.

    Se registra en el ``calculation_trace`` para que el motivo sea auditable.
    ``resolution`` es siempre ``treated_as_absent``: un input que no supera el
    gate vale exactamente lo mismo que un input que no existe, y su valor no
    se sustituye por un default.
    """
    return {
        "input": name,
        "value": None if value is None else str(value),
        "reason": reason,
        "resolution": "treated_as_absent",
        "detail": detail,
    }


def _capital_scale_conflict(equity_fact: FinancialFact, debt_fact: FinancialFact) -> bool:
    """True si equity y debt no son comparables para el WACC.

    Fail-closed, en este orden:
    - Unidades monetarias explicitas y distintas (USD vs EUR): conflicto
      siempre. No es un error de escala sino de divisa, y ninguna
      provenance lo rescata: un par de fuentes "absolutas" no es
      comparable si cada una expresa otra moneda.
    - Ambas fuentes absolutas y misma unidad: comparables a cualquier
      ratio (una mega-cap casi sin deuda supera 100x de forma real).
    - Cualquier otra combinacion (ESEF sin escala persistida, o
      provenance incierta): conflicto siempre, a cualquier magnitud.
      Un ratio razonable no demuestra unidades compatibles; el atajo
      del 100x dejaba pasar mezclas no verificables.

    Nunca se deduce un factor de escala ni de divisa: si no son
    comparables, el metodo queda unavailable en vez de publicar un WACC
    inventado.
    """
    if debt_fact.value == 0:
        return False
    if (
        equity_fact.unit
        and debt_fact.unit
        and equity_fact.unit != debt_fact.unit
    ):
        return True
    if (
        equity_fact.source_type in _ABSOLUTE_AMOUNT_SOURCES
        and debt_fact.source_type in _ABSOLUTE_AMOUNT_SOURCES
        and equity_fact.unit == debt_fact.unit
    ):
        return False
    return True


# Clave de db.info para la cache de hechos de calculate_all (ver alli).
_FACTS_CACHE_KEY = "metric_calculation_facts_cache"
# Hechos que lee _facts_for_metric por metrica (tope y orden comunes al
# camino de una metrica y a la precarga de calculate_all).
_FACTS_PER_METRIC = 20


# Orden de los hechos de una metrica: ejercicio mas reciente, luego el
# ultimo guardado; el id desempata para que el resultado sea determinista.
_FACT_ORDER = (
    FinancialFact.fiscal_year.desc().nullslast(),
    desc(FinancialFact.created_at),
    FinancialFact.id.asc(),
)
# Insumos de todas las formulas + alias que leen el tipo fiscal y el WACC.
_PREFETCH_METRICS = frozenset(
    {name for _, _, inputs, _ in METRIC_DEFINITIONS.values() for name in inputs}
    | {
        "cost_of_debt", "country_risk_premium", "effective_tax_rate", "tax_rate",
        "income_before_tax", "pretax_income", "income_before_taxes", "income_tax_expense",
        "tax_expense", "market_cap", "market_capitalization",
    }
)


class MetricCalculationService:
    def calculate_all(self, db: Session, company: Company, persist: bool = True) -> list[MetricResult]:
        # Cache de hechos SOLO durante este calculate_all: muchas metricas
        # comparten entradas (revenue, net_income...) y cada una repetia la
        # misma consulta. Vive en db.info (sesion por peticion, nunca
        # compartida entre hilos) y se borra al terminar, asi que una llamada
        # posterior ve siempre los hechos frescos.
        owns_cache = _FACTS_CACHE_KEY not in db.info
        if owns_cache:
            db.info[_FACTS_CACHE_KEY] = {}
            self._prefetch_facts(db, company, db.info[_FACTS_CACHE_KEY])
        try:
            results = [self.calculate(db, company, metric, persist=persist) for metric in METRIC_DEFINITIONS]
        finally:
            if owns_cache:
                db.info.pop(_FACTS_CACHE_KEY, None)
        if persist:
            db.commit()
        return results

    def calculate(self, db: Session, company: Company, metric: str, persist: bool = True) -> MetricResult:
        if metric not in METRIC_DEFINITIONS:
            raise ValueError(f"Unsupported calculated metric: {metric}")
        definition_version, formula, inputs, unit = METRIC_DEFINITIONS[metric]

        if metric == "wacc":
            return self._calculate_wacc(db, company, persist)
        if metric == "cfroi":
            return self._calculate_cfroi(db, company, persist)
        if metric in WINDOWED_RATIO_METRICS:
            return self._calculate_windowed_ratio(db, company, metric, persist)
        if metric in WINDOWED_COMPOSED_METRICS:
            return self._calculate_windowed_composed(db, company, metric, persist)
        if metric == "quality_moat_score":
            return self._calculate_quality_score(db, company, persist)
        if metric == "quality_moat_score_v2":
            return self._calculate_quality_score_v2(db, company, persist)
        if metric == "fcf_before_growth_capex":
            return self._calculate_fcf_before_growth_capex(db, company, persist)

        facts = self._coherent_facts(
            db,
            company,
            inputs,
            strict=metric in {"roic", "roic_adjusted"},
        )
        missing_inputs = [input_metric for input_metric in inputs if input_metric not in facts]
        period = self._period_for_result(facts)

        if missing_inputs:
            first = next(iter(facts.values()), None)
            result = MetricResult(
                metric=metric,
                status="unavailable",
                period=period,
                value=None,
                unit=unit,
                definition_version=definition_version,
                formula=formula,
                numerator=None,
                denominator=None,
                source_fact_ids=[fact.id for fact in facts.values()],
                calculation_trace={
                    "reason": (
                        "missing_or_incoherent_inputs"
                        if metric in {"roic", "roic_adjusted"}
                        else "missing_inputs"
                    ),
                    "missing_inputs": missing_inputs,
                    "available_inputs": sorted(facts),
                },
                confidence=Decimal("0.00"),
                fiscal_year=first.fiscal_year if first else None,
                fiscal_quarter=first.fiscal_quarter if first else None,
            )
            return self._persist_if_requested(db, company, result, persist)

        # F153: un ratio exige coincidencia de periodo entre numerador y
        # denominador. El fallback no estricto de _coherent_facts toma el
        # ultimo hecho de cada metrica aunque sean de periodos distintos -
        # asi se compuso un net_margin del 834% (net_income FY2026 sobre
        # revenue FY2010) que Comparables exponia como benchmark. Si los
        # periodos no coinciden (mismo fin de periodo o mismo ano/trimestre
        # fiscal), el ratio es «sin datos», nunca el cociente.
        anchor_fact = facts[inputs[0]]
        incoherent_inputs = {
            input_metric: facts[input_metric].period
            for input_metric in inputs[1:]
            if not self._same_period(facts[input_metric], anchor_fact)
        }
        if incoherent_inputs:
            result = MetricResult(
                metric=metric,
                status="unavailable",
                period=period,
                value=None,
                unit=unit,
                definition_version=definition_version,
                formula=formula,
                numerator=None,
                denominator=None,
                source_fact_ids=[fact.id for fact in facts.values()],
                calculation_trace={
                    "reason": "incoherent_periods",
                    "anchor": {"metric": inputs[0], "period": anchor_fact.period},
                    "incoherent_inputs": incoherent_inputs,
                },
                confidence=Decimal("0.00"),
                fiscal_year=anchor_fact.fiscal_year,
                fiscal_quarter=anchor_fact.fiscal_quarter,
            )
            return self._persist_if_requested(db, company, result, persist)

        numerator, denominator, trace, supplemental_facts = self._evaluate(
            db,
            company,
            metric,
            facts,
        )
        result_facts = {**facts, **supplemental_facts}
        unique_facts = self._unique_facts(result_facts)
        if denominator is None or denominator == 0 or numerator is None:
            reason = "zero_or_invalid_denominator"
        elif denominator < 0 and metric in POSITIVE_DENOMINATOR_METRICS:
            reason = "non_positive_denominator"
        else:
            reason = None
        if reason is not None:
            result = MetricResult(
                metric=metric,
                status="unavailable",
                period=period,
                value=None,
                unit=unit,
                definition_version=definition_version,
                formula=formula,
                numerator=numerator,
                denominator=denominator,
                source_fact_ids=[fact.id for fact in unique_facts],
                calculation_trace={
                    **trace,
                    "reason": reason,
                },
                confidence=Decimal("0.00"),
                fiscal_year=next(iter(facts.values())).fiscal_year if facts else None,
                fiscal_quarter=next(iter(facts.values())).fiscal_quarter if facts else None,
            )
            return self._persist_if_requested(db, company, result, persist)

        value = _quantize(numerator / denominator)
        # F153: margen > 100% con periodos coherentes = dato real atipico
        # (ganancia no operativa excepcional). Se publica etiquetado.
        if metric in MARGIN_METRICS and value > Decimal("1"):
            trace = {
                **trace,
                "atypical": (
                    "margin_over_100pct: lectura real posible solo por ganancias "
                    "no operativas excepcionales; verificar numerador/denominador"
                ),
            }
        confidence = min(
            (Decimal(fact.confidence) for fact in unique_facts),
            default=Decimal("0.70"),
        )
        if trace.get("tax_rate_source") == "statutory_fallback":
            confidence = min(confidence, Decimal("0.70"))
        if unit == "USD":
            # importe: la divisa es la de los hechos de entrada (EUR en ESEF,
            # CAD en Yahoo), no USD fijo
            units = {f.unit for f in unique_facts if f.unit}
            if len(units) > 1:
                # divisas mezcladas: N/D declarado, nunca un importe etiquetado USD
                return self._persist_if_requested(
                    db, company,
                    self._mixed_unit_result(metric, period, unit, definition_version, formula, unique_facts, sorted(units)),
                    persist,
                )
            unit = units.pop() if units else unit
        result = MetricResult(
            metric=metric,
            status="ok",
            period=period,
            value=value,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=_quantize(numerator),
            denominator=_quantize(denominator),
            source_fact_ids=[fact.id for fact in unique_facts],
            calculation_trace={
                **trace,
                "inputs": {
                    input_metric: {
                        "fact_id": fact.id,
                        "value": str(fact.value),
                        "period": fact.period,
                        "source_type": fact.source_type,
                        "metric": fact.metric,
                    }
                    for input_metric, fact in result_facts.items()
                },
            },
            confidence=confidence,
            fiscal_year=next(iter(facts.values())).fiscal_year if facts else None,
            fiscal_quarter=next(iter(facts.values())).fiscal_quarter if facts else None,
        )

        return self._persist_if_requested(db, company, result, persist)

    def latest_calculated(self, db: Session, company: Company) -> list[CalculatedMetric]:
        return list(
            db.scalars(
                select(CalculatedMetric)
                .where(CalculatedMetric.company_id == company.id)
                .order_by(CalculatedMetric.metric, desc(CalculatedMetric.updated_at))
            ).all()
        )

    def _coherent_facts(
        self,
        db: Session,
        company: Company,
        inputs: tuple[str, ...],
        strict: bool = False,
    ) -> dict[str, FinancialFact]:
        anchors = self._facts_for_metric(db, company, inputs[0])
        best_match: dict[str, FinancialFact] = {}
        for anchor in anchors:
            facts = {inputs[0]: anchor}
            for metric in inputs[1:]:
                match = self._match_fact(db, company, metric, anchor)
                if match:
                    facts[metric] = match
            if len(facts) == len(inputs):
                return facts
            if len(facts) > len(best_match):
                best_match = facts
        if strict:
            return best_match
        facts: dict[str, FinancialFact] = {}
        for metric in inputs:
            latest = self._facts_for_metric(db, company, metric)
            if latest:
                facts[metric] = latest[0]
        return facts

    def _facts_for_metric(self, db: Session, company: Company, metric: str) -> list[FinancialFact]:
        cache: dict[tuple[int, str], list[FinancialFact]] | None = db.info.get(_FACTS_CACHE_KEY)
        key = (company.id, metric)
        if cache is not None and key in cache:
            return list(cache[key])
        facts = list(
            db.scalars(
                select(FinancialFact)
                .where(FinancialFact.company_id == company.id, FinancialFact.metric == metric)
                .order_by(*_FACT_ORDER)
                .limit(_FACTS_PER_METRIC)
            ).all()
        )
        if cache is not None:
            cache[key] = facts
            return list(facts)
        return facts

    def _prefetch_facts(
        self, db: Session, company: Company, cache: dict[tuple[int, str], list[FinancialFact]]
    ) -> None:
        """Una consulta para los insumos de TODAS las metricas de la empresa.

        Antes cada insumo era su propia consulta (~19-26 por empresa; la
        comparativa de comparables lanzaba 172 para 9 empresas). Mismo tope
        y orden que ``_facts_for_metric``; un insumo sin hechos queda en
        cache como lista vacia para no volver a consultarlo.
        """
        metrics = sorted(_PREFETCH_METRICS)
        ranked = (
            select(
                FinancialFact.id,
                func.row_number()
                .over(partition_by=FinancialFact.metric, order_by=_FACT_ORDER)
                .label("rn"),
            )
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(metrics),
                *tenant_filters(db, FinancialFact),
            )
            .subquery()
        )
        grouped: dict[str, list[FinancialFact]] = {metric: [] for metric in metrics}
        rows = db.execute(
            select(FinancialFact, ranked.c.rn)
            .join(ranked, FinancialFact.id == ranked.c.id)
            .where(ranked.c.rn <= _FACTS_PER_METRIC)
        ).all()
        for fact, rn in sorted(rows, key=lambda row: (row[0].metric, row[1])):
            grouped[fact.metric].append(fact)
        for metric, facts in grouped.items():
            cache[(company.id, metric)] = facts

    def _match_fact(self, db: Session, company: Company, metric: str, anchor: FinancialFact) -> FinancialFact | None:
        candidates = self._facts_for_metric(db, company, metric)
        for candidate in candidates:
            if candidate.period == anchor.period:
                return candidate
        for candidate in candidates:
            if (
                anchor.fiscal_year is not None
                and candidate.fiscal_year == anchor.fiscal_year
                and candidate.fiscal_quarter == anchor.fiscal_quarter
            ):
                return candidate
        return None

    def _mixed_unit_result(
        self, metric, period, unit, definition_version, formula, facts, units
    ) -> MetricResult:
        return MetricResult(
            metric=metric,
            status="unavailable",
            period=period,
            value=None,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[fact.id for fact in facts],
            calculation_trace={"reason": "mixed_currency_inputs", "units": units},
            confidence=Decimal("0.00"),
            fiscal_year=None,
            fiscal_quarter=None,
        )

    def _period_for_result(self, facts: dict[str, FinancialFact]) -> str:
        if not facts:
            return "unknown"
        first = next(iter(facts.values()))
        return first.period

    def _evaluate(
        self,
        db: Session,
        company: Company,
        metric: str,
        facts: dict[str, FinancialFact],
    ) -> tuple[Decimal | None, Decimal | None, dict, dict[str, FinancialFact]]:
        value = lambda key: Decimal(facts[key].value)
        if metric == "owner_earnings":
            oe = owner_earnings(
                net_income=value("net_income"),
                depreciation_amortization=value("depreciation_amortization"),
                change_in_working_capital=value("change_in_working_capital"),
                capital_expenditure=value("capital_expenditure"),
            )
            assert oe is not None and oe.estimated_growth_capex is not None
            trace = {
                "method": "owner_earnings",
                "source": "Buffett, Berkshire Hathaway shareholder letter 1986",
                "maintenance_capex": str(_quantize(oe.maintenance_capex)),
                "maintenance_capex_rule": oe.maintenance_capex_rule,
                "estimated_growth_capex": str(_quantize(oe.estimated_growth_capex)),
                "change_in_working_capital": str(_quantize(value("change_in_working_capital"))),
                "working_capital_sign": WORKING_CAPITAL_SIGN_CONVENTION,
            }
            return oe.value, Decimal("1"), trace, {}
        if metric == "cfroi_approx":
            tax_rate, tax_trace, tax_facts = self._tax_rate_for_period(
                db,
                company,
                facts["net_income"],
                allow_fallback=True,
            )
            assert tax_rate is not None
            gross_cash_flow = (
                value("net_income")
                + value("depreciation_amortization")
                + value("interest_expense") * (Decimal("1") - tax_rate)
            )
            trace = {
                "method": "cfroi_approx",
                "approximation": (
                    "invested capital proxied by total_assets; no inflation "
                    "adjustment; not comparable to Credit Suisse CFROI"
                ),
                **tax_trace,
            }
            return gross_cash_flow, value("total_assets"), trace, tax_facts
        if metric in {"roic", "roic_adjusted"}:
            tax_rate, tax_trace, tax_facts = self._tax_rate_for_period(
                db,
                company,
                facts["operating_income"],
                allow_fallback=True,
            )
            assert tax_rate is not None
            nopat = value("operating_income") * (Decimal("1") - tax_rate)
            capital_metrics = ["total_debt", "total_equity", "cash_and_equivalents"]
            current_invested_capital = (
                value("total_debt")
                + value("total_equity")
                - value("cash_and_equivalents")
            )
            if metric == "roic_adjusted":
                capital_metrics.extend(
                    ["goodwill", "intangible_assets", "operating_lease_liabilities"]
                )
                current_invested_capital = (
                    current_invested_capital
                    - value("goodwill")
                    - value("intangible_assets")
                    + value("operating_lease_liabilities")
                )

            prior = self._prior_coherent_facts(
                db,
                company,
                facts["operating_income"],
                tuple(capital_metrics),
            )
            supplemental_facts = dict(tax_facts)
            prior_invested_capital = None
            invested_capital = current_invested_capital
            capital_basis = "current_period"
            if prior:
                prior_invested_capital = (
                    Decimal(prior["total_debt"].value)
                    + Decimal(prior["total_equity"].value)
                    - Decimal(prior["cash_and_equivalents"].value)
                )
                if metric == "roic_adjusted":
                    prior_invested_capital = (
                        prior_invested_capital
                        - Decimal(prior["goodwill"].value)
                        - Decimal(prior["intangible_assets"].value)
                        + Decimal(prior["operating_lease_liabilities"].value)
                    )
                invested_capital = (
                    current_invested_capital + prior_invested_capital
                ) / Decimal("2")
                capital_basis = "average_current_and_prior_period"
                supplemental_facts.update(
                    {f"prior_{key}": fact for key, fact in prior.items()}
                )

            trace = {
                "method": (
                    "adjusted_roic" if metric == "roic_adjusted" else "standard_roic"
                ),
                **tax_trace,
                "nopat": str(nopat),
                "invested_capital": str(invested_capital),
                "invested_capital_basis": capital_basis,
                "current_invested_capital": str(current_invested_capital),
                "prior_invested_capital": (
                    str(prior_invested_capital)
                    if prior_invested_capital is not None
                    else None
                ),
            }
            if metric == "roic_adjusted":
                trace["adjustments"] = {
                    "goodwill_removed": str(value("goodwill")),
                    "intangible_assets_removed": str(value("intangible_assets")),
                    "operating_lease_liabilities_added": str(
                        value("operating_lease_liabilities")
                    ),
                    "numerator_adjustments": (
                        "none; no amortization or lease-interest add-back is made "
                        "without separately reported inputs"
                    ),
                }
            return nopat, invested_capital, trace, supplemental_facts
        numerator_key, denominator_key = METRIC_DEFINITIONS[metric][2]
        return (
            value(numerator_key),
            value(denominator_key),
            {
                "method": "simple_ratio",
                "numerator_metric": numerator_key,
                "denominator_metric": denominator_key,
            },
            {},
        )

    def _tax_rate_for_period(
        self,
        db: Session,
        company: Company,
        anchor: FinancialFact,
        allow_fallback: bool,
        allow_latest: bool = False,
    ) -> tuple[Decimal | None, dict, dict[str, FinancialFact]]:
        direct = self._match_alias(
            db,
            company,
            ("effective_tax_rate", "tax_rate"),
            anchor,
            reported_only=True,
            allow_latest=allow_latest,
        )
        rejected_inputs: list[str] = []
        if direct:
            _, fact = direct
            rate, normalized = self._normalize_rate(fact.value, unit=fact.unit)
            if rate is not None and Decimal("0") <= rate <= Decimal("1"):
                return rate, {
                    "tax_rate": str(rate),
                    "tax_rate_source": "reported_effective_tax_rate",
                    "tax_rate_fallback": False,
                    "tax_rate_normalized_from_percent": normalized,
                    "tax_rate_input_fact_ids": [fact.id],
                }, {"effective_tax_rate": fact}
            rejected_inputs.append(f"{fact.metric}:outside_0_to_1")

        # Pares (gasto por impuestos, resultado antes de impuestos) del MISMO
        # periodo. Se recorren del ejercicio mas reciente al mas antiguo y gana
        # el primero coherente (pretax > 0 y tasa en [0, 1]); un ultimo ejercicio
        # con perdidas o con un hecho sin pareja no tapa un ejercicio anterior
        # valido. La tasa declara el periodo del que sale; nunca hay default.
        pairs: list[tuple[FinancialFact, FinancialFact]] = []
        seen_expense: set[int] = set()
        anchor_expense = self._match_alias(
            db,
            company,
            ("income_tax_expense", "tax_expense"),
            anchor,
            reported_only=True,
        )
        expense_candidates: list[FinancialFact] = []
        if anchor_expense:
            expense_candidates.append(anchor_expense[1])
        if allow_latest:
            for alias in ("income_tax_expense", "tax_expense"):
                for candidate in self._facts_for_metric(db, company, alias):
                    if candidate.is_reported:
                        expense_candidates.append(candidate)
        for expense_fact in expense_candidates:
            if expense_fact.id in seen_expense:
                continue
            seen_expense.add(expense_fact.id)
            pretax_match = self._match_alias(
                db,
                company,
                ("income_before_tax", "pretax_income", "income_before_taxes"),
                expense_fact,
                reported_only=True,
            )
            if pretax_match:
                pairs.append((expense_fact, pretax_match[1]))
        for expense_fact, pretax_fact in pairs:
            pretax = Decimal(pretax_fact.value)
            if pretax > 0:
                derived_rate = Decimal(expense_fact.value) / pretax
                if Decimal("0") <= derived_rate <= Decimal("1"):
                    return derived_rate, {
                        "tax_rate": str(derived_rate),
                        "tax_rate_source": "reported_income_statement",
                        "tax_rate_fallback": False,
                        "tax_rate_formula": "income_tax_expense / income_before_tax",
                        "tax_rate_period": expense_fact.period,
                        "tax_rate_input_fact_ids": [
                            expense_fact.id,
                            pretax_fact.id,
                        ],
                    }, {
                        "income_tax_expense": expense_fact,
                        "income_before_tax": pretax_fact,
                    }
        if pairs:
            rejected_inputs.append("income_tax_expense/income_before_tax:incoherent")
        elif expense_candidates:
            rejected_inputs.append("income_tax_expense:sin_income_before_tax_del_mismo_periodo")

        if not allow_fallback:
            return None, {
                "tax_rate": None,
                "tax_rate_source": "unavailable",
                "tax_rate_fallback": False,
                "rejected_tax_inputs": rejected_inputs,
            }, {}

        fallback = Decimal("0.21")
        return fallback, {
            "tax_rate": str(fallback),
            "tax_rate_source": "statutory_fallback",
            "tax_rate_fallback": True,
            "tax_rate_fallback_reason": (
                "no coherent reported effective tax rate or reported "
                "income-tax-expense/pre-tax-income pair"
            ),
            "rejected_tax_inputs": rejected_inputs,
            "confidence_adjustment": "capped_at_0.70_for_tax_fallback",
        }, {}

    def _prior_coherent_facts(
        self,
        db: Session,
        company: Company,
        current_anchor: FinancialFact,
        metrics: tuple[str, ...],
    ) -> dict[str, FinancialFact]:
        for prior_anchor in self._facts_for_metric(db, company, metrics[0]):
            if not self._is_prior_period(prior_anchor, current_anchor):
                continue
            facts = {metrics[0]: prior_anchor}
            for metric in metrics[1:]:
                match = self._match_fact(db, company, metric, prior_anchor)
                if match:
                    facts[metric] = match
            if len(facts) == len(metrics):
                return facts
        return {}

    def _is_prior_period(
        self,
        candidate: FinancialFact,
        current: FinancialFact,
    ) -> bool:
        if candidate.fiscal_year is not None and current.fiscal_year is not None:
            if candidate.fiscal_year >= current.fiscal_year:
                return False
            if (
                candidate.fiscal_quarter is not None
                and current.fiscal_quarter is not None
                and candidate.fiscal_quarter != current.fiscal_quarter
            ):
                return False
            return True
        return candidate.period < current.period

    def _match_alias(
        self,
        db: Session,
        company: Company,
        aliases: tuple[str, ...],
        anchor: FinancialFact,
        reported_only: bool = False,
        allow_latest: bool = False,
    ) -> tuple[str, FinancialFact] | None:
        for alias in aliases:
            for candidate in self._facts_for_metric(db, company, alias):
                if reported_only and not candidate.is_reported:
                    continue
                if self._same_period(candidate, anchor):
                    return alias, candidate
        if allow_latest:
            for alias in aliases:
                for candidate in self._facts_for_metric(db, company, alias):
                    if not reported_only or candidate.is_reported:
                        return alias, candidate
        return None

    def _same_period(self, candidate: FinancialFact, anchor: FinancialFact) -> bool:
        if candidate.period == anchor.period:
            return True
        # F153: el fallback fiscal_year/fiscal_quarter puede asociar hechos
        # con cierres distintos dentro del mismo ejercicio (una empresa que
        # cambia de cierre, o un FY etiquetado a 2025-06-30 y otro a
        # 2025-12-31). Si ambos periodos traen fin de periodo parseable, la
        # coincidencia exige mismo fin Y misma etiqueta de duracion (un FY
        # no es un Q4 aunque cierren el mismo dia).
        anchor_key = self._period_key(anchor.period)
        candidate_key = self._period_key(candidate.period)
        if anchor_key is not None and candidate_key is not None:
            return anchor_key == candidate_key
        return (
            anchor.fiscal_year is not None
            and candidate.fiscal_year == anchor.fiscal_year
            and candidate.fiscal_quarter == anchor.fiscal_quarter
        )

    @staticmethod
    def _period_key(period: str) -> tuple[str, str] | None:
        """(fin_de_periodo, etiqueta) si el periodo las trae («2026-06-30:FY»);
        None cuando la etiqueta es opaca («FY2025») y toca el fallback fiscal."""
        end, sep, tag = period.partition(":")
        if sep and tag and len(end) == 10 and end[4] == "-" and end[7] == "-":
            return (end, tag)
        return None

    def _normalize_rate(
        self,
        raw_value: Decimal,
        allow_negative: bool = False,
        unit: str | None = None,
    ) -> tuple[Decimal | None, bool]:
        # Helper único de unidades: la unidad del hecho manda; la heurística
        # «>1 => %» solo queda para hechos sin unidad útil.
        rate, method = to_fraction(Decimal(raw_value), unit)
        normalized = is_from_percent(method)
        if rate < 0 and not allow_negative:
            return None, normalized
        if rate > 1:
            return None, normalized
        return rate, normalized

    def _calculate_wacc(
        self,
        db: Session,
        company: Company,
        persist: bool,
    ) -> MetricResult:
        definition_version, formula, _, unit = METRIC_DEFINITIONS["wacc"]
        anchors = self._facts_for_metric(db, company, "risk_free_rate")
        if not anchors:
            result = MetricResult(
                metric="wacc",
                status="unavailable",
                period="unknown",
                value=None,
                unit=unit,
                definition_version=definition_version,
                formula=formula,
                numerator=None,
                denominator=None,
                source_fact_ids=[],
                calculation_trace={
                    "method": "standard_wacc",
                    "reason": "missing_or_incoherent_inputs",
                    "missing_inputs": ["risk_free_rate"],
                },
                confidence=Decimal("0.00"),
            )
            return self._persist_if_requested(db, company, result, persist)

        best_facts: dict[str, FinancialFact] = {"risk_free_rate": anchors[0]}
        best_missing: list[str] = []
        best_tax_trace: dict = {}
        best_gated: list[dict] = []
        for anchor in anchors:
            facts: dict[str, FinancialFact] = {"risk_free_rate": anchor}
            missing: list[str] = []
            gated: list[dict] = []
            for key, aliases in (
                ("beta", ("beta",)),
                ("equity_risk_premium", ("equity_risk_premium",)),
                ("total_debt", ("total_debt",)),
            ):
                matched = self._match_alias(
                    db,
                    company,
                    aliases,
                    anchor,
                    allow_latest=True,
                )
                if matched:
                    facts[key] = matched[1]
                else:
                    missing.append(key)

            # Beta presente pero no plausible: mismo estado que beta ausente.
            # Se saca de `facts` (asi no entra en source_fact_ids ni se
            # presenta como input disponible) y se declara en `missing`.
            beta_fact = facts.get("beta")
            if beta_fact is not None and not _beta_is_plausible(
                Decimal(beta_fact.value)
            ):
                del facts["beta"]
                missing.append("beta")
                gated.append(
                    _gated_input(
                        "beta",
                        "beta_outside_plausible_range",
                        "beta de mercado fuera de "
                        f"[{BETA_PLAUSIBLE_RANGE[0]}, {BETA_PLAUSIBLE_RANGE[1]}]: "
                        "el dato es basura o una escala mal parseada; no se "
                        "recorta a los extremos",
                        value=Decimal(beta_fact.value),
                    )
                )

            # Solo valor de MERCADO para el peso de equity. `total_equity` es el
            # patrimonio contable: usarlo como Ew del WACC mezcla market value
            # con book value. Con market cap 10.000M, book equity 2.000M y debt
            # 3.000M, el WACC correcto es 7,08% y con book equity salia 5,60%
            # (-21%), y como el DCF escala con 1/(WACC-g) el valor de salida se
            # desvía +48%. Si no hay market cap, el WACC no se calcula: se
            # declara unavailable con el motivo (ver mas abajo).
            equity = self._match_alias(
                db,
                company,
                ("market_cap", "market_capitalization"),
                anchor,
                allow_latest=True,
            )
            if equity:
                facts["equity_value"] = equity[1]
            else:
                missing.append("market_cap")

            tax_rate, tax_trace, tax_facts = self._tax_rate_for_period(
                db,
                company,
                anchor,
                allow_fallback=False,
                allow_latest=True,
            )
            facts.update(tax_facts)
            if tax_rate is None:
                missing.append("tax_rate")

            cost_of_debt = None
            cost_of_debt_source = None
            direct_debt_cost = self._match_alias(
                db,
                company,
                ("cost_of_debt",),
                anchor,
                allow_latest=True,
            )
            if direct_debt_cost:
                facts["cost_of_debt"] = direct_debt_cost[1]
                cost_of_debt, _ = self._normalize_rate(direct_debt_cost[1].value, unit=direct_debt_cost[1].unit)
                cost_of_debt_source = "reported_cost_of_debt"
                if cost_of_debt is None:
                    missing.append("valid_cost_of_debt")
            elif "total_debt" in facts and Decimal(facts["total_debt"].value) > 0:
                interest = self._match_alias(
                    db,
                    company,
                    ("interest_expense",),
                    facts["total_debt"],
                    allow_latest=True,
                )
                if interest:
                    facts["interest_expense"] = interest[1]
                    cost_of_debt = (
                        abs(Decimal(interest[1].value))
                        / Decimal(facts["total_debt"].value)
                    )
                    cost_of_debt_source = "interest_expense_over_debt"
                    if cost_of_debt > 1:
                        cost_of_debt = None
                        missing.append("valid_interest_expense_over_debt")
                else:
                    missing.append("cost_of_debt_or_interest_expense")
            elif "total_debt" in facts and Decimal(facts["total_debt"].value) == 0:
                # Deuda financiera reportada = 0: su peso en el WACC es 0 y el
                # coste de la deuda no entra. No se inventa un coste; se declara.
                cost_of_debt = Decimal("0")
                cost_of_debt_source = "no_reported_debt"
            else:
                missing.append("cost_of_debt_or_interest_expense")

            if not missing:
                country_risk = self._match_alias(
                    db,
                    company,
                    ("country_risk_premium",),
                    anchor,
                    allow_latest=True,
                )
                # Sin fact de CRP el WACC NO se calcula. Un 0 explicito seria
                # afirmar "esta compañía no tiene riesgo pais", y para
                # Argentina, Nigeria o Arabia son +-10pp de CRP real: con rf
                # 4,5%, beta 1,2 y ERP 5,5% el coste de equity salia 11,1%
                # donde correspondia ~21%. Como el DCF escala con 1/(WACC-g),
                # ese -10pp multiplica el valor por accion por ~2,3. La CRP es
                # input obligatorio: si no hay fact, el unico CRP 0 legitimo es
                # el declarado por la politica (wacc_policy, con fuente y
                # fecha), no el que aparece por defecto en este codigo.
                if not country_risk:
                    missing.append("country_risk_premium")
                    gated.append(
                        _gated_input(
                            "country_risk_premium",
                            "absent_never_defaulted_to_zero",
                            "sin fact de prima de riesgo pais: un 0 implicito "
                            "subestimaria el coste de equity en los +10pp que "
                            "aplica a mercados emergentes; el WACC queda "
                            "unavailable en vez de descontar con un 0 inventado",
                        )
                    )
                else:
                    facts["country_risk_premium"] = country_risk[1]
                    normalized_country_risk, _ = self._normalize_rate(
                        country_risk[1].value, unit=country_risk[1].unit
                    )
                    if normalized_country_risk is None:
                        missing.append("valid_country_risk_premium")
                        gated.append(
                            _gated_input(
                                "country_risk_premium",
                                "invalid_country_risk_premium",
                                "el fact existe pero no es una tasa valida "
                                "(negativa o >100%): se declara ausente en "
                                "vez de tomar 0",
                                value=Decimal(country_risk[1].value),
                            )
                        )

            if len(facts) >= len(best_facts):
                best_facts = facts
                best_missing = missing
                best_tax_trace = tax_trace
                best_gated = gated
            if missing:
                continue

            risk_free_rate, rf_normalized = self._normalize_rate(
                facts["risk_free_rate"].value,
                allow_negative=True,
                unit=facts["risk_free_rate"].unit,
            )
            equity_risk_premium, erp_normalized = self._normalize_rate(
                facts["equity_risk_premium"].value, unit=facts["equity_risk_premium"].unit
            )
            beta = Decimal(facts["beta"].value)
            debt = Decimal(facts["total_debt"].value)
            equity_value = Decimal(facts["equity_value"].value)
            if (
                risk_free_rate is None
                or equity_risk_premium is None
                or debt < 0
                or equity_value <= 0
                or debt + equity_value <= 0
            ):
                best_facts = facts
                best_missing = ["valid_rates_and_capital_weights"]
                best_tax_trace = tax_trace
                best_gated = gated
                continue
            if _capital_scale_conflict(facts["equity_value"], facts["total_debt"]):
                # market_cap viene de market data en unidades absolutas;
                # total_debt ESEF puede llegar escalado (scale no se conserva).
                # Sumarlos sin reconciliar daba Dw ~= 1,5e-6 en un emisor
                # apalancado: WACC 18,0% donde correspondía 12,6% (-34% de
                # valor de salida). No se adivina un factor de escala: se
                # declara inconsistente.
                best_facts = facts
                best_missing = ["capital_amounts_scale_mismatch"]
                best_tax_trace = tax_trace
                best_gated = gated
                continue

            country_risk_rate = self._normalize_rate(
                facts["country_risk_premium"].value, unit=facts["country_risk_premium"].unit
            )[0]
            assert country_risk_rate is not None
            assert tax_rate is not None
            assert cost_of_debt is not None
            cost_of_equity = (
                risk_free_rate
                + beta * equity_risk_premium
                + country_risk_rate
            )
            total_capital = equity_value + debt
            equity_weight = equity_value / total_capital
            debt_weight = debt / total_capital
            after_tax_cost_of_debt = cost_of_debt * (Decimal("1") - tax_rate)
            wacc = (
                equity_weight * cost_of_equity
                + debt_weight * after_tax_cost_of_debt
            )
            unique_facts = self._unique_facts(facts)
            as_of_date = self._date_from_period(anchor.period)
            trace = {
                "method": "standard_wacc",
                **tax_trace,
                "risk_free_rate": str(risk_free_rate),
                "beta": str(beta),
                "beta_plausible_range": [
                    str(BETA_PLAUSIBLE_RANGE[0]),
                    str(BETA_PLAUSIBLE_RANGE[1]),
                ],
                "equity_risk_premium": str(equity_risk_premium),
                "country_risk_premium": str(country_risk_rate),
                "cost_of_equity": str(cost_of_equity),
                "cost_of_debt": str(cost_of_debt),
                "cost_of_debt_source": cost_of_debt_source,
                "after_tax_cost_of_debt": str(after_tax_cost_of_debt),
                "equity_value": str(equity_value),
                "equity_value_source": facts["equity_value"].metric,
                "debt": str(debt),
                "equity_weight": str(equity_weight),
                "debt_weight": str(debt_weight),
                "currency": company.currency,
                "as_of_period": anchor.period,
                "input_period_alignment": (
                    "same_period"
                    if len({fact.period for fact in facts.values()}) == 1
                    else "mixed_latest_available"
                ),
                "rate_normalization": {
                    "risk_free_rate_from_percent": rf_normalized,
                    "equity_risk_premium_from_percent": erp_normalized,
                },
                "inputs": {
                    key: {
                        "fact_id": fact.id,
                        "metric": fact.metric,
                        "value": str(fact.value),
                        "period": fact.period,
                        "source_type": fact.source_type,
                        "unit": fact.unit,
                    }
                    for key, fact in facts.items()
                },
            }
            if as_of_date:
                trace["as_of_date"] = as_of_date
            result = MetricResult(
                metric="wacc",
                status="ok",
                period=anchor.period,
                value=_quantize(wacc),
                unit=unit,
                definition_version=definition_version,
                formula=formula,
                numerator=_quantize(wacc),
                denominator=Decimal("1.00000000"),
                source_fact_ids=[fact.id for fact in unique_facts],
                calculation_trace=trace,
                confidence=min(
                    Decimal(fact.confidence) for fact in unique_facts
                ),
                fiscal_year=anchor.fiscal_year,
                fiscal_quarter=anchor.fiscal_quarter,
            )
            return self._persist_if_requested(db, company, result, persist)

        anchor = anchors[0]
        unique_facts = self._unique_facts(best_facts)
        result = MetricResult(
            metric="wacc",
            status="unavailable",
            period=anchor.period,
            value=None,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[fact.id for fact in unique_facts],
            calculation_trace={
                "method": "standard_wacc",
                **best_tax_trace,
                "reason": "missing_or_incoherent_inputs",
                "missing_inputs": sorted(set(best_missing)),
                "gated_inputs": best_gated,
                "available_inputs": sorted(best_facts),
                "currency": company.currency,
                "as_of_period": anchor.period,
            },
            confidence=Decimal("0.00"),
            fiscal_year=anchor.fiscal_year,
            fiscal_quarter=anchor.fiscal_quarter,
        )
        return self._persist_if_requested(db, company, result, persist)

    def _calculate_cfroi(
        self,
        db: Session,
        company: Company,
        persist: bool,
    ) -> MetricResult:
        definition_version, formula, _, unit = METRIC_DEFINITIONS["cfroi"]
        available: dict[str, FinancialFact] = {}
        for input_metric in CFROI_REQUIRED_INPUTS:
            facts = self._facts_for_metric(db, company, input_metric)
            if facts:
                available[input_metric] = facts[0]
        first = next(iter(available.values()), None)
        result = MetricResult(
            metric="cfroi",
            status="unavailable",
            period=first.period if first else "unknown",
            value=None,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[
                fact.id for fact in self._unique_facts(available)
            ],
            calculation_trace={
                "method": "cfroi",
                "reason": "specialized_methodology_inputs_required",
                "methodology": (
                    "CFROI requires inflation-adjusted gross cash flow, "
                    "inflation-adjusted gross investment, asset-life normalization, "
                    "and terminal non-depreciating assets; accounting proxies are "
                    "not substituted."
                ),
                "required_inputs": list(CFROI_REQUIRED_INPUTS),
                "missing_inputs": [
                    key for key in CFROI_REQUIRED_INPUTS if key not in available
                ],
                "policy": "persist_unavailable_never_fabricate",
            },
            confidence=Decimal("0.00"),
            fiscal_year=first.fiscal_year if first else None,
            fiscal_quarter=first.fiscal_quarter if first else None,
        )
        return self._persist_if_requested(db, company, result, persist)

    def _date_from_period(self, period: str) -> str | None:
        match = re.match(r"^\d{4}-\d{2}-\d{2}", period)
        return match.group(0) if match else None

    def _unique_facts(
        self,
        facts: dict[str, FinancialFact],
    ) -> list[FinancialFact]:
        unique: dict[int, FinancialFact] = {}
        for fact in facts.values():
            unique[fact.id] = fact
        return list(unique.values())

    def _annual_facts_by_year(
        self,
        db: Session,
        company: Company,
        metric: str,
    ) -> dict[int, FinancialFact]:
        """Latest annual fact per fiscal year (fiscal_quarter == 'FY')."""
        by_year: dict[int, FinancialFact] = {}
        for fact in self._facts_for_metric(db, company, metric):
            if fact.fiscal_year is None or fact.fiscal_quarter != "FY":
                continue
            if fact.fiscal_year not in by_year:
                by_year[fact.fiscal_year] = fact
        return by_year

    def _window_unavailable(
        self,
        db: Session,
        company: Company,
        metric: str,
        persist: bool,
        years_with_data: list[int],
        facts_used: list[FinancialFact],
    ) -> MetricResult:
        definition_version, formula, _, unit = METRIC_DEFINITIONS[metric]
        result = MetricResult(
            metric=metric,
            status="unavailable",
            period="unknown" if not years_with_data else f"FY{min(years_with_data)}-FY{max(years_with_data)}",
            value=None,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[fact.id for fact in facts_used],
            calculation_trace={
                "reason": "insufficient_history",
                "coverage": f"{len(years_with_data)}/{WINDOW_MAX_YEARS}",
                "years_with_data": sorted(years_with_data),
                "minimum_years": WINDOW_MIN_YEARS,
            },
            confidence=Decimal("0.00"),
            fiscal_year=max(years_with_data) if years_with_data else None,
        )
        return self._persist_if_requested(db, company, result, persist)

    def _calculate_windowed_ratio(
        self,
        db: Session,
        company: Company,
        metric: str,
        persist: bool,
    ) -> MetricResult:
        definition_version, formula, _, unit = METRIC_DEFINITIONS[metric]
        numerator_metric, denominator_metric = WINDOWED_RATIO_METRICS[metric]
        numerators = self._annual_facts_by_year(db, company, numerator_metric)
        denominators = self._annual_facts_by_year(db, company, denominator_metric)
        usable_years = sorted(
            (
                year
                for year in set(numerators) & set(denominators)
                # Años con denominador <= 0 (patrimonio/activo/ingresos
                # negativos) no son interpretables: fuera de la ventana.
                if Decimal(denominators[year].value) > 0
            ),
            reverse=True,
        )[:WINDOW_MAX_YEARS]
        facts_used = [f for year in usable_years for f in (numerators[year], denominators[year])]
        if len(usable_years) < WINDOW_MIN_YEARS:
            return self._window_unavailable(db, company, metric, persist, usable_years, facts_used)

        ratios = {
            year: Decimal(numerators[year].value) / Decimal(denominators[year].value)
            for year in usable_years
        }
        value = _quantize(sum(ratios.values()) / Decimal(len(ratios)))
        confidence = min(
            (Decimal(fact.confidence) for fact in facts_used),
            default=Decimal("0.70"),
        )
        result = MetricResult(
            metric=metric,
            status="ok",
            period=f"FY{min(usable_years)}-FY{max(usable_years)}",
            value=value,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[fact.id for fact in facts_used],
            calculation_trace={
                "aggregation": "mean_of_annual_ratios",
                "coverage": f"{len(usable_years)}/{WINDOW_MAX_YEARS}",
                "years": sorted(usable_years),
                "ratios": {str(year): str(_quantize(ratio)) for year, ratio in ratios.items()},
                "inputs": {
                    str(year): {
                        "numerator_fact_id": numerators[year].id,
                        "numerator": str(numerators[year].value),
                        "denominator_fact_id": denominators[year].id,
                        "denominator": str(denominators[year].value),
                    }
                    for year in usable_years
                },
            },
            confidence=confidence,
            fiscal_year=max(usable_years),
        )
        return self._persist_if_requested(db, company, result, persist)

    def _calculate_windowed_composed(
        self,
        db: Session,
        company: Company,
        metric: str,
        persist: bool,
    ) -> MetricResult:
        definition_version, formula, inputs, unit = METRIC_DEFINITIONS[metric]
        facts_by_year = {
            input_metric: self._annual_facts_by_year(db, company, input_metric)
            for input_metric in inputs
        }
        common_years = set.intersection(
            *(set(facts) for facts in facts_by_year.values())
        )
        usable_years = sorted(common_years, reverse=True)[:WINDOW_MAX_YEARS]
        facts_used = [
            fact
            for year in usable_years
            for fact in (facts_by_year[input_metric][year] for input_metric in inputs)
        ]

        yearly: dict[int, Decimal] = {}
        skipped_zero_da: list[int] = []
        for year in usable_years:
            da = Decimal(facts_by_year["depreciation_amortization"][year].value)
            capex = abs(Decimal(facts_by_year["capital_expenditure"][year].value))
            if metric == "owner_earnings_5y":
                oe = owner_earnings(
                    net_income=Decimal(facts_by_year["net_income"][year].value),
                    depreciation_amortization=da,
                    change_in_working_capital=Decimal(
                        facts_by_year["change_in_working_capital"][year].value
                    ),
                    capital_expenditure=capex,
                )
                assert oe is not None
                yearly[year] = oe.value
            else:  # capex_to_da_5y
                if da == 0:
                    skipped_zero_da.append(year)
                    continue
                yearly[year] = capex / da

        if len(yearly) < WINDOW_MIN_YEARS:
            return self._window_unavailable(
                db, company, metric, persist, sorted(yearly), facts_used
            )

        value = _quantize(sum(yearly.values()) / Decimal(len(yearly)))
        confidence = min(
            (Decimal(fact.confidence) for fact in facts_used),
            default=Decimal("0.70"),
        )
        years = sorted(yearly)
        if unit == "USD":
            # importe: la divisa es la de los hechos de entrada, no una fija
            units = {f.unit for f in facts_used if f.unit}
            if len(units) > 1:
                return self._persist_if_requested(
                    db, company,
                    self._mixed_unit_result(
                        metric, f"FY{min(years)}-FY{max(years)}", unit,
                        definition_version, formula, facts_used, sorted(units),
                    ),
                    persist,
                )
            unit = units.pop() if units else unit
        result = MetricResult(
            metric=metric,
            status="ok",
            period=f"FY{min(years)}-FY{max(years)}",
            value=value,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=[fact.id for fact in facts_used],
            calculation_trace={
                "aggregation": "mean_of_annual_values",
                "coverage": f"{len(yearly)}/{WINDOW_MAX_YEARS}",
                "years": years,
                "values": {str(year): str(_quantize(v)) for year, v in yearly.items()},
                "skipped_zero_depreciation_years": skipped_zero_da,
                "inputs": {
                    str(year): {
                        f"{input_metric}_fact_id": facts_by_year[input_metric][year].id
                        for input_metric in inputs
                    }
                    for year in years
                },
            },
            confidence=confidence,
            fiscal_year=max(years),
        )
        return self._persist_if_requested(db, company, result, persist)

    def _latest_stored(self, db: Session, company: Company, metric: str) -> CalculatedMetric | None:
        return db.scalar(
            select(CalculatedMetric)
            .where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == metric,
            )
            .order_by(desc(CalculatedMetric.updated_at))
            .limit(1)
        )

    def _ratio_check(
        self,
        result: MetricResult,
        threshold: str,
        label: str,
    ) -> dict:
        threshold_value = Decimal(threshold)
        if result.status != "ok" or result.value is None:
            return {
                "check": label,
                "metric": result.metric,
                "threshold": threshold,
                "value": None,
                "passed": None,
                "reason": result.calculation_trace.get("reason", result.status),
            }
        return {
            "check": label,
            "metric": result.metric,
            "threshold": threshold,
            "value": str(result.value),
            "passed": result.value > threshold_value,
        }

    def _wacc_esef_equity_only(
        self, db: Session, company: Company
    ) -> tuple[Decimal, dict] | None:
        """WACC = coste de equity puro para emisores ESEF sin deuda desagregable.

        Aproximacion declarada (25/9, documentada en /metodologia):
        como el coste de la deuda tras impuestos es inferior al coste del
        equity, el WACC todo-equity es una COTA SUPERIOR del WACC real -
        umbral conservador AL ALZA para los checks roic/cfroi > wacc.
        Solo se usa dentro de quality_moat_score_v2: el metric wacc
        almacenado no se toca.
        """
        rf_facts = self._facts_for_metric(db, company, "risk_free_rate")
        beta_facts = self._facts_for_metric(db, company, "beta")
        erp_facts = self._facts_for_metric(db, company, "equity_risk_premium")
        if not rf_facts or not beta_facts or not erp_facts:
            return None
        risk_free, _ = self._normalize_rate(rf_facts[0].value, allow_negative=True, unit=rf_facts[0].unit)
        erp, _ = self._normalize_rate(erp_facts[0].value, unit=erp_facts[0].unit)
        if risk_free is None or erp is None:
            return None
        beta = Decimal(beta_facts[0].value)
        if not _beta_is_plausible(beta):
            # Mismo gate que el WACC estándar: una beta no plausible haría que
            # el umbral del check roic>wacc se cumpliera con un coste de equity
            # sin respaldo, en la dirección que ENGANA (roic "pasa"). Sin beta
            # creíble el check queda no evaluable.
            return None
        country_rate = Decimal("0")
        crp_facts = self._facts_for_metric(db, company, "country_risk_premium")
        if crp_facts:
            normalized_crp, _ = self._normalize_rate(crp_facts[0].value, unit=crp_facts[0].unit)
            if normalized_crp is not None:
                country_rate = normalized_crp
        cost_of_equity = risk_free + beta * erp + country_rate
        fact_ids = [rf_facts[0].id, beta_facts[0].id, erp_facts[0].id]
        if crp_facts:
            fact_ids.append(crp_facts[0].id)
        trace = {
            "method": "wacc_esef_equity_only",
            "approximation": (
                "sin deuda ESEF desagregable (IFRS la reparte y la metodologia "
                "prohibe sumarla): WACC = coste de equity puro, cota superior "
                "del WACC real - umbral conservador al alza; aproximacion "
                "declarada 25/9, documentada en /metodologia"
            ),
            "cost_of_equity": str(cost_of_equity),
            "risk_free_rate": str(risk_free),
            "beta": str(beta),
            "equity_risk_premium": str(erp),
            "country_risk_premium": str(country_rate),
            "input_fact_ids": fact_ids,
        }
        return _quantize(cost_of_equity), trace

    def _roic_approx_esef(
        self, db: Session, company: Company
    ) -> tuple[Decimal, dict] | None:
        """ROIC aproximado para emisores ESEF sin desglose de deuda.

        Hueco IFRS honesto: borrowings current/noncurrent/lease van repartidos
        y la metodologia prohibe sumarlos (ver ESEF_METRIC_MAP). Aproximacion
        declarada (25/9, documentada en /metodologia): capital invertido
        ~ total_assets - cash_and_equivalents. Como activos - caja >= deuda +
        equity - caja, el denominador se sobreestima y el ROIC queda
        conservador A LA BAJA: nunca infla el check roic_gt_wacc.
        """
        assets = self._annual_facts_by_year(db, company, "total_assets")
        cash = self._annual_facts_by_year(db, company, "cash_and_equivalents")
        operating = self._annual_facts_by_year(db, company, "operating_income")
        common = sorted(set(assets) & set(cash) & set(operating), reverse=True)
        if not common:
            return None
        year = common[0]
        tax_rate, tax_trace, _ = self._tax_rate_for_period(
            db, company, operating[year], allow_fallback=True
        )
        if tax_rate is None:
            return None
        nopat = Decimal(operating[year].value) * (Decimal("1") - tax_rate)
        invested = Decimal(assets[year].value) - Decimal(cash[year].value)
        prior_invested = None
        basis = "current_period"
        prior_years = [y for y in common if y < year]
        if prior_years:
            py = prior_years[0]
            prior_invested = Decimal(assets[py].value) - Decimal(cash[py].value)
            invested = (invested + prior_invested) / Decimal("2")
            basis = "average_current_and_prior_period"
        if invested <= 0:
            return None
        trace = {
            "method": "roic_approx_esef_assets_menos_caja",
            "approximation": (
                "capital invertido aproximado como total_assets - cash_and_equivalents "
                "(>= deuda + equity - caja: ROIC conservador a la baja); "
                "aproximacion declarada 25/9, documentada en /metodologia"
            ),
            "fiscal_year": year,
            **tax_trace,
            "nopat": str(nopat),
            "invested_capital": str(invested),
            "invested_capital_basis": basis,
            "prior_invested_capital": (
                str(prior_invested) if prior_invested is not None else None
            ),
        }
        return _quantize(nopat / invested), trace

    def _base_quality_checks(
        self,
        db: Session,
        company: Company,
        persist: bool,
    ) -> tuple[list[dict], list[MetricResult]]:
        fcf_result = self._calculate_windowed_ratio(db, company, "fcf_margin_5y", persist)
        net_margin_result = self._calculate_windowed_ratio(db, company, "net_margin_5y", persist)
        roe_result = self._calculate_windowed_ratio(db, company, "roe_5y", persist)
        roa_result = self._calculate_windowed_ratio(db, company, "roa_5y", persist)

        checks = [
            self._ratio_check(fcf_result, "0.05", "fcf_margin_5y_gt_5pct"),
            self._ratio_check(net_margin_result, "0.15", "net_margin_5y_gt_15pct"),
            self._ratio_check(roe_result, "0.15", "roe_5y_gt_15pct"),
            self._ratio_check(roa_result, "0.07", "roa_5y_gt_7pct"),
        ]

        roic_result = self.calculate(db, company, "roic", persist=persist)
        wacc_result = self.calculate(db, company, "wacc", persist=persist)
        if roic_result.status == "ok" and wacc_result.status == "ok":
            checks.append(
                {
                    "check": "roic_gt_wacc",
                    "metric": "roic",
                    "threshold": str(wacc_result.value),
                    "value": str(roic_result.value),
                    "passed": roic_result.value > wacc_result.value,
                }
            )
        else:
            checks.append(
                {
                    "check": "roic_gt_wacc",
                    "metric": "roic",
                    "threshold": str(wacc_result.value) if wacc_result.value is not None else None,
                    "value": str(roic_result.value) if roic_result.value is not None else None,
                    "passed": None,
                    "reason": "roic_or_wacc_unavailable",
                }
            )

        component_results = [
            fcf_result,
            net_margin_result,
            roe_result,
            roa_result,
            roic_result,
            wacc_result,
        ]
        return checks, component_results

    def _calculate_fcf_before_growth_capex(
        self, db: Session, company: Company, persist: bool
    ) -> MetricResult:
        """FCF antes de gasto de crecimiento = FCF + capex de crecimiento estimado.

        Estados: ok con inputs completos; partial sin D&A, siempre sin valor;
        insufficient_data sin FCF/capex o con inputs incompatibles/invalidos.
        """
        metric = "fcf_before_growth_capex"
        definition_version, formula, inputs, unit = METRIC_DEFINITIONS[metric]
        facts = self._coherent_facts(db, company, inputs)
        period = self._period_for_result(facts)
        missing = [input_metric for input_metric in inputs if input_metric not in facts]
        first = next(iter(facts.values()), None)

        def build(
            *,
            status: str,
            value: Decimal | None,
            numerator: Decimal | None,
            trace: dict,
            confidence: Decimal,
            fact_list: list[FinancialFact],
            result_unit: str,
        ) -> MetricResult:
            return MetricResult(
                metric=metric,
                status=status,
                period=period,
                value=value,
                unit=result_unit,
                definition_version=definition_version,
                formula=formula,
                numerator=numerator,
                denominator=Decimal("1") if numerator is not None else None,
                source_fact_ids=[fact.id for fact in fact_list],
                calculation_trace=trace,
                confidence=confidence,
                fiscal_year=first.fiscal_year if first else None,
                fiscal_quarter=first.fiscal_quarter if first else None,
            )

        if "free_cash_flow" in missing or "capital_expenditure" in missing:
            return self._persist_if_requested(
                db,
                company,
                build(
                    status="insufficient_data",
                    value=None,
                    numerator=None,
                    trace={
                        "reason": "missing_inputs",
                        "missing_inputs": missing,
                        "available_inputs": sorted(facts),
                    },
                    confidence=Decimal("0.00"),
                    fact_list=list(facts.values()),
                    result_unit=unit,
                ),
                persist,
            )

        anchor = facts["free_cash_flow"]
        incoherent = {
            input_metric: facts[input_metric].period
            for input_metric in inputs[1:]
            if input_metric in facts and not self._same_period(facts[input_metric], anchor)
        }
        if incoherent:
            return self._persist_if_requested(
                db,
                company,
                build(
                    status="insufficient_data",
                    value=None,
                    numerator=None,
                    trace={
                        "reason": "incoherent_periods",
                        "anchor": {"metric": "free_cash_flow", "period": anchor.period},
                        "incoherent_inputs": incoherent,
                    },
                    confidence=Decimal("0.00"),
                    fact_list=list(facts.values()),
                    result_unit=unit,
                ),
                persist,
            )

        unique_facts = self._unique_facts(facts)
        units = {fact.unit for fact in unique_facts if fact.unit}
        if len(units) > 1:
            return self._persist_if_requested(
                db,
                company,
                build(status="insufficient_data", value=None, numerator=None,
                      trace={"reason": "mixed_currency_inputs", "units": sorted(units)},
                      confidence=Decimal("0"), fact_list=unique_facts, result_unit=unit),
                persist,
            )
        result_unit = units.pop() if units else unit
        confidence = min(
            (Decimal(fact.confidence) for fact in unique_facts), default=Decimal("0.70")
        )
        maintenance_rule = (
            "min(abs(capital_expenditure), depreciation_amortization); "
            "maintenance capex is not separately reported - declared "
            "conservative estimate"
        )
        fcf = Decimal(facts["free_cash_flow"].value)
        capex = Decimal(facts["capital_expenditure"].value)
        depreciation = (
            Decimal(facts["depreciation_amortization"].value)
            if "depreciation_amortization" not in missing else None
        )
        invalid = not fcf.is_finite() or not capex.is_finite()
        if depreciation is not None:
            invalid = invalid or not depreciation.is_finite()
            if depreciation.is_finite():
                invalid = invalid or depreciation < 0
        if invalid:
            return self._persist_if_requested(db, company, build(
                status="insufficient_data", value=None, numerator=None,
                trace={"reason": "invalid_inputs"}, confidence=Decimal("0"),
                fact_list=unique_facts, result_unit=result_unit,
            ), persist)
        capex_abs = abs(capex)

        if "depreciation_amortization" in missing:
            # No publicar el FCF reportado bajo el nombre de otra metrica.
            return self._persist_if_requested(
                db,
                company,
                build(
                    status="partial",
                    value=None,
                    numerator=None,
                    trace={
                        "method": "fcf_before_growth_capex",
                        "reason": "growth_capex_not_separable",
                        "missing_inputs": ["depreciation_amortization"],
                        "maintenance_capex_rule": maintenance_rule,
                        "value_basis": (
                            "no_value_without_split: "
                            "reported FCF is not this metric"
                        ),
                    },
                    confidence=confidence,
                    fact_list=unique_facts,
                    result_unit=result_unit,
                ),
                persist,
            )

        assert depreciation is not None
        maintenance_capex = min(capex_abs, depreciation)
        growth_capex = capex_abs - maintenance_capex
        value = _quantize(fcf + growth_capex)
        return self._persist_if_requested(
            db,
            company,
            build(
                status="ok",
                value=value,
                numerator=value,
                trace={
                    "method": "fcf_before_growth_capex",
                    "maintenance_capex": str(_quantize(maintenance_capex)),
                    "maintenance_capex_rule": maintenance_rule,
                    "estimated_growth_capex": str(_quantize(growth_capex)),
                    "estimate": (
                        "the maintenance/growth capex split is a declared "
                        "estimate, not separately reported by the company"
                    ),
                    "inputs": {
                        input_metric: {
                            "fact_id": fact.id,
                            "value": str(fact.value),
                            "period": fact.period,
                            "source_type": fact.source_type,
                            "metric": fact.metric,
                        }
                        for input_metric, fact in facts.items()
                    },
                },
                confidence=confidence,
                fact_list=unique_facts,
                result_unit=result_unit,
            ),
            persist,
        )

    def _quality_score_result(
        self,
        db: Session,
        company: Company,
        persist: bool,
        metric: str,
        framework_label: str,
        checks: list[dict],
        component_results: list[MetricResult],
    ) -> MetricResult:
        definition_version, formula, _, unit = METRIC_DEFINITIONS[metric]
        evaluable = [check for check in checks if check["passed"] is not None]
        score = sum(1 for check in checks if check["passed"] is True)
        if not evaluable:
            status = "unavailable"
            value = None
        elif len(evaluable) == len(checks):
            status = "ok"
            value = Decimal(score)
        else:
            status = "partial"
            value = Decimal(score)
        periods = [r.period for r in component_results if r.period and r.period != "unknown"]
        result = MetricResult(
            metric=metric,
            status=status,
            period=periods[0] if periods else "unknown",
            value=value,
            unit=unit,
            definition_version=definition_version,
            formula=formula,
            numerator=None,
            denominator=None,
            source_fact_ids=sorted(
                {fact_id for r in component_results for fact_id in r.source_fact_ids}
            ),
            calculation_trace={
                "framework": framework_label,
                "checks": checks,
                "checks_evaluable": len(evaluable),
                "checks_total": len(checks),
                "score": score,
            },
            confidence=min(
                (r.confidence for r in component_results if r.status == "ok"),
                default=Decimal("0.00"),
            ),
            fiscal_year=next(
                (r.fiscal_year for r in component_results if r.fiscal_year is not None),
                None,
            ),
        )
        return self._persist_if_requested(db, company, result, persist)

    def _calculate_quality_score(
        self,
        db: Session,
        company: Company,
        persist: bool,
    ) -> MetricResult:
        checks, component_results = self._base_quality_checks(db, company, persist)
        return self._quality_score_result(
            db,
            company,
            persist,
            "quality_moat_score",
            "MARCO_V1 (apuntes manuscritos, sept 2026)",
            checks,
            component_results,
        )

    def _calculate_quality_score_v2(
        self,
        db: Session,
        company: Company,
        persist: bool,
    ) -> MetricResult:
        checks, component_results = self._base_quality_checks(db, company, persist)

        # Aproximaciones declaradas ESEF (25/9, documentadas en
        # /metodologia): IFRS reparte la deuda (borrowings current/noncurrent/
        # lease) y la metodologia prohibe sumarla, asi que el ROIC estandar y
        # el WACC estandar no son calculables para emisores ESEF. Ambas
        # aproximaciones son conservadoras CONTRA el check: WACC = coste de
        # equity puro (cota superior del umbral) y capital invertido =
        # activos - caja (cota superior del denominador, ROIC a la baja).
        esef_wacc = None
        if company.currency == "EUR":
            esef_wacc = self._wacc_esef_equity_only(db, company)
            if esef_wacc is not None:
                wacc_value, wacc_trace = esef_wacc
                roic_approx = self._roic_approx_esef(db, company)
                for i, check in enumerate(checks):
                    if check["check"] != "roic_gt_wacc" or check["passed"] is not None:
                        continue
                    if roic_approx is None:
                        continue
                    roic_value, roic_trace = roic_approx
                    checks[i] = {
                        "check": "roic_gt_wacc",
                        "metric": "roic",
                        "threshold": str(wacc_value),
                        "value": str(roic_value),
                        "passed": roic_value > wacc_value,
                        "approximation": {
                            "roic": roic_trace,
                            "wacc": wacc_trace,
                        },
                    }

        # CFROI (aproximacion declarada) por encima del coste de capital:
        # creacion de valor en terminos de caja, no solo contables.
        cfroi_result = self.calculate(db, company, "cfroi_approx", persist=persist)
        wacc_result = component_results[-1]
        if cfroi_result.status == "ok" and wacc_result.status == "ok":
            checks.append(
                {
                    "check": "cfroi_approx_gt_wacc",
                    "metric": "cfroi_approx",
                    "threshold": str(wacc_result.value),
                    "value": str(cfroi_result.value),
                    "passed": cfroi_result.value > wacc_result.value,
                }
            )
        elif esef_wacc is not None and cfroi_result.status == "ok":
            wacc_value, wacc_trace = esef_wacc
            checks.append(
                {
                    "check": "cfroi_approx_gt_wacc",
                    "metric": "cfroi_approx",
                    "threshold": str(wacc_value),
                    "value": str(cfroi_result.value),
                    "passed": cfroi_result.value > wacc_value,
                    "approximation": {"wacc": wacc_trace},
                }
            )
        else:
            checks.append(
                {
                    "check": "cfroi_approx_gt_wacc",
                    "metric": "cfroi_approx",
                    "threshold": str(wacc_result.value) if wacc_result.value is not None else None,
                    "value": str(cfroi_result.value) if cfroi_result.value is not None else None,
                    "passed": None,
                    "reason": "cfroi_approx_or_wacc_unavailable",
                }
            )
        component_results.append(cfroi_result)

        # Owner earnings (Buffett): la media de hasta 5 anos debe ser
        # positiva; un negocio que no genera caja para el dueno tras
        # mantenimiento no tiene foso economico.
        oe_result = self._calculate_windowed_composed(db, company, "owner_earnings_5y", persist)
        checks.append(self._ratio_check(oe_result, str(V2_OWNER_EARNINGS_MIN), "owner_earnings_5y_positive"))
        component_results.append(oe_result)

        # Disciplina de capital: |capex|/D&A medio <= 1.5 (1.0 = solo
        # mantenimiento). Mas arriba, el negocio exige reinversion pesada
        # continua - el foso queda en duda. Umbral <=, no <.
        capex_da_result = self._calculate_windowed_composed(db, company, "capex_to_da_5y", persist)
        if capex_da_result.status == "ok" and capex_da_result.value is not None:
            checks.append(
                {
                    "check": "capex_to_da_5y_le_150pct",
                    "metric": "capex_to_da_5y",
                    "threshold": str(V2_CAPEX_TO_DA_MAX),
                    "value": str(capex_da_result.value),
                    "passed": capex_da_result.value <= V2_CAPEX_TO_DA_MAX,
                }
            )
        else:
            checks.append(
                {
                    "check": "capex_to_da_5y_le_150pct",
                    "metric": "capex_to_da_5y",
                    "threshold": str(V2_CAPEX_TO_DA_MAX),
                    "value": None,
                    "passed": None,
                    "reason": capex_da_result.calculation_trace.get("reason", capex_da_result.status),
                }
            )
        component_results.append(capex_da_result)

        profile, profile_reason = financial_quality_profile(company)
        if profile in NONCOMPARABLE_PROFILES:
            # Do not turn losses/investment in an early-stage company, bank or
            # cyclical business into a spurious zero-out-of-eight "moat".
            # The computed components remain accessible as raw diagnostics.
            checks = [
                {**check, "passed": None, "reason": "not_applicable_to_profile"}
                for check in checks
            ]
        # Assemble the complete trace before the single upsert. JSON columns do
        # not track mutations of a dictionary already assigned to an ORM row.
        result = self._quality_score_result(
            db,
            company,
            False,
            "quality_moat_score_v2",
            "MARCO_V2 (V1 + cfroi/owner earnings/capex; umbrales fijados 2026-09-25)",
            checks,
            component_results,
        )
        result.calculation_trace.update({
            "profile": profile,
            "profile_label": PROFILE_LABELS[profile],
            "profile_reason": profile_reason,
            "score_comparable": profile not in NONCOMPARABLE_PROFILES,
            "interpretation": (
                "Diagnóstico de calidad financiera; no demuestra un foso competitivo."
                if profile not in NONCOMPARABLE_PROFILES else
                "Estos umbrales generales no son pertinentes para este perfil. "
                "El foso requiere evidencia cualitativa verificable."
            ),
        })
        return self._persist_if_requested(db, company, result, persist)

    def _persist_if_requested(
        self,
        db: Session,
        company: Company,
        result: MetricResult,
        persist: bool,
    ) -> MetricResult:
        if persist:
            stored = self._upsert(db, company, result)
            result.id = stored.id
        return result

    def _upsert(self, db: Session, company: Company, result: MetricResult) -> CalculatedMetric:
        if result.status in {"ok", "partial"}:
            # Higiene: una fila con valor real sustituye a las filas
            # unavailable de ciclos anteriores con otro periodo (incluida la
            # "unknown" de los recalculos sin historia); sin esto la tabla
            # crece x2 en cada ciclo (la UI lee la mas reciente por
            # updated_at, pero la basura se acumula).
            db.execute(
                delete(CalculatedMetric).where(
                    CalculatedMetric.company_id == company.id,
                    CalculatedMetric.metric == result.metric,
                    CalculatedMetric.period != result.period,
                    CalculatedMetric.status.in_(["unavailable", "insufficient_data"]),
                    CalculatedMetric.definition_version == result.definition_version,
                )
            )
        metric = db.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == result.metric,
                CalculatedMetric.period == result.period,
                CalculatedMetric.definition_version == result.definition_version,
            )
        )
        if metric is None:
            metric = CalculatedMetric(
                company_id=company.id,
                metric=result.metric,
                period=result.period,
                definition_version=result.definition_version,
                formula=result.formula,
            )
            db.add(metric)

        metric.value = result.value
        metric.unit = result.unit
        metric.fiscal_year = result.fiscal_year
        metric.fiscal_quarter = result.fiscal_quarter
        metric.status = result.status
        metric.formula = result.formula
        metric.numerator = result.numerator
        metric.denominator = result.denominator
        metric.source_fact_ids = result.source_fact_ids
        metric.calculation_trace = result.calculation_trace
        metric.confidence = result.confidence
        db.flush()
        return metric
