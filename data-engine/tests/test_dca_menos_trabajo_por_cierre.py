"""Senales DCA: menos trabajo por cierre diario, mismo resultado exacto.

Con 400 tickers x 5 anos (~520.000 cierres) la evaluacion formateaba la clave
del mes en CADA cierre, recalculaba los mismos logaritmos mensuales en cada mes
para su ventana de volatilidad y convertia cada cierre a float dos veces. Estos
tests comparan con las implementaciones de antes (copiadas aqui): meses,
volatilidades y veredictos tienen que ser IDENTICOS (==), no aproximados.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from app.services import dca_signal_engine as engine
from app.services.dca_signal_engine import DEFAULT_PARAMS, DailyBar, evaluate_series, monthly_closes


def _monthly_closes_antes(bars):
    months: dict[str, list[DailyBar]] = {}
    for bar in sorted(bars, key=lambda b: b.day):
        if bar.close is None or not math.isfinite(bar.close) or bar.close <= 0:
            continue
        months.setdefault(f"{bar.day.year:04d}-{bar.day.month:02d}", []).append(bar)
    out = []
    for key in sorted(months):
        items = months[key]
        lows = [
            b.low if (b.low is not None and math.isfinite(b.low) and b.low > 0) else b.close for b in items
        ]
        out.append((key, items[-1].day, float(items[-1].close), float(min(lows))))
    return out


def _trailing_vol_antes(closes, i, params):
    start = max(1, i - params.vol_lookback_months)
    rets = [math.log(closes[j] / closes[j - 1]) for j in range(start, i)]
    if len(rets) < max(2, params.vol_min_months):
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(12.0)


def _barras(seed: int, n: int, *, desordenadas: bool = False) -> list[DailyBar]:
    rnd = random.Random(seed)
    price = rnd.uniform(5, 500)
    bars = []
    day = date(2019, 1, 1) + timedelta(days=rnd.randrange(0, 60))
    for _ in range(n):
        day += timedelta(days=rnd.choice((1, 1, 1, 3)))
        price = max(0.5, price * (1 + rnd.gauss(0.0003, 0.02)))
        close: float = price
        roll = rnd.random()
        if roll < 0.01:
            close = 0.0
        elif roll < 0.015:
            close = float("nan")
        low = None if rnd.random() < 0.3 else price * rnd.uniform(0.95, 1.0)
        bars.append(DailyBar(day=day, close=close, low=low))
    if desordenadas:
        rnd.shuffle(bars)
    return bars


def test_monthly_closes_identico():
    for seed in range(30):
        bars = _barras(seed, random.Random(seed).randrange(0, 1500), desordenadas=seed % 3 == 0)
        assert monthly_closes(bars) == _monthly_closes_antes(bars)
    assert monthly_closes([]) == []


def test_trailing_vol_con_logaritmos_precalculados_identica():
    for seed in range(20):
        closes = [m[2] for m in _monthly_closes_antes(_barras(seed, 1600))]
        logs = [0.0] + [math.log(closes[j] / closes[j - 1]) for j in range(1, len(closes))]
        for i in range(len(closes)):
            antes = _trailing_vol_antes(closes, i, DEFAULT_PARAMS)
            assert engine._trailing_vol(closes, i, DEFAULT_PARAMS) == antes  # noqa: SLF001
            assert engine._trailing_vol(closes, i, DEFAULT_PARAMS, logs) == antes  # noqa: SLF001


def test_evaluate_series_identica_a_la_de_antes(monkeypatch):
    casos = [_barras(seed, 1300) for seed in range(12)]
    nuevos = [evaluate_series(bars, today=date(2026, 11, 2)) for bars in casos]
    monkeypatch.setattr(engine, "monthly_closes", _monthly_closes_antes)
    monkeypatch.setattr(
        engine,
        "_trailing_vol",
        lambda closes, i, params, log_returns=None: _trailing_vol_antes(closes, i, params),
    )
    antes = [evaluate_series(bars, today=date(2026, 11, 2)) for bars in casos]
    assert nuevos == antes
    assert any(nuevos)
