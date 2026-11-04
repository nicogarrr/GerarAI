"""Margen FCF de ciclo medio para empresas cíclicas en el DCF estándar.

Decisión de Nico (4-nov-2026, 11:40, «mete todo lo que mejores resultados
tenga»), con la evidencia del backtest point-in-time 2 (82 empresas de EE. UU.,
2015–2026; variantes elegidas con 2015–20 y validadas con 2021–26): en
petróleo y gas, minería y metales, acero y fabricantes de coches, el margen
FCF del último ejercicio (o su mediana de 3 años) es una foto de un punto del
ciclo, no del negocio. El error mediano a 12 meses de esas empresas era del
99 % en los dos periodos; con la media de 5 ejercicios y crecimiento plano igual
al terminal baja al 53 % en 2021–26 (96 % en 2015–20). Con 7 años, con CAGR de
6 años o incluyendo semiconductores sale peor, por eso esos quedan fuera.

Reglas (generales, sin listas de tickers):

* la empresa es cíclica si su industria (la de la ficha o la de la referencia
  del instrumento) encaja en ``CYCLICAL_INDUSTRIES`` y ninguna de las dos en
  ``CYCLICAL_INDUSTRY_EXCLUSIONS`` (semiconductores, midstream, componentes de
  automóvil, concesionarios, utilities);
* margen = media del margen FCF real ((flujo operativo − capex) / ingresos) de
  ejercicios con datos dentro de los últimos ``CYCLICAL_MIDCYCLE_YEARS``
  (contados desde el último ejercicio con ingresos), con el mismo corte
  point-in-time que el snapshot; con menos de
  ``CYCLICAL_MIDCYCLE_MIN_YEARS`` no se aplica y la traza dice por qué;
* crecimiento plano igual al terminal en toda la proyección y sin
  normalización de capex (ya es un margen de ciclo medio);
* con margen de ciclo medio ≤ 0 no se publica un DCF;
* un método de valoración declarado en el maestro (distinto de los genéricos)
  prevalece y la regla no se aplica (la traza lo dice).
"""

from __future__ import annotations

import re
from typing import Any

# Industrias cíclicas, como expresiones sobre el texto de industria (en
# minúsculas) de los proveedores que hay en prod: financedatabase («Oil, Gas &
# Fuels», «Oilfield Services & Equipment», «Mining & Metals», «Automobiles»),
# GICS/Finnhub («Metals & Mining», «Automobiles», «Oil & Gas Integrated») y
# Yahoo («Oil & Gas E&P», «Steel», «Copper», «Auto Manufacturers»…).
CYCLICAL_INDUSTRIES: dict[str, str] = {
    "oil_gas": r"\boil\b|\boilfield\b|\bpetroleum\b",
    "mining_metals": r"\bmining\b|\bsteel\b|\balumin(?:um|ium)\b|\bcopper\b|\bcoal\b|\bgold\b|\bsilver\b",
    "autos": r"\bautomobiles?\b|\bauto manufacturers?\b|\bautomobile manufacturers?\b",
}

# Aunque encajen arriba, no se tratan como cíclicas: los semiconductores
# empeoran el backtest en 2021–26, el midstream cobra por volumen (no por
# precio), y componentes, concesionarios y utilities no son productores.
CYCLICAL_INDUSTRY_EXCLUSIONS = r"semiconductor|midstream|\bparts\b|component|dealership|utilit"

CYCLICAL_MIDCYCLE_YEARS = 5
CYCLICAL_MIDCYCLE_MIN_YEARS = 3

# Métodos que no declaran nada propio: con cualquier otro, el método declarado
# prevalece sobre la regla por industria.
GENERIC_VALUATION_MODELS = frozenset({"", "unassigned", "standard_dcf", "dcf"})

_MARGIN_METRICS = ("revenue", "operating_cash_flow", "capital_expenditure")
_EXCLUSION_RE = re.compile(CYCLICAL_INDUSTRY_EXCLUSIONS, re.IGNORECASE)
_GROUP_RES = {group: re.compile(rx, re.IGNORECASE) for group, rx in CYCLICAL_INDUSTRIES.items()}


