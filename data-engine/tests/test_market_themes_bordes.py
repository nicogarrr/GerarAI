"""Bordes de ``app.services.market_themes``: entradas invalidas y cache.

Lo que cada test demuestra:
- ``_bars`` descarta pares con timestamp o cierre no parseables o fuera de
  rango (459-460) y ordena por fecha.
- ``_last_on_or_before`` recorre toda la lista cuando el limite cubre todas
  las barras (471, rama 471->476) y aplica el ``floor``.
- ``ThemesCache.get`` devuelve el valor aparecido bajo ``compute_lock`` con
  ``stale: False`` (681) sin llamar a ``compute``.
- Un refresco en segundo plano que lanza conserva el dato anterior y libera
  el candado (717-718).
- ``with_live_intraday`` con ``as_of`` no ISO devuelve el payload intacto
  (733-734).

Relojes fijados con constantes; ``compute`` doblado con boom cuando no debe
llamarse; sin red.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime

from app.services import market_themes as mt


def test_bars_descarta_pares_invalidos_y_ordena():
    candles = {
        "s": "ok",
        "t": [1700000000, "no-numero", 99999999999999999999, 1600000000],
        "c": [10.0, 20.0, 30.0, 5.5],
    }
    assert mt._bars(candles) == [
        (date(2020, 9, 13), 5.5),
        (date(2023, 11, 14), 10.0),
    ]


def test_last_on_or_before_recorre_toda_la_lista():
    barras = [(date(2026, 1, 1), 1.0), (date(2026, 2, 1), 2.0), (date(2026, 3, 1), 3.0)]
    assert mt._last_on_or_before(barras, date(2026, 3, 15)) == 3.0
    assert mt._last_on_or_before(barras, date(2026, 2, 15)) == 2.0
    assert mt._last_on_or_before(barras, date(2025, 12, 31)) is None
    assert mt._last_on_or_before(barras, date(2026, 3, 15), floor=date(2026, 3, 1)) == 3.0
    assert mt._last_on_or_before(barras, date(2026, 2, 15), floor=date(2026, 3, 1)) is None


def test_cache_doble_chequeo_bajo_compute_lock(monkeypatch):
    cache = mt.ThemesCache(ttl=100.0, clock=lambda: 1000.0)

    def aparece_valor(now):
        cache._value = {"symbols_with_data": 3, "status": "ok"}
        return None

    def boom():
        raise AssertionError("compute no debio llamarse")

    monkeypatch.setattr(cache, "_recent_failure", aparece_valor)
    assert cache.get(boom) == {"symbols_with_data": 3, "status": "ok", "stale": False}


def test_cache_refresco_fallido_conserva_el_dato_anterior():
    cache = mt.ThemesCache(ttl=10.0, clock=lambda: 1000.0)
    original = {"symbols_with_data": 1, "status": "ok", "tema": "x"}
    cache._value = original
    cache._at = 0.0

    def boom():
        raise ValueError("Yahoo caido")

    servido = cache.get(boom)
    assert servido == {**original, "stale": True}
    for _ in range(300):
        if not cache._refreshing:
            break
        time.sleep(0.01)
    assert cache._refreshing is False
    assert cache._value is original  # el fallo no piso el dato bueno


def test_with_live_intraday_fecha_invalida_devuelve_el_payload_intacto():
    payload = {"as_of": "no-es-fecha", "status": "ok"}
    assert mt.with_live_intraday(payload, datetime(2026, 10, 12, 20, 30, tzinfo=UTC)) == payload
