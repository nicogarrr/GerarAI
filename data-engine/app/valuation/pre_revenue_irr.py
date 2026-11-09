"""Valoración de una empresa preingresos o que quema caja: runway, dilución y TIR por escenarios (puro).

Regla PRE-REGISTRADA (``RULES_VERSION``, fijada el 9-nov-2026 antes de mirar ningún resultado; se cambia
solo con un PR nuevo). Ningún parámetro depende del emisor: lo que entra son magnitudes que GerarAI ya
tiene (hechos del filing, consenso citado, guía de la empresa, cartera contratada, comparables) y cada
una lleva su fuente.

1. **Runway** = (caja + inversiones a corto) / consumo trimestral, con consumo trimestral = −FCF del
   último ejercicio / 4 (FCF = flujo de caja operativo − |capex|). Sin consumo (FCF ≥ 0) no hay runway
   que contar; sin FCF es N/D con el input que falta.
2. **Dilución histórica** = TCAC de las acciones diluidas de los tres últimos ejercicios (la del
   servicio). **Dilución proyectada** hasta el break-even, que la regla sitúa en el año de salida T (el
   año en que la empresa se valora como una madura por EV/ventas):
   consumo acumulado hasta T = consumo anual × N × factor, con factor 1 (bajista: el consumo no baja),
   ½ (base: baja en línea recta hasta 0 en T) y ¼ (alcista: llega a 0 a mitad de camino);
   necesidad = máx(0, consumo acumulado + colchón de ``BUFFER_MONTHS`` meses de consumo − caja);
   acciones nuevas = necesidad / precio actual (todo con capital, al precio de hoy).
   En el bajista la dilución es la mayor entre esa y la histórica compuesta N años; las acciones de más
   sobre el hueco no suman caja (financian consumo que la regla no ve). [Corregido el 9-nov tras la primera
   medida: acreditar esa caja ponía el bajista por encima del base, una incoherencia, no un ajuste de nota.]
3. **Ingresos del año T**, T entre el último ejercicio + 3 y + 5 (el más lejano con dato):
   a. estimaciones de firmas citadas (mediana; bajo/alto = mínimo/máximo si hay 2 o más firmas);
   b. «consenso (prensa)» citado;
   c. guía de la propia empresa para ese ejercicio (punto medio; bajo/alto, su rango);
   d. si no hay ninguna de las tres: cartera contratada (backlog / obligaciones de desempeño pendientes)
      del último filing repartida en los años hasta T (suelo contratado).
   Sin rango propio, bajista = base × (1 − ``REVENUE_SPREAD``) y alcista = base × (1 + ``REVENUE_SPREAD``).
4. **Múltiplo EV/ventas**: el de comparables MADUROS (operativos, con ingresos y EV positivos), calculado
   con la misma fórmula (EV / ingresos del último ejercicio) que la empresa. Bajista p25, base mediana,
   alcista p75. La selección es la primera de estas capas con al menos ``MIN_PEERS``: comparables del
   servicio → misma industria → mismo sector → toda la base no financiera; la capa usada se dice.
5. **Valor en T**: EV_T = ingresos_T × múltiplo; caja_T = caja + capital nuevo − consumo acumulado;
   capital_T = EV_T + caja_T − deuda − minoritarios − híbridos (deuda constante); precio_T = capital_T /
   acciones_T; **TIR** = (precio_T / precio)^(1/N) − 1, con N = años desde hoy hasta el cierre de T.
   Capital_T ≤ 0 → TIR −100 %.
Un input que falta deja ESE escenario N/D con el motivo concreto; el resto se calcula igual.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

RULES_VERSION = "preingresos-v1 (prerregistrada 9-nov-2026)"
SCENARIOS = ("bear", "base", "bull")
SCENARIO_LABELS = {"bear": "Bajista", "base": "Base", "bull": "Alcista"}
#: Fracción del consumo anual actual que se acumula cada año hasta el break-even en T.
BURN_FACTOR = {"bear": 1.0, "base": 0.5, "bull": 0.25}
BUFFER_MONTHS = 6.0
REVENUE_SPREAD = 0.5
MIN_PEERS = 3
HORIZON_MIN, HORIZON_MAX = 3, 5


@dataclass(frozen=True)
class RevenueAnchor:
    year: int
    base: float
    low: float | None
    high: float | None
    source: str               # analistas | consenso_prensa | guia | backlog
    label: str
    cite: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PeerMultiple:
    ticker: str
    name: str | None
    ev: float
    revenue: float

    @property
    def multiple(self) -> float:
        return self.ev / self.revenue


def quantile(values: Sequence[float], q: float) -> float:
    """Cuantil con interpolación lineal (el de ``statistics.quantiles`` método inclusive)."""
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def runway(cash: float | None, fcf: float | None, *, missing: str | None = None) -> dict[str, Any]:
    if cash is None:
        return {"quarters": None, "quarterly_burn": None, "missing": "sin caja en el filing"}
    if fcf is None:
        return {"quarters": None, "quarterly_burn": None, "missing": missing or "sin FCF del último ejercicio"}
    if fcf >= 0:
        return {"quarters": None, "quarterly_burn": 0.0, "missing": None, "note": "genera caja: sin consumo"}
    qb = -fcf / 4.0
    return {"quarters": cash / qb, "quarterly_burn": qb, "missing": None}


def choose_anchor(anchors: Sequence[RevenueAnchor], last_fy: int) -> tuple[RevenueAnchor | None, str | None]:
    """El ancla de ingresos de la regla (paso 3) o (None, motivo)."""
    order = {"analistas": 0, "consenso_prensa": 1, "guia": 2, "backlog": 3}
    window = range(last_fy + HORIZON_MIN, last_fy + HORIZON_MAX + 1)
    usable = [a for a in anchors if a.year in window and a.base and a.base > 0 and a.source != "backlog"]
    if usable:
        far = max(a.year for a in usable)
        return min((a for a in usable if a.year == far), key=lambda a: order[a.source]), None
    backlog = [a for a in anchors if a.source == "backlog" and a.base and a.base > 0]
    if backlog:
        return backlog[0], None
    return None, (f"sin consenso de ingresos {last_fy + HORIZON_MIN}–{last_fy + HORIZON_MAX} (ni de firmas, ni de "
                  "prensa, ni guía de la empresa) y sin cartera contratada en los filings")


def peer_stats(peers: Sequence[PeerMultiple]) -> dict[str, float] | None:
    mults = [p.multiple for p in peers if p.revenue > 0 and p.ev > 0]
    if not mults:
        return None
    return {"p25": quantile(mults, 0.25), "median": statistics.median(mults), "p75": quantile(mults, 0.75),
            "n": float(len(mults))}


def years_to(today: date, year: int, fy_end_month: int = 12) -> float:
    import calendar

    end = date(year, fy_end_month, calendar.monthrange(year, fy_end_month)[1])
    return max((end - today).days / 365.25, 0.25)


def _dilution(k: str, *, burn: float, n_years: float, cash: float, price: float, shares: float,
              dilution_hist: float | None) -> dict[str, Any]:
    cum_burn = burn * n_years * BURN_FACTOR[k]
    buffer = burn * BUFFER_MONTHS / 12.0
    need = max(0.0, cum_burn + buffer - cash) if burn > 0 else 0.0
    new_shares = need / price if price > 0 else 0.0
    dil = new_shares / shares if shares > 0 else 0.0
    dil_from = "hueco de financiación"
    if k == "bear" and dilution_hist is not None and dilution_hist > 0:
        hist_dil = (1 + dilution_hist) ** n_years - 1
        if hist_dil > dil:
            dil, dil_from = hist_dil, "dilución histórica compuesta"
            new_shares = shares * dil
    # Solo el capital que cubre el hueco entra en caja: las acciones de más del bajista (dilución histórica)
    # financian consumo que la regla no ve (expansión, compensación en acciones) y no suman caja.
    return {"cumulative_burn": cum_burn, "funding_need": need, "new_shares": new_shares, "dilution": dil,
            "dilution_from": dil_from, "cash_end": cash + need - cum_burn, "shares_end": shares * (1 + dil)}


def scenarios(*, today: date, price: float | None, shares: float | None, cash: float | None, debt: float | None,
              minorities: float, hybrids: float, fcf: float | None, dilution_hist: float | None,
              anchor: RevenueAnchor | None, anchor_missing: str | None, peers: Mapping[str, float] | None,
              peers_missing: str | None, last_fy: int, fy_end_month: int = 12) -> dict[str, Any]:
    """Los tres escenarios de la regla (pasos 2–5), cada uno con su TIR o N/D y su motivo. La dilución
    proyectada se calcula aunque falte el ancla de ingresos o los comparables (con T = último ejercicio + 3)."""
    out: dict[str, Any] = {}
    burn = (-fcf if fcf < 0 else 0.0) if fcf is not None else None
    exit_year = anchor.year if anchor is not None else last_fy + HORIZON_MIN
    n_years = years_to(today, exit_year, fy_end_month)
    for k in SCENARIOS:
        base_missing: list[str] = []
        for name, v in (("precio", price), ("acciones diluidas", shares), ("caja", cash), ("deuda", debt)):
            if v is None:
                base_missing.append(f"sin {name}")
        if burn is None:
            base_missing.append("sin FCF del último ejercicio")
        missing = list(base_missing)
        if anchor is None:
            missing.insert(0, anchor_missing or "sin ingresos a 3–5 años")
        if peers is None:
            missing.insert(0 if anchor is not None else 1, peers_missing or "sin comparables maduros")
        row: dict[str, Any] = {"label": SCENARIO_LABELS[k], "year": exit_year, "years": n_years, "irr": None,
                               "missing": "; ".join(missing) or None}
        if not base_missing:
            assert price is not None and shares is not None and cash is not None and burn is not None
            row.update(_dilution(k, burn=burn, n_years=n_years, cash=cash, price=price, shares=shares,
                                 dilution_hist=dilution_hist))
        if missing:
            out[k] = row
            continue
        assert anchor is not None and peers is not None and debt is not None and price is not None
        if k == "base":
            rev = anchor.base
        elif k == "bear":
            rev = anchor.low if anchor.low is not None else anchor.base * (1 - REVENUE_SPREAD)
        else:
            rev = anchor.high if anchor.high is not None else anchor.base * (1 + REVENUE_SPREAD)
        mult = {"bear": peers["p25"], "base": peers["median"], "bull": peers["p75"]}[k]
        ev_t = rev * mult
        equity_t = ev_t + row["cash_end"] - debt - minorities - hybrids
        price_t = equity_t / row["shares_end"] if row["shares_end"] > 0 else None
        if price_t is None or price <= 0:
            irr = None
        elif price_t <= 0:
            irr = -1.0
        else:
            irr = (price_t / price) ** (1 / n_years) - 1
        row.update({"revenue": rev, "ev_to_sales": mult, "ev": ev_t, "equity": equity_t, "price_end": price_t,
                    "irr": irr})
        out[k] = row
    return out


FORMULAS = {
    "runway": "(caja + inversiones a corto) / (−FCF del último ejercicio / 4), en trimestres",
    "dilucion_historica": "TCAC de las acciones diluidas de los tres últimos ejercicios",
    "dilucion_proyectada": ("máx(0, consumo acumulado hasta el break-even + 6 meses de colchón − caja) / precio "
                            "actual / acciones diluidas; consumo acumulado = consumo anual × años × (1 bajista, "
                            "½ base, ¼ alcista); en el bajista, como mínimo la dilución histórica compuesta"),
    "ingresos": ("ingresos del año de salida (último ejercicio + 3 a + 5): firmas citadas → consenso de prensa → "
                 "guía de la empresa → cartera contratada repartida; sin rango, ±50 %"),
    "multiplo": "EV / ingresos del último ejercicio de comparables maduros: p25 / mediana / p75",
    "tir": ("(precio en T / precio actual)^(1/años) − 1; precio en T = (ingresos × EV/ventas + caja en T − deuda − "
            "minoritarios − híbridos) / acciones tras la dilución"),
}

__all__ = ["BURN_FACTOR", "FORMULAS", "MIN_PEERS", "PeerMultiple", "RULES_VERSION", "RevenueAnchor", "SCENARIOS",
           "choose_anchor", "peer_stats", "quantile", "runway", "scenarios", "years_to"]
