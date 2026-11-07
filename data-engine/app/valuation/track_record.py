"""Fiabilidad histórica del DCF estándar: cuánto se ha alejado el precio del valor.

Medido, no supuesto (backtest gerarai-dcavalor1, 7-nov-2026): réplica point-in-time
del DCF estándar vigente (ventas TTM, caja con inversiones, WACC por banda de tamaño,
capex con tope de 5 años, cíclicas a margen medio), 377 empresas actuales del
S&P 500 sin financieras, inmobiliarias ni utilities, 11.490 valoraciones
trimestrales de 2015 a 2025 con un valor entre 0,2x y 5x el precio.

* Precio a 12 meses / valor calculado: p10 0,63x, mediana 1,65x, p90 3,69x
  (2015-20: 0,66 / 1,74 / 3,78; 2021-26: 0,59 / 1,54 / 3,56). Solo el 21 % quedó a
  menos de un 25 % del valor.
* «Infravalorada» (valor > precio) no anticipa ganar al S&P 500 a 12 meses: lo
  bate el 49 % de las veces, frente al 49 % del resto.
* Ordenar sí sirve algo a 24 meses: el quintil más barato según el método bate al
  más caro en +4,0 (2015-20) y +12,1 (2021-26) puntos de rentabilidad mediana
  frente al SPY.

Las cifras son del método, no de cada empresa, y no son un precio objetivo: dicen
cuánto pesar el número. Se adjuntan solo cuando el número sale del DCF estándar.
"""

from __future__ import annotations

from typing import Any

TRACK_RECORD_ENGINE = "standard_dcf"
#: Precio a 12 meses / valor calculado (percentiles 10, 50 y 90).
PRICE_TO_VALUE_12M = {"p10": 0.63, "p50": 1.65, "p90": 3.69}
WITHIN_25PCT_SHARE = 0.21
UNDERVALUED_BEAT_SPY_12M = 0.49
REST_BEAT_SPY_12M = 0.49
CHEAPEST_VS_DEAREST_QUINTILE_24M_PTS = {"2015_2020": 4.0, "2021_2026": 12.1}
SAMPLE_ES = (
    "réplica point-in-time del DCF estándar, 377 empresas del S&P 500 sin financieras, "
    "inmobiliarias ni utilities, 11.490 valoraciones trimestrales 2015–2025"
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
            f"entre {_x(band['p10'])}x y {_x(band['p90'])}x este valor (mediana {_x(band['p50'])}x; "
            "el método suele quedarse corto). Sirve para comparar empresas entre sí, sobre todo a "
            "2 años, no como precio objetivo."
        ),
        "message_en": (
            f"Method track record: in the backtest, 8 times out of 10 the price 12 months later was "
            f"between {band['p10']:.2f}x and {band['p90']:.2f}x this value (median {band['p50']:.2f}x; "
            "the method tends to come in low). Use it to compare companies, especially over 2 years, "
            "not as a price target."
        ),
    }
