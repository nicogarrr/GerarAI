"""Estimación propia de ingresos a +3–5 años por fase e industria («fase-industria-v1», PREREG bear 9-nov-2026).

Para una empresa preingresos o que quema caja SIN consenso, guía ni cartera (paso 3 de preingresos-v2), los
ingresos del año T salen de lo que hicieron las empresas de su industria que estaban en la misma fase:
cociente ingresos(s+N) / ingresos(s) de cada empresa activa con ingresos del último ejercicio en el mismo
tramo, en el mismo SIC de 3 dígitos. Bajista / base / alcista = p25 / mediana / p75.

* Fuente: SEC (gratis). Lista de empresas: EDGAR browse-by-SIC (incluye registrantes inactivos, así que no
  son solo supervivientes); ingresos: SEC frames us-gaap CY en USD (máximo de Revenues,
  RevenueFromContractWithCustomerExcluding/IncludingAssessedTax y SalesRevenueNet); actividad: hecho de ingresos
  o de ResearchAndDevelopmentExpense ese año. Lo calcula ``scripts/revenue_phase_rates.py``.
* Fases (ingresos del último ejercicio): F1 1–10 M, F2 10–50 M, F3 50–250 M. Con < 1 M (F0) no hay cifra:
  la mitad de esas empresas seguía sin ingresos a 3–5 años, y la regla no pasaba su prueba (N/D con motivo).
* Supuesto declarado: una empresa activa en s+N sin ingresos etiquetados cuenta con 0. Las que dejaron de
  presentar (adquiridas, excluidas o quebradas) quedan fuera de los percentiles; su porcentaje va en la tabla.
* Tabla: partidas 2015–2019. Prueba fuera de muestra (partidas 2014, no usadas en nada antes): realizado
  dentro de [p25, p75] 57 %, por debajo 18 %, por encima 24 % (n = 526). Celda con n < 30 → N/D.
"""
from __future__ import annotations

from typing import Any

RULES_VERSION = "fase-industria-v1 (prerregistrada 9-nov-2026; prueba fuera de muestra con partidas 2014)"
PHASES: tuple[tuple[str, float, float], ...] = (("F1", 1.0, 10.0), ("F2", 10.0, 50.0), ("F3", 50.0, 250.0))
PHASE_LABELS = {"F1": "ingresos de 1–10 M", "F2": "ingresos de 10–50 M", "F3": "ingresos de 50–250 M"}
MIN_N = 30
SOURCE = ("SEC: EDGAR browse-by-SIC (SIC 2833–2836, 8731, 3826; incluye inactivas) y SEC frames us-gaap CY "
          "2014–2024; partidas 2015–2019; scripts/revenue_phase_rates.py")
#: (SIC de 3 dígitos, fase, N años) → percentiles del cociente ingresos(s+N)/ingresos(s), n y % de inactivas.
RATES: dict[tuple[str, str, int], dict[str, float]] = {
    ("283", "F1", 3): {"p25": 0.3060, "p50": 1.2925, "p75": 4.5785, "n": 466, "inactivas": 0.143},
    ("283", "F1", 4): {"p25": 0.1528, "p50": 1.1144, "p75": 4.9861, "n": 434, "inactivas": 0.202},
    ("283", "F1", 5): {"p25": 0.0929, "p50": 1.0743, "p75": 6.7367, "n": 396, "inactivas": 0.272},
    ("283", "F2", 3): {"p25": 0.3371, "p50": 1.2667, "p75": 2.9385, "n": 417, "inactivas": 0.201},
    ("283", "F2", 4): {"p25": 0.3153, "p50": 1.4483, "p75": 3.9401, "n": 381, "inactivas": 0.270},
    ("283", "F2", 5): {"p25": 0.3016, "p50": 1.5329, "p75": 3.9477, "n": 350, "inactivas": 0.330},
    ("283", "F3", 3): {"p25": 0.6452, "p50": 1.1050, "p75": 1.8267, "n": 293, "inactivas": 0.184},
    ("283", "F3", 4): {"p25": 0.5197, "p50": 1.1602, "p75": 2.2319, "n": 272, "inactivas": 0.242},
    ("283", "F3", 5): {"p25": 0.6031, "p50": 1.2530, "p75": 2.5329, "n": 244, "inactivas": 0.320},
}


def phase_for(revenue_millions: float | None) -> str | None:
    if revenue_millions is None:
        return None
    for name, lo, hi in PHASES:
        if lo <= revenue_millions < hi:
            return name
    return None


def estimate(sic: int | None, last_revenue_millions: float | None, years: int) -> tuple[dict[str, Any] | None, str]:
    """({year_offset, base, low, high, phase, group, n, inactivas, ratios}, etiqueta) o (None, motivo). Puro."""
    if sic is None:
        return None, "sin SIC: no hay tasa base por industria"
    if not last_revenue_millions or last_revenue_millions <= 0:
        return None, "sin ingresos en el último ejercicio: la tasa base por fase no da una cifra"
    phase = phase_for(last_revenue_millions)
    if phase is None:
        return None, ("ingresos del último ejercicio < 1 M: la tasa base por fase no da una cifra (la mitad de "
                      "esas empresas seguía sin ingresos a 3–5 años)" if last_revenue_millions < 1
                      else "ingresos del último ejercicio ≥ 250 M: fuera de las fases de la tabla")
    group = str(int(sic))[:3]
    cell = RATES.get((group, phase, int(years)))
    if cell is None or cell["n"] < MIN_N:
        return None, f"sin tasa base para SIC {group}x en la fase {PHASE_LABELS[phase]} (menos de {MIN_N} empresas)"
    out = {"years": int(years), "phase": phase, "group": group, "n": int(cell["n"]), "inactivas": cell["inactivas"],
           "ratios": {k: cell[k] for k in ("p25", "p50", "p75")},
           "base": last_revenue_millions * cell["p50"], "low": last_revenue_millions * cell["p25"],
           "high": last_revenue_millions * cell["p75"]}
    label = (f"estimación propia: tasa base por fase e industria (SIC {group}x, {PHASE_LABELS[phase]}, "
             f"n = {out['n']}; {cell['inactivas']:.0%} dejaron de presentar y no cuentan)")
    return out, label


__all__ = ["MIN_N", "PHASES", "RATES", "RULES_VERSION", "SOURCE", "estimate", "phase_for"]
