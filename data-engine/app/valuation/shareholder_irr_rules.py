"""Regla PRE-REGISTRADA que construye los tres escenarios del motor de TIR (8-nov-2026).

Fijada antes de mirar el backtest y de comparar con ninguna tesis o precio objetivo. Cada palanca sale de
la historia de la propia empresa (hechos anuales citados), de las tasas base (crecimiento futuro observado
en empresas con un pasado parecido) y del múltiplo mediano de sus comparables, calculado por el código.
La guía de la propia empresa, si está guardada, ancla el crecimiento del primer tramo. Nada sale del modelo.

Reglas (``RULES_VERSION``):
* Crecimiento orgánico años 1–5: base = ½ histórico orgánico + ½ mediana de la tasa base de su tramo
  (regresión a la media); con guía, base = media de eso y la guía. Bajista = min(p25 del tramo, base − 2 pp);
  alcista = max(p75 del tramo, base + 2 pp). Años 6–10: mitad de camino hacia el 4 % nominal.
* Histórico orgánico = TCAC de ingresos de los últimos (hasta) 3 ejercicios menos el crecimiento comprado
  (gasto en adquisiciones / múltiplo de partida / margen / ingresos).
* Margen en el año 5: base = mediana de los 3 últimos; bajista = mínimo; alcista = máximo.
* Conversión de caja (flujo libre / EBITDA, o / beneficio): base = mediana de los 3 últimos; bajista = mínimo;
  alcista = máximo; acotada a [0, 1,2] ([0,3, 1,5] en PER).
* M&A: gasto medio en adquisiciones / ingresos de los 3 últimos (tope 15 %); bajista la mitad.
* Reparto: dividendo y recompras = su peso medio en el flujo libre tras M&A de los 3 últimos (suma ≤ 100 %);
  igual en los tres escenarios (es una política, no una previsión).
* Dilución por remuneración en acciones = gasto SBC anual / capitalización.
* Múltiplo de salida: con ≥ 3 comparables calculados, base = media entre el propio y la mediana de los
  comparables; bajista = 0,9 × el menor de los dos; alcista = el mayor. Sin comparables: base = el propio
  (sin cambio de múltiplo), bajista 0,8×, alcista 1,2×. Acotado a [4, 25] (EV/EBITDA) o [6, 35] (PER).
* Base ``pb`` (valor contable/NAV: aseguradoras, bancos, holdings): «ingresos» = valor contable atribuible,
  «margen» = ROE; crecimiento = ROE × (1 − reparto) con el reparto mediano (dividendos + recompras sobre el
  beneficio) de los tres últimos ejercicios; múltiplo P/VC acotado a [0,5; 5].
* Probabilidades 25 / 50 / 25 (convención fija; el redactor puede elegir otra de ``PROBABILITY_SETS`` con
  su razón, y la TIR ponderada se recalcula).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from app.valuation.shareholder_irr import Drivers, StartingPoint

RULES_VERSION = "shareholder-irr-rules-v2"
LONG_RUN_GROWTH = 0.04
SCENARIOS = ("bear", "base", "bull")
SCENARIO_LABELS = {"bear": "Bajista", "base": "Base", "bull": "Alcista"}
PROBABILITY_SETS: dict[str, dict[str, float]] = {
    "simetrico": {"bear": 0.25, "base": 0.50, "bull": 0.25},
    "uniforme": {"bear": 1 / 3, "base": 1 / 3, "bull": 1 / 3},
    "sesgo_bajista": {"bear": 0.40, "base": 0.45, "bull": 0.15},
    "sesgo_alcista": {"bear": 0.15, "base": 0.45, "bull": 0.40},
}
DEFAULT_PROBABILITIES = "simetrico"
MULTIPLE_BOUNDS = {"ev_ebitda": (4.0, 25.0), "pe": (6.0, 35.0), "pb": (0.5, 5.0)}
MIN_PEERS = 3

#: Tasas base: TCAC de ingresos de los 5 años SIGUIENTES (p25, p50, p75) según la TCAC de los 3 años
#: anteriores. Calculadas por ``scripts/irr_base_rates.py`` sobre los 10-K (SEC companyfacts) de una
#: muestra fija de empresas del S&P 500 con inicios 2010–2014 (los finales acaban en 2019 como tarde, así
#: que el backtest con inicio 2019 no las ve). Recuento ``n`` por tramo.
BASE_RATE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("decrece", -1.0, 0.0),
    ("0-5 %", 0.0, 0.05),
    ("5-10 %", 0.05, 0.10),
    ("10-20 %", 0.10, 0.20),
    ("> 20 %", 0.20, 10.0),
)
BASE_RATES: dict[str, dict[str, float]] = {
    "decrece": {"p25": -0.0165, "p50": 0.011, "p75": 0.0642, "n": 92},
    "0-5 %": {"p25": -0.0199, "p50": 0.0154, "p75": 0.0444, "n": 129},
    "5-10 %": {"p25": 0.0092, "p50": 0.044, "p75": 0.0807, "n": 111},
    "10-20 %": {"p25": 0.0183, "p50": 0.073, "p75": 0.1134, "n": 91},
    "> 20 %": {"p25": 0.0202, "p50": 0.0631, "p75": 0.2053, "n": 60},
}
BASE_RATE_SOURCE = (
    "SEC companyfacts (10-K, primera cifra publicada por ejercicio) de 200 valores del S&P 500 elegidos con "
    "semilla fija 20261108, sin financieras (SIC 6000–6799): 161 empresas y 483 observaciones con inicio "
    "2010–2014. Sesgo conocido: son supervivientes (miembros actuales del índice), así que las tasas pecan "
    "de optimistas."
)


@dataclass(frozen=True)
class History:
    """Ejercicios anuales ascendentes (millones). ``None`` = sin dato ese año."""

    years: Sequence[int]
    revenue: Sequence[float | None]
    earnings: Sequence[float | None]  # EBITDA (ev_ebitda) o beneficio neto (pe)
    operating_cash_flow: Sequence[float | None] = ()
    capex: Sequence[float | None] = ()
    dividends: Sequence[float | None] = ()
    buybacks: Sequence[float | None] = ()
    acquisitions: Sequence[float | None] = ()
    sbc: float | None = None


@dataclass
class ScenarioSet:
    drivers: dict[str, Drivers]
    trace: dict[str, Any] = field(default_factory=dict)  # palanca → valores y su porqué
    warnings: list[str] = field(default_factory=list)


def _last(values: Sequence[float | None], n: int = 3) -> list[float]:
    return [float(v) for v in list(values)[-n:] if v is not None]


def _cagr(values: Sequence[float | None], n: int = 3) -> tuple[float | None, int]:
    vals = [v for v in list(values) if v is not None and v > 0]
    if len(vals) < 2:
        return None, 0
    span = min(n, len(vals) - 1)
    return (vals[-1] / vals[-1 - span]) ** (1 / span) - 1, span


def base_rate_for(growth: float | None) -> tuple[str | None, dict[str, float] | None]:
    if growth is None:
        return None, None
    for name, lo, hi in BASE_RATE_BUCKETS:
        if lo <= growth < hi:
            return name, BASE_RATES.get(name)
    return None, None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_scenarios(sp: StartingPoint, hist: History, *, peer_multiples: Sequence[float] = (),
                    guidance_growth: float | None = None) -> ScenarioSet:
    """Los tres escenarios según la regla del docstring. Puro y determinista."""
    out = ScenarioSet(drivers={})
    m0 = sp.multiple
    if m0 is None:
        raise ValueError("sin múltiplo de partida")
    lo_b, hi_b = MULTIPLE_BOUNDS[sp.basis]
    if not lo_b / 2 <= m0 <= hi_b * 2:
        raise ValueError(
            f"múltiplo de partida {m0:.1f}x fuera del rango que la regla puede proyectar ({lo_b / 2:g}–{hi_b * 2:g}x): "
            "el EBITDA o el beneficio contable no representa lo que gana el accionista"
        )
    margins = [e / r for r, e in zip(hist.revenue, hist.earnings, strict=False)
               if r is not None and e is not None and r > 0]
    margin_last3 = margins[-3:]
    # conversión de caja por año
    conv = []
    for e, o, c in zip(hist.earnings, hist.operating_cash_flow or [None] * len(hist.years),
                       hist.capex or [None] * len(hist.years), strict=False):
        if e and e > 0 and o is not None:
            conv.append((o - abs(c or 0.0)) / e)
    conv = conv[-3:]
    rev_last3 = _last(hist.revenue)
    acq_last3 = [abs(a) for a in _last(hist.acquisitions)] if hist.acquisitions else []
    mna_pct = (sum(acq_last3) / sum(rev_last3[-len(acq_last3):])) if acq_last3 and rev_last3 else 0.0
    mna_pct = _clamp(mna_pct, 0.0, 0.15)
    margin0 = sp.margin or (margin_last3[-1] if margin_last3 else 0.0)
    acquired_growth = (mna_pct / m0 / margin0) if (mna_pct > 0 and margin0 > 0) else 0.0
    g_total, span = _cagr(hist.revenue)
    if g_total is None:
        out.warnings.append("sin dos ejercicios de ingresos: crecimiento histórico desconocido; se usa la tasa base del tramo 0-5 %")
        g_org_hist = None
    else:
        g_org_hist = g_total - acquired_growth
    bucket, br = base_rate_for(g_org_hist if g_org_hist is not None else 0.02)
    if br is None:
        br = {"p25": 0.0, "p50": 0.03, "p75": 0.06, "n": 0}
        out.warnings.append("sin tabla de tasas base para el tramo: se usa 0 / 3 / 6 %")
    shrunk = br["p50"] if g_org_hist is None else 0.5 * g_org_hist + 0.5 * br["p50"]
    base_g = shrunk if guidance_growth is None else (shrunk + guidance_growth) / 2
    growth = {"bear": min(br["p25"], base_g - 0.02), "base": base_g, "bull": max(br["p75"], base_g + 0.02)}
    late = {k: (v + LONG_RUN_GROWTH) / 2 for k, v in growth.items()}
    out.trace["crecimiento"] = {
        "historico_total": g_total, "anos_historico": span, "comprado": acquired_growth,
        "historico_organico": g_org_hist, "tramo_tasa_base": bucket, "tasa_base": br,
        "guia": guidance_growth, "valores": growth, "anos_6_10": late,
    }
    # margen
    if margin_last3:
        mg = {"bear": min(margin_last3), "base": median(margin_last3), "bull": max(margin_last3)}
    else:
        mg = dict.fromkeys(SCENARIOS, margin0)
        out.warnings.append("sin margen histórico: margen constante")
    out.trace["margen"] = {"ultimos": margin_last3, "partida": margin0, "valores": mg}
    lo_c, hi_c = {"pe": (0.3, 1.5), "pb": (0.0, 1.0)}.get(sp.basis, (0.0, 1.2))
    if conv:
        cv = {"bear": min(conv), "base": median(conv), "bull": max(conv)}
    else:
        cv = dict.fromkeys(SCENARIOS, 0.5)
        out.warnings.append("sin flujo de caja operativo y capex: conversión supuesta del 50 %")
    cv = {k: _clamp(v, lo_c, hi_c) for k, v in cv.items()}
    if sp.basis == "pb":
        # Valor contable: lo que no se reparte se queda en el balance y compone al ROE. Un único reparto (el
        # mediano) para los tres escenarios; el crecimiento del valor contable = ROE × (1 − reparto), así que
        # el escenario cambia por el ROE, no por un crecimiento elegido aparte.
        cv = dict.fromkeys(SCENARIOS, cv["base"])
        growth = {k: mg[k] * (1 - cv[k]) for k in SCENARIOS}
        late = {k: (v + LONG_RUN_GROWTH) / 2 for k, v in growth.items()}
        out.trace["crecimiento"] |= {
            "valores": growth, "anos_6_10": late, "tramo_tasa_base": None, "tasa_base": None,
            "regla": "valor contable: ROE del escenario × (1 − reparto mediano de los tres últimos ejercicios)",
        }
    out.trace["conversion"] = {"ultimos": conv, "valores": cv}
    mna = {"bear": mna_pct / 2, "base": mna_pct, "bull": mna_pct}
    out.trace["mna"] = {"gasto_pct_ingresos": mna_pct, "multiplo_pagado": m0, "valores": mna}
    # reparto
    fcfs = [(o - abs(c or 0.0)) for o, c in zip(hist.operating_cash_flow or [], hist.capex or [None] * 99, strict=False)
            if o is not None][-3:]
    acq_for = acq_last3[-len(fcfs):] if acq_last3 else [0.0] * len(fcfs)
    pool = sum(fcfs) - sum(acq_for)
    div3 = sum(abs(x) for x in _last(hist.dividends)) if hist.dividends else 0.0
    bb3 = sum(abs(x) for x in _last(hist.buybacks)) if hist.buybacks else 0.0
    if pool > 0:
        dp, bp = div3 / pool, bb3 / pool
        if dp + bp > 1:
            dp, bp = dp / (dp + bp), bp / (dp + bp)
    else:
        dp, bp = 0.0, 0.0
        if div3 or bb3:
            out.warnings.append("flujo libre tras M&A ≤ 0 en los últimos años: reparto proyectado nulo")
    out.trace["reparto"] = {"dividendo": dp, "recompras": bp, "deuda": 1 - dp - bp}
    sbc_rate = (hist.sbc / sp.market_cap) if (hist.sbc and sp.market_cap > 0) else 0.0
    out.trace["dilucion_sbc"] = {"tasa_anual": sbc_rate}
    # múltiplo
    lo_m, hi_m = MULTIPLE_BOUNDS[sp.basis]
    peers = sorted(m for m in peer_multiples if m and m > 0)
    if len(peers) >= MIN_PEERS:
        pm = median(peers)
        ex = {"bear": 0.9 * min(m0, pm), "base": (m0 + pm) / 2, "bull": max(m0, pm)}
        why = "media entre el múltiplo propio y la mediana de los comparables calculados"
    else:
        pm = None
        ex = {"bear": 0.8 * m0, "base": m0, "bull": 1.2 * m0}
        why = f"menos de {MIN_PEERS} comparables calculados: base sin cambio de múltiplo"
        out.warnings.append(why)
    ex = {k: _clamp(v, lo_m, hi_m) for k, v in ex.items()}
    out.trace["multiplo"] = {"propio": m0, "mediana_comparables": pm, "n_comparables": len(peers),
                             "valores": ex, "por_que": why}
    for k in SCENARIOS:
        out.drivers[k] = Drivers(
            organic_growth=growth[k], organic_growth_late=late[k], mna_spend_pct_revenue=mna[k],
            margin_target=mg[k], cash_conversion=cv[k], dividend_payout=dp, buyback_payout=bp,
            sbc_dilution=sbc_rate, exit_multiple=ex[k],
        )
    return out


def sensitivity_axes(sp: StartingPoint, scen: ScenarioSet) -> tuple[list[float], list[float]]:
    """Ejes de la tabla: crecimiento base ±1,5 y ±3 pp; múltiplo de bajista a alcista en 5 pasos."""
    g = scen.drivers["base"].organic_growth
    growths = [round(g + d, 4) for d in (-0.03, -0.015, 0.0, 0.015, 0.03)]
    lo, hi = scen.drivers["bear"].exit_multiple, scen.drivers["bull"].exit_multiple
    if hi - lo < 1e-6:
        lo, hi = lo * 0.8, hi * 1.2
    mults = [round(lo + (hi - lo) * i / 4, 2) for i in range(5)]
    return growths, mults


def probabilities(choice: str | None) -> tuple[str, dict[str, float]]:
    key = choice if choice in PROBABILITY_SETS else DEFAULT_PROBABILITIES
    return key, PROBABILITY_SETS[key]


__all__ = [
    "BASE_RATES",
    "PROBABILITY_SETS",
    "RULES_VERSION",
    "SCENARIOS",
    "SCENARIO_LABELS",
    "History",
    "ScenarioSet",
    "base_rate_for",
    "build_scenarios",
    "probabilities",
    "sensitivity_axes",
]
