"""Cuánto valdría el DCF estándar si los pagos en acciones (SBC) se restaran del FCF.

El DCF estándar parte de FCF = flujo operativo − capex, y en US GAAP ese flujo
operativo ya ha vuelto a sumar la compensación en acciones (SBC). Damodaran la
trata como un gasto. Medido antes de decidir (backtest gerarai-dcavalor2,
7-nov-2026; réplica point-in-time del DCF estándar, 377 empresas del S&P 500,
2015-2026): restarla baja el valor (mediana −9 %; −67 % con SBC > 10 % de las
ventas) pero ORDENA PEOR las empresas (IC 12 m −0,014 → −0,032 en 2015-20 y
0,038 → 0,030 en 2021-26; 24 m 0,021 → −0,007 y 0,056 → 0,036) y sube el error
mediano 3-4 puntos. Por eso el número publicado no cambia: esto es una línea
informativa para las empresas en las que el SBC pesa (≥ 10 % del FCF).

El valor alternativo se recalcula con las mismas trayectorias de crecimiento,
WACC, terminal y puente de cada escenario, restando a cada año del margen FCF el
SBC del último ejercicio en porcentaje de sus ventas, y se pondera con las mismas
probabilidades. Se publica como proporción sobre el valor ya publicado, así que
la conversión de divisa del valor no le afecta.
"""

from __future__ import annotations

from typing import Any

from app.valuation.normalized_fcf import run_path_dcf

SBC_NOTE_ENGINE = "standard_dcf"
#: A partir de qué peso del SBC sobre el FCF se muestra la línea.
SBC_SHARE_OF_FCF_THRESHOLD = 0.10
SBC_HISTORY_METRICS = (
    "revenue",
    "operating_cash_flow",
    "capital_expenditure",
    "stock_based_compensation",
)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _fact_value(row: dict, metric: str) -> float | None:
    fact = row.get(metric)
    return _num(getattr(fact, "value", fact))


def _es(value: float, digits: int = 2) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def latest_sbc_year(history: dict[int, dict]) -> dict | None:
    """Último ejercicio con ventas, flujo operativo, capex y SBC."""
    for year in sorted(history, reverse=True):
        row = history[year]
        revenue = _fact_value(row, "revenue")
        ocf = _fact_value(row, "operating_cash_flow")
        capex = _fact_value(row, "capital_expenditure")
        sbc = _fact_value(row, "stock_based_compensation")
        if None in (revenue, ocf, capex, sbc) or not revenue or revenue <= 0:
            continue
        return {"fiscal_year": year, "revenue": revenue, "fcf": ocf - abs(capex), "sbc": abs(sbc)}
    return None


def _scenario_value_after_sbc(trace: dict, sbc_margin: float) -> float | None:
    inputs = (trace or {}).get("inputs") or {}
    growth_path = inputs.get("growth_path")
    margin_path = inputs.get("margin_path")
    if not growth_path or not margin_path or len(growth_path) != len(margin_path):
        return None
    try:
        out = run_path_dcf(
            revenue=float(inputs["revenue"]),
            growth_path=[float(g) for g in growth_path],
            margin_path=[float(m) - sbc_margin for m in margin_path],
            wacc=float(inputs["wacc"]),
            terminal_growth=float(inputs["terminal_growth"]),
            net_debt=float(inputs.get("net_debt") or 0.0),
            shares_outstanding=float(inputs["shares_outstanding"]),
            minority_interest=float(inputs.get("minority_interest") or 0.0),
            preferred_stock=float(inputs.get("preferred_stock") or 0.0),
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return out.value_per_share


def sbc_adjustment(result: dict[str, Any], history: dict[int, dict]) -> dict[str, Any] | None:
    """Línea «si se restan los pagos en acciones…», o None si no aplica.

    Solo para un valor del DCF estándar (``trace.engine``) con valor esperado > 0,
    FCF > 0 y SBC ≥ 10 % del FCF en el último ejercicio con los cuatro hechos.
    """
    trace = result.get("trace") or {}
    if not isinstance(trace, dict) or trace.get("engine") != SBC_NOTE_ENGINE:
        return None
    published = _num(result.get("expected_value"))
    if published is None or published <= 0:
        return None
    year = latest_sbc_year(history or {})
    if year is None or year["fcf"] <= 0 or year["sbc"] <= 0:
        return None
    share = year["sbc"] / year["fcf"]
    if share < SBC_SHARE_OF_FCF_THRESHOLD:
        return None
    sbc_margin = year["sbc"] / year["revenue"]
    scenarios = trace.get("scenarios") or {}
    before = after = weight = 0.0
    for data in scenarios.values():
        probability = _num(((data or {}).get("definition") or {}).get("probability"))
        old = _num((data or {}).get("value_per_share"))
        if old is None:  # escenario N/D: el esperado pondera su valor bruto
            old = _num((data or {}).get("value_per_share_raw"))
        new = _scenario_value_after_sbc((data or {}).get("trace") or {}, sbc_margin)
        if probability is None or probability <= 0 or old is None or new is None:
            return None
        before += probability * old
        after += probability * new
        weight += probability
    if weight <= 0 or before <= 0:
        return None
    before, after = before / weight, after / weight
    currency = result.get("value_currency")
    suffix = f" {currency}" if isinstance(currency, str) and currency else ""
    pct = round(share * 100)
    fy = year["fiscal_year"]
    base = {
        "fiscal_year": fy,
        "sbc_share_of_fcf": round(share, 4),
        "sbc_to_revenue": round(sbc_margin, 4),
        "currency": currency if suffix else None,
    }
    tail_es = " GerarAI no lo resta porque, en el backtest, restarlo ordenó peor las empresas."
    tail_en = " GerarAI does not deduct it: in the backtest, deducting it ranked companies worse."
    if after <= 0:
        return {
            **base,
            "value_after_sbc": None,
            "message_es": (
                f"Si se restan los pagos en acciones ({pct} % del FCF de {fy}), "
                "el valor saldría negativo." + tail_es
            ),
            "message_en": (
                f"If stock-based pay ({pct}% of {fy} FCF) is deducted, the value turns negative." + tail_en
            ),
        }
    value = published * after / before
    return {
        **base,
        "value_after_sbc": value,
        "message_es": (
            f"Si se restan los pagos en acciones ({pct} % del FCF de {fy}), el valor sería "
            f"~{_es(value)}{suffix}." + tail_es
        ),
        "message_en": (
            f"If stock-based pay ({pct}% of {fy} FCF) is deducted, the value would be "
            f"~{value:,.2f}{suffix}." + tail_en
        ),
    }
