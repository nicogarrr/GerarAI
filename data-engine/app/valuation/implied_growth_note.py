"""Crecimiento que descuenta el precio frente al histórico (solo informativo).

Una línea junto al DCF estándar: el crecimiento anual de ingresos que hace falta
para justificar el precio (DCF inverso, mismo camino que el modelo) frente al
CAGR de ingresos de los últimos 3 ejercicios presentados. No cambia ningún valor
ni ninguna señal.

Medido (torneo de fórmulas gerarai-dcavalor5, 8-nov-2026; 377 empresas del
S&P 500, 2015–2026): «histórico − descontado» ordena algo mejor que el DCF en
2015–20 (IC 12 m +0,025 frente a −0,006) y empata en 2021–26 (+0,042 frente a
+0,040). No pasó la regla para ser señal; se muestra como dato.
"""

from __future__ import annotations

from typing import Any

IMPLIED_GROWTH_ENGINE = "standard_dcf"
#: Años de la etapa 1 en los dos DCF inversos (plano y por etapas).
STAGE1_YEARS = 5


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pct_es(ratio: float) -> str:
    return f"{ratio * 100:.1f}".replace(".", ",") + " %"


def implied_growth_vs_history(result: dict[str, Any]) -> dict[str, Any] | None:
    """La línea, o None si falta el DCF inverso resuelto o el CAGR histórico."""
    trace = result.get("trace") or {}
    if not isinstance(trace, dict) or trace.get("engine") != IMPLIED_GROWTH_ENGINE:
        return None
    reverse = result.get("reverse_dcf") or {}
    if not isinstance(reverse, dict) or reverse.get("out_of_bounds"):
        return None
    implied = _num(reverse.get("required_revenue_growth"))
    semantics = trace.get("growth_semantics") or {}
    cagr = semantics.get("historical_revenue_cagr") if isinstance(semantics, dict) else None
    historical = _num(cagr.get("value")) if isinstance(cagr, dict) else None
    if implied is None or historical is None:
        return None
    from_year, to_year = cagr.get("from_year"), cagr.get("to_year")
    span = f" (FY{from_year}–FY{to_year})" if from_year and to_year else ""
    span_en = f" (FY{from_year}–FY{to_year})" if from_year and to_year else ""
    gap = implied - historical
    return {
        "method": IMPLIED_GROWTH_ENGINE,
        "implied_revenue_growth": implied,
        "historical_revenue_cagr": historical,
        "historical_from_year": from_year,
        "historical_to_year": to_year,
        "gap": gap,
        "years": STAGE1_YEARS,
        "message_es": (
            f"Crecimiento que descuenta el precio: {_pct_es(implied)} anual de ingresos durante "
            f"{STAGE1_YEARS} años; en los últimos 3 ejercicios ha crecido un {_pct_es(historical)} anual"
            f"{span}. Dato informativo: no cambia la señal."
        ),
        "message_en": (
            f"Growth priced in: {implied * 100:.1f}% a year in revenue for {STAGE1_YEARS} years; over the "
            f"last 3 fiscal years it grew {historical * 100:.1f}% a year{span_en}. For information only: "
            "it does not change the signal."
        ),
    }
