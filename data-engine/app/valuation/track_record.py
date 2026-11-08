"""Fiabilidad histórica del DCF estándar: cuánto se ha alejado el precio del valor.

Medido, no supuesto: réplica point-in-time del DCF estándar vigente (ventas TTM,
caja con inversiones, WACC CAPM trazable como en #4729 —rf + beta × ERP, pesos de
mercado—, capex con tope de 5 años, cíclicas a margen medio), 377 empresas actuales
del S&P 500 sin financieras, inmobiliarias ni utilities, 11.673 valoraciones
trimestrales de 2015 a 2025 con un valor entre 0,2x y 5x el precio
(gerarai-dcavalor2b, 8-nov-2026; la versión de #4732 se midió con la banda de WACC
por tamaño, que #4729 dejó solo como diagnóstico).

* Precio a 12 meses / valor calculado: p10 0,36x, mediana 0,97x, p90 2,57x
  (2015-20: 0,38 / 0,94 / 2,48; 2021-26: 0,35 / 1,02 / 2,68). Solo el 25 % quedó a
  menos de un 25 % del valor. Con la banda era 0,61 / 1,65 / 3,67 (se quedaba corto).
* «Infravalorada» (valor > precio) no anticipa ganar al S&P 500 a 12 meses: lo
  bate el 49 % de las veces, frente al 48 % del resto.
* Ordenar sirve poco: a 24 meses el quintil más barato según el método bate al
  más caro en +0,4 (2015-20) y +1,6 (2021-26) puntos de rentabilidad mediana frente
  al SPY (con la banda, misma medida: +3,8 y +8,6).

Las cifras son del método, no de cada empresa, y no son un precio objetivo: dicen
cuánto pesar el número. Se adjuntan solo cuando el número sale del DCF estándar.
"""

from __future__ import annotations

from typing import Any

TRACK_RECORD_ENGINE = "standard_dcf"
#: Precio a 12 meses / valor calculado (percentiles 10, 50 y 90).
PRICE_TO_VALUE_12M = {"p10": 0.36, "p50": 0.97, "p90": 2.57}
WITHIN_25PCT_SHARE = 0.25
UNDERVALUED_BEAT_SPY_12M = 0.49
REST_BEAT_SPY_12M = 0.48
CHEAPEST_VS_DEAREST_QUINTILE_24M_PTS = {"2015_2020": 0.4, "2021_2026": 1.6}
SAMPLE_ES = (
    "réplica point-in-time del DCF estándar con WACC CAPM, 377 empresas del S&P 500 sin financieras, "
    "inmobiliarias ni utilities, 11.673 valoraciones trimestrales 2015–2025"
)


def _x(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def dcf_track_record(result: dict[str, Any]) -> dict[str, Any] | None:
    """Fiabilidad del método para un resultado del motor, o None si no aplica.

    Solo para un número del DCF estándar (``trace.engine``) con valor esperado > 0:
    otro motor o un respaldo por múltiplos no tiene este historial medido.
    """
    trace = result.get("trace") or {}
    if not isinstance(trace, dict) or trace.get("engine") != TRACK_RECORD_ENGINE:
        return None
    value = result.get("expected_value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        return None
    band = PRICE_TO_VALUE_12M
    return {
        "method": TRACK_RECORD_ENGINE,
        "horizon_months": 12,
        "price_to_value_p10": band["p10"],
        "price_to_value_p50": band["p50"],
        "price_to_value_p90": band["p90"],
        "within_25pct_share": WITHIN_25PCT_SHARE,
        "undervalued_beat_spy_share": UNDERVALUED_BEAT_SPY_12M,
        "rest_beat_spy_share": REST_BEAT_SPY_12M,
        "cheapest_vs_dearest_quintile_24m_pts": dict(CHEAPEST_VS_DEAREST_QUINTILE_24M_PTS),
        "sample_es": SAMPLE_ES,
        "message_es": (
            f"Fiabilidad del método: en el backtest, 8 de cada 10 veces el precio a 12 meses quedó "
            f"entre {_x(band['p10'])}x y {_x(band['p90'])}x este valor (mediana {_x(band['p50'])}x). "
            "Es un punto de partida con mucho margen de error, no un precio objetivo."
        ),
        "message_en": (
            f"Method track record: in the backtest, 8 times out of 10 the price 12 months later was "
            f"between {band['p10']:.2f}x and {band['p90']:.2f}x this value (median {band['p50']:.2f}x). "
            "A starting point with a wide margin of error, not a price target."
        ),
    }