def cyclical_industry_groups(*industries: str | None) -> list[str]:
    """Grupos cíclicos que encajan con alguna de las industrias dadas.

    Lista vacía si ninguna encaja o si alguna cae en las exclusiones.
    """
    labels = [value for value in industries if value]
    if any(_EXCLUSION_RE.search(value) for value in labels):
        return []
    return [group for group, rx in _GROUP_RES.items() if any(rx.search(value) for value in labels)]


def _industries(company) -> tuple[str | None, str | None]:
    from app.valuation.engines.registry import reference_industry

    own = getattr(company, "industry", None)
    try:
        reference = reference_industry(company)
    except Exception:  # noqa: BLE001 - sin referencia, solo la ficha
        reference = None
    return own, reference


def midcycle_fcf_margin(db, company_id: int, as_of) -> dict[str, Any]:
    """Media del margen FCF real de los últimos ejercicios (point-in-time)."""
    from app.valuation.normalized_fcf import fy_history

    history = fy_history(db, company_id, as_of, metrics=_MARGIN_METRICS)
    # Ventana = los últimos CYCLICAL_MIDCYCLE_YEARS ejercicios contados desde
    # el último con ingresos: un hueco de datos recientes no puede convertir
    # la media en la de un ciclo de hace años.
    revenue_years = [year for year, row in history.items() if "revenue" in row]
    first_year = max(revenue_years) - CYCLICAL_MIDCYCLE_YEARS + 1 if revenue_years else None
    periods = []
    for year in sorted(history, reverse=True):
        if first_year is None or year < first_year:
            break
        row = history[year]
        if not all(metric in row for metric in _MARGIN_METRICS):
            continue
        if len({(row[m].unit or "") for m in _MARGIN_METRICS}) != 1:
            continue
        revenue = float(row["revenue"].value)
        if revenue <= 0:
            continue
        ocf = float(row["operating_cash_flow"].value)
        capex = abs(float(row["capital_expenditure"].value))
        periods.append(
            {
                "fiscal_year": int(year),
                "fcf_margin": (ocf - capex) / revenue,
                "fact_ids": [row[m].id for m in _MARGIN_METRICS if row[m].id is not None],
            }
        )
        if len(periods) >= CYCLICAL_MIDCYCLE_YEARS:
            break
    if len(periods) < CYCLICAL_MIDCYCLE_MIN_YEARS:
        return {
            "applied": False,
            "years_used": len(periods),
            "periods": periods,
            "reason": (
                f"solo hay {len(periods)} ejercicios con flujo operativo, capex e ingresos "
                f"en los últimos {CYCLICAL_MIDCYCLE_YEARS} (mínimo {CYCLICAL_MIDCYCLE_MIN_YEARS}); "
                "se usa el margen habitual"
            ),
        }
    margin = sum(item["fcf_margin"] for item in periods) / len(periods)
    return {
        "applied": True,
        "years_used": len(periods),
        "periods": periods,
        "margin": margin,
    }


def cyclical_midcycle(context) -> dict[str, Any] | None:
    """None si la empresa no es cíclica; si lo es, la decisión con su traza."""
    groups = cyclical_industry_groups(*_industries(context.company))
    if not groups:
        return None
    own, reference = _industries(context.company)
    base = {
        "cyclical": True,
        "industries_matched": groups,
        "industry": own,
        "reference_industry": reference,
        "years_target": CYCLICAL_MIDCYCLE_YEARS,
        "min_years": CYCLICAL_MIDCYCLE_MIN_YEARS,
    }
    declared = (getattr(context.company, "valuation_model", None) or "").strip().lower()
    if declared not in GENERIC_VALUATION_MODELS:
        # Un método declarado en el maestro (p. ej. escenarios de coche +
        # energía + conducción autónoma) describe la empresa mejor que la
        # regla por industria, y el motor de escenarios parte de este DCF.
        return {
            **base,
            "applied": False,
            "years_used": 0,
            "periods": [],
            "reason": f"prevalece el método declarado «{declared}»; se usa el margen habitual",
        }
    try:
        result = midcycle_fcf_margin(
            getattr(context, "db", None), context.company.id, getattr(context, "as_of", None)
        )
    except Exception:  # noqa: BLE001 - sin historial, comportamiento anterior
        result = {
            "applied": False,
            "years_used": 0,
            "periods": [],
            "reason": "no se pudo leer el historial de ejercicios; se usa el margen habitual",
        }
    return {**base, **result}
