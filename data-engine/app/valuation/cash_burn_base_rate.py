"""Tasas base de las empresas que queman caja, junto a cualquier valor justo suyo.

Medido, no supuesto (backtest gerarai-dcavalor4, 7-nov-2026): empresas de EE. UU. con
beneficio neto y flujo de caja operativo negativos en su último ejercicio y más de
100 M$ de capital flotante (datos SEC de 2013 a 2023, compradas el 1 de mayo
siguiente, precios de Yahoo hasta mayo de 2026). 2.845 casos con resultado a 24 meses:
las que siguen cotizando con su rentabilidad total y las que dejaron de presentar
cuentas a la SEC (quiebra, compra o exclusión; el 15 %) contadas con −90 %.

* Rentabilidad mediana a 24 meses: −51 % (2014-18: −41 %; 2019-24: −52 %).
* La mitad cayó más de un 50 % (46 % y 51 %); el 11 % más que duplicó.
* Solo el 21 % batió al S&P 500 a 24 meses.

No sustituye ni corrige la cifra (la de una tesis son sus escenarios): dice de dónde
parte una empresa así. Es historia del grupo, no una previsión de esta empresa.
"""

from __future__ import annotations

from typing import Any

CASES = 2845
MEDIAN_RETURN_24M = -0.51
MEDIAN_RETURN_24M_BY_PERIOD = {"2014_2018": -0.41, "2019_2024": -0.52}
FELL_OVER_HALF_24M_SHARE = 0.50
DOUBLED_24M_SHARE = 0.11
BEAT_SPY_24M_SHARE = 0.21
STOPPED_FILING_24M_SHARE = 0.15


def _pct(value: float) -> str:
    return f"{round(value * 100)} %"


def burns_cash(latest: dict[str, float | None]) -> bool:
    """Último ejercicio con beneficio neto Y flujo de caja operativo negativos."""
    ni = latest.get("net_income")
    ocf = latest.get("operating_cash_flow")
    return ni is not None and ocf is not None and ni < 0 and ocf < 0


def latest_fiscal_year_values(facts: list[Any]) -> dict[str, float | None]:
    """Beneficio neto y flujo operativo del ÚLTIMO ejercicio que tiene los dos.

    ``facts`` son HealthFact (metric, year, value). Si el ejercicio más reciente solo
    trae uno de los dos, se usa el anterior completo: nunca se mezclan años.
    """
    by_year: dict[int, dict[str, float]] = {}
    for fact in facts:
        if fact.metric in ("net_income", "operating_cash_flow"):
            by_year.setdefault(int(fact.year), {})[fact.metric] = float(fact.value)
    for year in sorted(by_year, reverse=True):
        row = by_year[year]
        if "net_income" in row and "operating_cash_flow" in row:
            return {"fiscal_year": year, **row}
    return {}


def cash_burn_base_rate(latest: dict[str, float | None], fair_value: dict[str, Any]) -> dict[str, Any] | None:
    """Línea informativa para un valor justo con cifra de una empresa que quema caja."""
    value = fair_value.get("value") if isinstance(fair_value, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        return None
    if not burns_cash(latest):
        return None
    return {
        "fiscal_year": latest.get("fiscal_year"),
        "cases": CASES,
        "median_return_24m": MEDIAN_RETURN_24M,
        "median_return_24m_by_period": dict(MEDIAN_RETURN_24M_BY_PERIOD),
        "fell_over_half_24m_share": FELL_OVER_HALF_24M_SHARE,
        "doubled_24m_share": DOUBLED_24M_SHARE,
        "beat_spy_24m_share": BEAT_SPY_24M_SHARE,
        "stopped_filing_24m_share": STOPPED_FILING_24M_SHARE,
        "message_es": (
            "Punto de partida: la empresa aún pierde dinero y quema caja. En el backtest "
            "(2.845 casos así en EE. UU., 2014–2026, contando las que desaparecieron), a 2 años "
            f"la rentabilidad mediana fue {_pct(MEDIAN_RETURN_24M)}: la mitad cayó más de un 50 %, "
            f"el {_pct(DOUBLED_24M_SHARE)} más que duplicó y solo el {_pct(BEAT_SPY_24M_SHARE)} "
            "batió al S&P 500. No cambia esta cifra."
        ),
        "message_en": (
            "Starting point: the company still loses money and burns cash. In the backtest "
            "(2,845 such US cases, 2014–2026, including those that disappeared), the median "
            f"2-year return was {round(MEDIAN_RETURN_24M * 100)}%: half fell more than 50%, "
            f"{round(DOUBLED_24M_SHARE * 100)}% more than doubled and only "
            f"{round(BEAT_SPY_24M_SHARE * 100)}% beat the S&P 500. It does not change this figure."
        ),
    }
