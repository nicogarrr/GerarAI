"""DCF multietapa y FCF con capex normalizado (empresas grandes con datos).

Por qué existe: el DCF estándar proyecta 5 años con el margen FCF del último
ejercicio y crecimiento constante, y salta directamente al crecimiento
terminal. Dos casos reales lo rompían en prod (3-nov-2026, datos SEC):

* AMZN: capex 131.819 M frente a amortización 65.756 M en el FY2025 (ciclo de
  inversión en IA). El margen FCF reportado cayó al 1,07 % (5,6 % y 5,2 % los
  dos años anteriores) y el valor esperado salió en 26,29 US$ con el precio en
  ~251 US$.
* PLTR: crecimiento de ingresos del 56 % en el FY2025; pasar de golpe del
  crecimiento del año 5 al terminal infravalora a una empresa que todavía
  crece a doble dígito alto.

Método (Damodaran, *Investment Valuation*, cap. 12 «Estimating growth» y
cap. 13 sobre capex de mantenimiento vs. de crecimiento; McKinsey,
*Valuation*, cap. 10 sobre márgenes de ciclo medio):

1. Capex normalizado: capex de mantenimiento ≈ amortización (D&A); lo que
   exceda la amortización es capex de crecimiento. El margen FCF de ciclo
   medio es la media, en los últimos 5–7 ejercicios, de
   ``(flujo operativo − min(capex, D&A)) / ingresos``. El margen de la
   proyección parte del margen reportado y converge linealmente a ese margen
   de ciclo medio en 5 años (la intensidad de capex se desvanece).
2. Crecimiento multietapa: si la empresa crece ≥ 10 %, los años 1–5 crecen al
   CAGR histórico de ingresos a 3 años (o al último crecimiento si no hay
   historia) y los años 6–10 bajan linealmente hasta el crecimiento terminal.

Todo sale de hechos con id; nada se inventa. El resultado se etiqueta
«estimado» con el método en la traza.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.valuation.dcf_fcff import DCFResult, WaccNotAboveTerminalGrowthError

HIGH_GROWTH_THRESHOLD = 0.10
STAGE1_YEARS = 5
FADE_YEARS = 5
CAPEX_FADE_YEARS = 5
#: El capex tiene que superar la amortización en al menos un 20 % para hablar
#: de capex de crecimiento material (por debajo es ruido contable).
GROWTH_CAPEX_TRIGGER = 1.20
#: El margen de ciclo medio tiene que superar al reportado en ≥ 1 pp: si el
#: capex no deprime el margen, normalizar no cambia nada y no se etiqueta.
MIN_MARGIN_UPLIFT = 0.01
MIDCYCLE_MAX_YEARS = 7
MIDCYCLE_MIN_YEARS = 5
MIDCYCLE_SHORT_MIN_YEARS = 3
# Tope del objetivo normalizado: nunca por encima del mejor margen FCF REAL
# (flujo operativo − capex total) de los últimos N ejercicios. Owner
# 4-nov-2026; backtest 2 point-in-time (work/gerarai-backtest2, prueba t3):
# error a 12 m 48 % → 41 % en 2021–26 y casi igual en 2015–20 (META 42,5 % →
# 33,1 %). Con menos ejercicios se usan los que haya y la traza lo dice.
CAPEX_NORM_MAX_REAL_MARGIN_YEARS = 5
GROWTH_CEILING = 0.45
GROWTH_FLOOR = -0.15
MARGIN_CEILING = 0.50

CAPEX_LABEL = "estimado, capex normalizado"
MULTISTAGE_LABEL = "estimado, DCF multietapa"

HISTORY_METRICS = (
    "revenue",
    "operating_cash_flow",
    "capital_expenditure",
    "depreciation_amortization",
)


def _num_es(value: float, digits: int = 1) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct_es(ratio: float, digits: int = 1) -> str:
    return f"{_num_es(ratio * 100, digits)} %"


def _millions_es(value: float) -> str:
    return f"{_num_es(value / 1e6, 0)} M"


def fy_history(db, company_id: int, as_of, metrics=HISTORY_METRICS) -> dict[int, dict]:
    """Un hecho por ejercicio fiscal y métrica, con la política del snapshot.

    Misma elegibilidad, cuarentena y corte point-in-time que
    ``financial_snapshot`` (``_facts_for_metric`` + ``_available_at``): un
    replay histórico no ve ejercicios publicados después del corte.
    Devuelve ``{año: {métrica: hecho}}``.
    """
    from app.valuation.financial_snapshot import _available_at, _facts_for_metric

    out: dict[int, dict] = {}
    for metric in metrics:
        facts = _facts_for_metric(db, company_id, metric)
        facts, _, _ = _available_at(facts, as_of)
        seen: set[int] = set()
        for fact in facts:
            if fact.fiscal_quarter != "FY" or fact.fiscal_year is None:
                continue
            if fact.fiscal_year in seen:
                continue
            seen.add(fact.fiscal_year)
            out.setdefault(int(fact.fiscal_year), {})[metric] = fact
    return out


def revenue_cagr(history: dict[int, dict], years: int = 3) -> dict | None:
    """CAGR de ingresos a ``years`` años con los FY disponibles."""
    revenues = {
        year: float(row["revenue"].value)
        for year, row in history.items()
        if "revenue" in row and float(row["revenue"].value) > 0
    }
    if not revenues:
        return None
    latest = max(revenues)
    start = latest - years
    if start not in revenues:
        return None
    # Un cambio de moneda de presentación no es crecimiento del negocio.
    # Sin unidades comparables no hay CAGR demostrado ni conversión implícita.
    start_unit = history[start]["revenue"].unit
    latest_unit = history[latest]["revenue"].unit
    if not start_unit or start_unit != latest_unit:
        return None
    cagr = (revenues[latest] / revenues[start]) ** (1 / years) - 1
    return {
        "years": years,
        "from_year": start,
        "to_year": latest,
        "value": cagr,
        "fact_ids": [
            history[y]["revenue"].id for y in (start, latest) if history[y]["revenue"].id is not None
        ],
    }


def capex_normalization(history: dict[int, dict], reported_margin: float | None) -> dict:
    """Margen FCF de ciclo medio con capex de mantenimiento ≈ amortización.

    Devuelve siempre un dict con ``applied`` y, si no aplica, ``reason``.
    """
    rows = []
    for year in sorted(history, reverse=True):
        row = history[year]
        if not all(metric in row for metric in HISTORY_METRICS):
            continue
        units = {(row[m].unit or "") for m in HISTORY_METRICS}
        if len(units) != 1:
            continue
        revenue = float(row["revenue"].value)
        if revenue <= 0:
            continue
        ocf = float(row["operating_cash_flow"].value)
        capex = abs(float(row["capital_expenditure"].value))
        da = float(row["depreciation_amortization"].value)
        if da <= 0:
            continue
        maintenance = min(capex, da)
        rows.append(
            {
                "fiscal_year": year,
                "revenue": revenue,
                "operating_cash_flow": ocf,
                "capex": capex,
                "depreciation_amortization": da,
                "maintenance_capex": maintenance,
                "growth_capex": max(capex - da, 0.0),
                "reported_fcf_margin": (ocf - capex) / revenue,
                "normalized_fcf_margin": (ocf - maintenance) / revenue,
                "fact_ids": [row[m].id for m in HISTORY_METRICS if row[m].id is not None],
            }
        )
        if len(rows) >= MIDCYCLE_MAX_YEARS:
            break
    if not rows:
        return {"applied": False, "reason": "sin historial de flujo operativo, capex y amortización"}
    latest = rows[0]
    if latest["capex"] <= latest["depreciation_amortization"] * GROWTH_CAPEX_TRIGGER:
        return {
            "applied": False,
            "reason": "el capex del último ejercicio no supera la amortización en más de un 20 %",
            "latest": latest,
        }
    if len(rows) < MIDCYCLE_SHORT_MIN_YEARS:
        return {
            "applied": False,
            "reason": f"historial de {len(rows)} ejercicios: hacen falta al menos {MIDCYCLE_SHORT_MIN_YEARS}",
            "latest": latest,
        }
    target = sum(item["normalized_fcf_margin"] for item in rows) / len(rows)
    reported_avg = sum(item["reported_fcf_margin"] for item in rows) / len(rows)
    initial = reported_margin if reported_margin is not None else latest["reported_fcf_margin"]
    # Tope: el margen de llegada no puede superar el mejor margen FCF real
    # (con el capex total) de los últimos CAPEX_NORM_MAX_REAL_MARGIN_YEARS
    # ejercicios: un margen que la empresa nunca ha tenido no es «ciclo medio».
    window = rows[:CAPEX_NORM_MAX_REAL_MARGIN_YEARS]
    best = max(window, key=lambda item: item["reported_fcf_margin"])
    capped_from_real = target if target > best["reported_fcf_margin"] else None
    real_cap = {
        "applied": capped_from_real is not None,
        "value": best["reported_fcf_margin"],
        "fiscal_year": best["fiscal_year"],
        "years": [item["fiscal_year"] for item in window],
        "years_wanted": CAPEX_NORM_MAX_REAL_MARGIN_YEARS,
        "short_history": len(window) < CAPEX_NORM_MAX_REAL_MARGIN_YEARS,
        "uncapped_target": target,
    }
    if capped_from_real is not None:
        target = best["reported_fcf_margin"]
    if target <= 0:
        return {
            "applied": False,
            "reason": "el margen de ciclo medio con capex de mantenimiento no es positivo",
            "latest": latest,
            "midcycle_margin": target,
            "max_real_margin_cap": real_cap,
        }
    if target < initial + MIN_MARGIN_UPLIFT:
        return {
            "applied": False,
            "reason": (
                "el capex no deprime el margen: el de ciclo medio"
                + (" (acotado al mejor margen real)" if capped_from_real is not None else "")
                + " no supera al reportado en 1 pp"
            ),
            "latest": latest,
            "midcycle_margin": target,
            "max_real_margin_cap": real_cap,
        }
    clamped_from = None
    if target > MARGIN_CEILING:
        clamped_from, target = target, MARGIN_CEILING
    years = [item["fiscal_year"] for item in rows]
    short = len(rows) < MIDCYCLE_MIN_YEARS
    note = (
        f"Capex normalizado: en el FY{latest['fiscal_year']} el capex fue "
        f"{_millions_es(latest['capex'])} frente a {_millions_es(latest['depreciation_amortization'])} "
        f"de amortización; se toma la amortización como capex de mantenimiento y el resto "
        f"({_millions_es(latest['growth_capex'])}) como capex de crecimiento. El margen FCF parte del "
        f"{_pct_es(initial)} reportado y converge en {CAPEX_FADE_YEARS} años al {_pct_es(target)} de ciclo "
        f"medio (media FY{min(years)}–FY{max(years)}, {len(rows)} ejercicios"
        + (", historial corto" if short else "")
        + f"; con el capex total la media habría sido {_pct_es(reported_avg)})."
        + (
            f" Objetivo acotado al mejor margen FCF real de los últimos {len(window)} ejercicios "
            f"({_pct_es(best['reported_fcf_margin'])} en el FY{best['fiscal_year']}"
            + (", historial corto" if real_cap["short_history"] else "")
            + f"); sin el tope habría sido {_pct_es(capped_from_real)}."
            if capped_from_real is not None
            else ""
        )
    )
    return {
        "applied": True,
        "label": CAPEX_LABEL,
        "method": "capex_mantenimiento_igual_amortizacion_margen_ciclo_medio",
        "initial_margin": initial,
        "target_margin": target,
        "target_margin_clamped_from": clamped_from,
        "target_margin_capped_from": capped_from_real,
        "max_real_margin_cap": real_cap,
        "fade_years": CAPEX_FADE_YEARS,
        "midcycle_years": years,
        "midcycle_short_history": short,
        "reported_fcf_margin_avg": reported_avg,
        "latest": latest,
        "history": rows,
        "fact_ids": sorted({i for item in rows for i in item["fact_ids"]}),
        "note_es": note,
    }


@dataclass(frozen=True)
class ProjectionPlan:
    """Forma de la proyección: trayectorias de crecimiento y margen.

    ``growth_fade``: años 6–10 bajando del crecimiento de la etapa 1 al
    terminal. ``margin_start``: margen del año 0 desde el que converge el de
    la proyección (None = margen constante). Los escenarios desplazan toda la
    trayectoria con el mismo delta que el modelo mecánico aplica al base.
    """

    growth_fade: bool = False
    margin_start: float | None = None
    margin_fade_years: int = CAPEX_FADE_YEARS
    labels: tuple[str, ...] = field(default_factory=tuple)

    @property
    def active(self) -> bool:
        return self.growth_fade or self.margin_start is not None

    @property
    def years(self) -> int:
        return STAGE1_YEARS + (FADE_YEARS if self.growth_fade else 0)

    def growth_path(self, stage1_growth: float, terminal_growth: float) -> list[float]:
        path = [stage1_growth] * STAGE1_YEARS
        if self.growth_fade:
            step = (stage1_growth - terminal_growth) / FADE_YEARS
            path += [stage1_growth - step * k for k in range(1, FADE_YEARS + 1)]
        return path

    def margin_path(self, target_margin: float, base_target: float) -> list[float]:
        """Trayectoria de margen; ``target_margin`` ya incluye el delta del escenario."""
        if self.margin_start is None:
            return [target_margin] * self.years
        start = self.margin_start + (target_margin - base_target)
        step = (target_margin - start) / self.margin_fade_years
        return [
            start + step * min(year, self.margin_fade_years) for year in range(1, self.years + 1)
        ]


def run_path_dcf(
    *,
    revenue: float,
    growth_path: list[float],
    margin_path: list[float],
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: float,
    minority_interest: float = 0.0,
    preferred_stock: float = 0.0,
) -> DCFResult:
    """FCFF DCF con crecimiento y margen por año (misma matemática que run_dcf)."""
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")
    if wacc <= terminal_growth:
        raise WaccNotAboveTerminalGrowthError()
    if not growth_path or len(growth_path) != len(margin_path):
        raise ValueError("growth and margin paths must have the same positive length")
    if 1 + wacc <= 0:
        raise ValueError("wacc must be greater than -1")
    forecast = []
    present_value = 0.0
    current = revenue
    for year, (growth, margin) in enumerate(zip(growth_path, margin_path), start=1):
        current *= 1 + growth
        fcf = current * margin
        discount_factor = (1 + wacc) ** year
        pv_fcf = fcf / discount_factor
        present_value += pv_fcf
        forecast.append(
            {
                "year": year,
                "revenue_growth": growth,
                "revenue": current,
                "fcf_margin": margin,
                "fcf": fcf,
                "discount_factor": discount_factor,
                "pv_fcf": pv_fcf,
            }
        )
    years = len(forecast)
    terminal_fcf = forecast[-1]["fcf"] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal_value = terminal_value / ((1 + wacc) ** years)
    enterprise_value = present_value + pv_terminal_value
    equity_value = enterprise_value - net_debt - minority_interest - preferred_stock
    value_per_share = equity_value / shares_outstanding
    terminal_share = pv_terminal_value / enterprise_value if enterprise_value > 0 else None
    inputs = {
        "revenue": revenue,
        "revenue_growth": growth_path[0],
        "growth_path": list(growth_path),
        "fcf_margin": margin_path[-1],
        "margin_path": list(margin_path),
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "net_debt": net_debt,
        "shares_outstanding": shares_outstanding,
        "years": years,
        "minority_interest": minority_interest,
        "preferred_stock": preferred_stock,
    }
    return DCFResult(
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        forecast=forecast,
        trace={
            "method": "fcff_dcf_multistage",
            "inputs": inputs,
            "terminal_fcf": terminal_fcf,
            "terminal_value": terminal_value,
            "pv_terminal_value": pv_terminal_value,
            "pv_explicit_fcf": present_value,
            "wacc_minus_growth": wacc - terminal_growth,
            "pv_terminal_share_of_ev": terminal_share,
            "equity_bridge": {
                "enterprise_value": enterprise_value,
                "net_debt": net_debt,
                "minority_interest": minority_interest,
                "preferred_stock": preferred_stock,
                "equity_value": equity_value,
            },
        },
    )


def run_planned(
    plan: ProjectionPlan,
    *,
    revenue: float,
    growth: float,
    margin: float,
    base_margin: float,
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: float,
    minority_interest: float = 0.0,
    preferred_stock: float = 0.0,
) -> DCFResult:
    return run_path_dcf(
        revenue=revenue,
        growth_path=plan.growth_path(growth, terminal_growth),
        margin_path=plan.margin_path(margin, base_margin),
        wacc=wacc,
        terminal_growth=terminal_growth,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        minority_interest=minority_interest,
        preferred_stock=preferred_stock,
    )


def _bisect(fn, low: float, high: float, target: float, iterations: int = 60) -> float | None:
    f_low, f_high = fn(low), fn(high)
    if not (min(f_low, f_high) <= target <= max(f_low, f_high)):
        return None
    increasing = f_high >= f_low
    for _ in range(iterations):
        mid = (low + high) / 2
        value = fn(mid)
        if (value < target) == increasing:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def planned_reverse_dcf(
    plan: ProjectionPlan,
    *,
    market_price: float,
    revenue: float,
    growth: float,
    margin: float,
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: float,
    minority_interest: float = 0.0,
    preferred_stock: float = 0.0,
    historical_cagr: dict | None = None,
    low_growth: float = -0.25,
    high_growth: float = 0.75,
) -> dict:
    """DCF inverso sobre la misma trayectoria que el modelo, con explicación.

    Resuelve (1) el crecimiento de la etapa 1 que justifica el precio con la
    trayectoria de margen del modelo y (2) el margen FCF de llegada que lo
    justifica con el crecimiento del modelo. Siempre devuelve una frase en
    español que dice qué descuenta el precio, también cuando no hay solución.
    """
    common = dict(
        revenue=revenue,
        wacc=wacc,
        terminal_growth=terminal_growth,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        minority_interest=minority_interest,
        preferred_stock=preferred_stock,
    )

    def value_at_growth(g: float) -> float:
        return run_planned(plan, growth=g, margin=margin, base_margin=margin, **common).value_per_share

    def value_at_margin(m: float) -> float:
        return run_planned(plan, growth=growth, margin=m, base_margin=margin, **common).value_per_share

    try:
        required_growth = _bisect(value_at_growth, low_growth, high_growth, market_price)
        bound_values = [value_at_growth(low_growth), value_at_growth(high_growth)]
        required_margin = _bisect(value_at_margin, -0.5, 1.0, market_price)
    except (ValueError, ZeroDivisionError, OverflowError):
        return {
            "required_revenue_growth": None,
            "market_price": market_price,
            "solved_value_per_share": None,
            "out_of_bounds": True,
            "status": "not_applicable",
            "reason": "the projection cannot be solved with these inputs",
            "trace": {"method": "planned_reverse_dcf"},
        }
    fade = (
        f" y después baja en {FADE_YEARS} años hasta el {_pct_es(terminal_growth)} terminal"
        if plan.growth_fade
        else f" y después el {_pct_es(terminal_growth)} terminal"
    )
    hist = (
        f" El histórico es {_pct_es(historical_cagr['value'])} anual (CAGR FY{historical_cagr['from_year']}–"
        f"FY{historical_cagr['to_year']})."
        if historical_cagr
        else ""
    )
    price = _num_es(market_price, 2)
    if required_growth is not None:
        explanation = (
            f"El precio de {price} descuenta un crecimiento de ingresos del {_pct_es(required_growth)} anual "
            f"durante {STAGE1_YEARS} años{fade}, con margen FCF de llegada del {_pct_es(margin)} y WACC "
            f"del {_pct_es(wacc)}. El modelo usa {_pct_es(growth)}.{hist}"
        )
    else:
        explanation = (
            f"Con margen FCF del {_pct_es(margin)} y WACC del {_pct_es(wacc)}, ni un crecimiento del "
            f"{_pct_es(high_growth, 0)} anual durante {STAGE1_YEARS} años justifica el precio de {price}."
        )
    if required_margin is not None:
        explanation += (
            f" Con el crecimiento del modelo ({_pct_es(growth)}), el precio exige un margen FCF de "
            f"llegada del {_pct_es(required_margin)} (el modelo usa {_pct_es(margin)})."
        )
    elif required_growth is None:
        explanation += " Ni siquiera un margen FCF del 100 % con el crecimiento del modelo lo justifica."
    status = "ok" if required_growth is not None else "out_of_bounds"
    return {
        "required_revenue_growth": required_growth,
        "required_fcf_margin": required_margin,
        "market_price": market_price,
        "solved_value_per_share": market_price if required_growth is not None else bound_values[1],
        "out_of_bounds": required_growth is None,
        "status": status,
        "reason": None
        if required_growth is not None
        else (
            f"market_price {market_price} is outside the valueable range {bound_values} for growth in "
            f"[{low_growth}, {high_growth}] on the model's projection path"
        ),
        "explanation_es": explanation,
        "trace": {
            "method": "planned_reverse_dcf",
            "growth_bounds": [low_growth, high_growth],
            "bound_values": bound_values,
            "projection_years": plan.years,
            "growth_fade": plan.growth_fade,
            "margin_converges_from": plan.margin_start,
            "historical_cagr": historical_cagr,
        },
    }


def planned_sensitivity(
    plan: ProjectionPlan,
    *,
    revenue: float,
    margin: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: float,
    growth_values: list[float],
    wacc_values: list[float],
    minority_interest: float = 0.0,
    preferred_stock: float = 0.0,
) -> dict:
    """Grid crecimiento × WACC con la misma forma que ``sensitivity_grid``."""
    rows = []
    for growth in growth_values:
        row = {"revenue_growth": growth, "values": []}
        for wacc in wacc_values:
            try:
                value = run_planned(
                    plan,
                    revenue=revenue,
                    growth=growth,
                    margin=margin,
                    base_margin=margin,
                    wacc=wacc,
                    terminal_growth=terminal_growth,
                    net_debt=net_debt,
                    shares_outstanding=shares_outstanding,
                    minority_interest=minority_interest,
                    preferred_stock=preferred_stock,
                ).value_per_share
                row["values"].append({"wacc": wacc, "value_per_share": value})
            except ValueError:
                row["values"].append(
                    {"wacc": wacc, "value_per_share": None, "error": "invalid_cell_inputs"}
                )
        rows.append(row)
    return {"rows": rows, "trace": {"method": "dcf_sensitivity_grid_multistage", "years": plan.years}}


PLAUSIBILITY_BAND = (0.2, 5.0)


def plausibility_warning(value: float | None, price: float | None) -> dict | None:
    """Aviso (nunca borrado) cuando el valor sale fuera de 0,2x–5x el precio."""
    if value is None or price is None or price <= 0 or value <= 0:
        return None
    ratio = value / price
    low, high = PLAUSIBILITY_BAND
    if low <= ratio <= high:
        return None
    side = "por debajo" if ratio < low else "por encima"
    return {
        "code": "fair_value_far_from_price",
        "ratio_to_price": ratio,
        "band": [low, high],
        "message_es": (
            f"El valor del DCF es {_num_es(ratio, 2)} veces el precio, "
            f"{side} de la banda {_num_es(low, 1)}x–{_num_es(high, 0)}x: se muestra igualmente, contrastado con "
            "múltiplos y con lo que descuenta el precio (DCF inverso)."
        ),
    }


def build_projection(
    db, company_id: int, as_of, *, margin: float | None, growth: float, growth_sourced: bool = True
) -> dict:
    """Decide la forma de la proyección para el DCF estándar.

    Devuelve ``{"plan", "margin", "growth", "info"}``: ``margin`` es el margen
    de llegada (el de ciclo medio si se normaliza el capex, si no el de
    entrada), ``growth`` el de la etapa 1. Sin historial o con cualquier
    error devuelve el plan inactivo y los valores de entrada sin tocar.
    """
    inactive = {"plan": ProjectionPlan(), "margin": margin, "growth": growth, "info": None}
    try:
        history = fy_history(db, company_id, as_of)
    except Exception:  # noqa: BLE001 - sin historial, comportamiento anterior
        return inactive
    capex = capex_normalization(history, margin)
    cagr = revenue_cagr(history, 3)
    labels: list[str] = []
    margin_start = None
    out_margin = margin
    if capex.get("applied"):
        margin_start = capex["initial_margin"]
        out_margin = capex["target_margin"]
        labels.append(CAPEX_LABEL)
    stage1 = growth
    growth_basis = "latest_revenue_growth"
    # Un crecimiento por defecto de la etiqueta no es evidencia de alto
    # crecimiento: el multietapa exige crecimiento de hechos o CAGR histórico.
    candidates = ([growth] if growth_sourced else []) + ([cagr["value"]] if cagr else [])
    high_growth = bool(candidates) and max(candidates) >= HIGH_GROWTH_THRESHOLD
    if high_growth:
        if cagr is not None:
            stage1 = max(min(cagr["value"], GROWTH_CEILING), GROWTH_FLOOR)
            growth_basis = "revenue_cagr_3y"
        labels.append(MULTISTAGE_LABEL)
    plan = ProjectionPlan(
        growth_fade=high_growth,
        margin_start=margin_start,
        labels=tuple(labels),
    )
    if not plan.active:
        return {
            **inactive,
            "info": {"capex_normalization": capex, "revenue_cagr_3y": cagr},
        }
    notes = []
    if capex.get("applied"):
        notes.append(capex["note_es"])
    if high_growth:
        source = (
            f"CAGR de ingresos FY{cagr['from_year']}–FY{cagr['to_year']}"
            if growth_basis == "revenue_cagr_3y" and cagr
            else "último crecimiento de ingresos"
        )
        notes.append(
            f"DCF multietapa: años 1–{STAGE1_YEARS} al {_pct_es(stage1)} ({source}); años "
            f"{STAGE1_YEARS + 1}–{STAGE1_YEARS + FADE_YEARS} bajando linealmente hasta el crecimiento terminal."
        )
    return {
        "plan": plan,
        "margin": out_margin,
        "growth": stage1,
        "info": {
            "labels": list(labels),
            "label": " · ".join(labels),
            "years": plan.years,
            "growth_fade": plan.growth_fade,
            "stage1_growth": stage1,
            "stage1_growth_basis": growth_basis,
            "latest_revenue_growth": growth,
            "revenue_cagr_3y": cagr,
            "capex_normalization": capex,
            "notes_es": notes,
        },
    }
