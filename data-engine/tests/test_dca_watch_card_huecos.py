"""Tarjeta DCA: «meses en zona» solo cuenta periodos OBSERVADOS seguidos.

Misma disciplina que ``zone_visits`` (#zone_visits del motor): si falta un mes
en el historico (valor suspendido, hueco del proveedor), lo que paso en ese mes
es desconocido y la racha no se une a traves del hueco.
"""

from __future__ import annotations

from datetime import date

from app.services.dca_signal_engine import DailyBar, evaluate_series
from app.services.dca_watch_card import build_watch_card


def _monthly(
    closes: list[float], start: date = date(2018, 1, 10), skip: set[int] | None = None
) -> list[DailyBar]:
    bars = []
    for i, c in enumerate(closes):
        if skip and i in skip:
            continue
        y, m = divmod(start.month - 1 + i, 12)
        bars.append(DailyBar(day=date(start.year + y, m + 1, 10), close=c))
    return bars


def _series_with_tail_drawdown() -> list[float]:
    # 40 meses al alza y luego una caida del 50 % que se queda abajo: 4X sostenido.
    up = [100.0 * 1.02**i for i in range(40)]
    return up + [up[-1] * 0.5] * 8


def test_sin_huecos_la_racha_cuenta_todos_los_meses_en_zona():
    bars = _monthly(_series_with_tail_drawdown())
    card = build_watch_card(bars, today=date(2030, 1, 1))
    monthly = evaluate_series(bars, today=date(2030, 1, 1))
    streak = 0
    for v in reversed(monthly):
        if v.level != monthly[-1].level:
            break
        streak += 1
    assert card["current"]["months_in_zone"] == streak


def test_un_mes_sin_precio_corta_la_racha():
    closes = _series_with_tail_drawdown()
    n = len(closes)
    hole = n - 3  # falta el antepenultimo mes
    bars = _monthly(closes, skip={hole})
    card = build_watch_card(bars, today=date(2030, 1, 1))
    # Solo los 2 meses observados despues del hueco estan probados en la zona.
    assert card["current"]["months_in_zone"] == 2
    month_tf = next(t for t in card["timeframes"] if t["key"] == "month")
    assert month_tf["streak"] == 2


def test_ultimo_cambio_es_de_otro_nivel_aunque_la_racha_corte_un_hueco():
    closes = _series_with_tail_drawdown()
    bars = _monthly(closes, skip={len(closes) - 3})
    card = build_watch_card(bars, today=date(2030, 1, 1))
    change = card["last_change"]
    assert change is not None
    assert change["from"]["level"] != change["to"]["level"]


def test_hueco_semanal_tambien_corta_la_racha():
    closes = _series_with_tail_drawdown()
    # Semanal: una barra por semana; quitamos una semana reciente.
    bars = []
    d0 = date(2024, 1, 1)
    from datetime import timedelta

    weekly = [c for c in closes for _ in range(2)]
    for i, c in enumerate(weekly):
        if i == len(weekly) - 3:
            continue
        bars.append(DailyBar(day=d0 + timedelta(weeks=i), close=c))
    card = build_watch_card(bars, today=date(2030, 1, 1))
    week = next(t for t in card["timeframes"] if t["key"] == "week")
    assert week["available"] and week["streak"] <= 2


def test_periodo_anterior_en_cambios_de_ano():
    from app.services.dca_watch_card import _previous_key

    assert _previous_key("2026-01", "month") == "2025-12"
    assert _previous_key("2026-Q1", "quarter") == "2025-Q4"
    assert _previous_key("2026", "year") == "2025"
    assert _previous_key("2021-W01", "week") == "2020-W53"
    assert _previous_key("2026-W01", "week") == "2025-W52"
