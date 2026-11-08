"""Empresas que queman caja: por qué no hay un valor justo fiable y qué pasó con su precio.

Medido, no supuesto (backtest gerarai-dcavalor4, 7-nov-2026; pre-registro y cifras en
el directorio de trabajo): 4.002 empresa-año de EE. UU. con pérdidas, flujo de caja
libre negativo y más de 100 M$ de capitalización (datos anuales SEC de 2013 a 2023,
valoradas el 1 de mayo siguiente; precios de Yahoo hasta mayo de 2026).

* El motor ``pre_revenue`` da N/D en el 100 % de esos casos: con FCF negativo solo
  calcula si hay un margen objetivo de analista con fuente, y en el histórico no lo hay.
* El DCF de Damodaran para empresas jóvenes (crecimiento que se apaga, margen hacia
  el 12 %, probabilidad de fracaso por meses de caja) ordena algo (IC a 12 meses 0,12 y
  0,09 en 2014-18 y 2019-24) pero su cifra no sirve: la mitad de las veces sale fuera
  de 0,2x-5x el precio, y su rango bajista-alcista (×7-8 de ancho) solo contiene el
  precio a 12 meses el 47 % de las veces. Tampoco un rango por resultados pasados
  aguanta fuera de muestra (el de 2014-18 cubrió el 64-69 % en 2019-24, no el 80 %).
* Lo que sí pasó, entre las que siguieron cotizando: precio a 12 meses / precio de
  partida p10 0,24x, mediana 0,81x, p90 1,95x; solo el 31 % batió al S&P 500. De las de
  más de 100 M$ de capital flotante, el 17 % dejó de presentar cuentas a la SEC en 2
  años (quiebra, compra o exclusión); sin ellas, las cifras de arriba salen optimistas.

Es historia del grupo, no una previsión de cada empresa. Se adjunta solo cuando el
resultado sale del motor ``pre_revenue`` con caja quemada (FCF o margen FCF <= 0).
"""

from __future__ import annotations

from typing import Any

TRACK_RECORD_ENGINE = "pre_revenue"
CASES = 4002
#: Precio a 12 / 24 meses entre precio de partida (percentiles 10, 50 y 90), supervivientes.
PRICE_RATIO_12M = {"p10": 0.24, "p50": 0.81, "p90": 1.95}
PRICE_RATIO_24M = {"p10": 0.13, "p50": 0.72, "p90": 2.35}
BEAT_SPY_12M_SHARE = 0.31
STOPPED_FILING_24M_SHARE = 0.17
ENGINE_NO_VALUE_SHARE = 1.0
YOUNG_FIRM_DCF_OUTSIDE_02_5X_SHARE = 0.50
YOUNG_FIRM_DCF_RANGE_COVERAGE_12M = 0.47
SAMPLE_ES = (
    "4.002 empresa-año de EE. UU. con pérdidas, FCF negativo y más de 100 M$ de "
    "capitalización, datos SEC 2013–2023 valorados en mayo del año siguiente, precios hasta mayo de 2026"
)


def _x(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _pct(value: float) -> str:
    return f"{round(value * 100)} %"


def _burns_cash(result: dict[str, Any], trace: dict[str, Any]) -> bool:
    """FCF o margen FCF reportado <= 0, tal como lo deja escrito el motor."""
    if trace.get("rejected_reported_fcf"):
        return True
    missing = result.get("missing_inputs") or trace.get("missing_inputs") or []
    if isinstance(missing, list) and "non_negative_fcf_margin" in missing:
        return True
    reported = trace.get("reported_fcf_margin")
    return (
        isinstance(reported, (int, float))
        and not isinstance(reported, bool)
        and reported <= 0
    )


def pre_revenue_track_record(result: dict[str, Any]) -> dict[str, Any] | None:
    """Historial medido para una empresa que quema caja, o None si no aplica.

    Solo para un resultado del motor ``pre_revenue`` (``trace.engine``) cuyo FCF o
    margen FCF reportado es <= 0: con caja positiva el motor hace otro cálculo, que
    no es el de esta muestra.
    """
    trace = result.get("trace") or {}
    if not isinstance(trace, dict) or trace.get("engine") != TRACK_RECORD_ENGINE:
        return None
    if not _burns_cash(result, trace):
        return None
    p12 = PRICE_RATIO_12M
    return {
        "method": TRACK_RECORD_ENGINE,
        "reliable_value": False,
        "horizon_months": 12,
        "cases": CASES,
        "price_ratio_12m": dict(p12),
        "price_ratio_24m": dict(PRICE_RATIO_24M),
        "beat_spy_12m_share": BEAT_SPY_12M_SHARE,
        "stopped_filing_24m_share": STOPPED_FILING_24M_SHARE,
        "engine_no_value_share": ENGINE_NO_VALUE_SHARE,
        "young_firm_dcf_outside_02_5x_share": YOUNG_FIRM_DCF_OUTSIDE_02_5X_SHARE,
        "young_firm_dcf_range_coverage_12m": YOUNG_FIRM_DCF_RANGE_COVERAGE_12M,
        "sample_es": SAMPLE_ES,
        "message_es": (
            "Sin valor justo fiable: la empresa aún quema caja. En el backtest (4.002 casos así en "
            "EE. UU., 2014–2026) ningún método acertó el nivel: el DCF para empresas jóvenes salió "
            f"fuera de 0,2x–5x el precio la mitad de las veces. A 12 meses, 8 de cada 10 veces el "
            f"precio quedó entre {_x(p12['p10'])}x y {_x(p12['p90'])}x el de partida (mediana "
            f"{_x(p12['p50'])}x); solo el {_pct(BEAT_SPY_12M_SHARE)} batió al S&P 500, y el "
            f"{_pct(STOPPED_FILING_24M_SHARE)} dejó de presentar cuentas en 2 años."
        ),
        "message_en": (
            "No reliable fair value: the company still burns cash. In the backtest (4,002 such US "
            "cases, 2014–2026) no method got the level right: the young-company DCF landed outside "
            f"0.2x–5x the price half the time. After 12 months, 8 times out of 10 the price was "
            f"between {p12['p10']:.2f}x and {p12['p90']:.2f}x the starting price (median "
            f"{p12['p50']:.2f}x); only {round(BEAT_SPY_12M_SHARE * 100)}% beat the S&P 500, and "
            f"{round(STOPPED_FILING_24M_SHARE * 100)}% stopped filing within 2 years."
        ),
    }
