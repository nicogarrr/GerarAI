"""Motor DCA por niveles (1X-4X + recortes), determinista y sin look-ahead.

Inspirado en el marco publico de DCA Optimizer (zonas mensuales 1X/2X/3X/4X de
la aportacion base, mas Light/Strong Trim). Su algoritmo es propietario y no se
replica: esta es una formula PROPIA y transparente, calibrada con el backtest de
``scripts/dca_backtest.py`` (datos reales, walk-forward, validacion cruzada por
activos). Todo se calcula sobre cierres MENSUALES construidos con cierres
diarios asentados:

* El veredicto *confirmado* de un mes lo fija su ultimo cierre diario.
* El mes en curso es *forming*: usa el ultimo cierre asentado y puede cambiar.
* Cada mes solo ve datos hasta su propio cierre (sin look-ahead).

El modulo es puro (sin DB ni red) para poder testearlo y backtestearlo igual
que se ejecuta en produccion.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# Codigos de nivel. Compra: 1..4 (multiplo de la aportacion base). Recorte: -1/-2.
LEVEL_STRONG_TRIM = -2
LEVEL_LIGHT_TRIM = -1
BUY_LEVELS = (1, 2, 3, 4)

ZONES: dict[int, dict[str, str]] = {
    4: {"key": "4x", "label": "4X DCA", "zone": "Zona de compra extrema", "color": "#B400FF", "fg": "#FFFFFF"},
    3: {"key": "3x", "label": "3X DCA", "zone": "Zona de compra fuerte", "color": "#68F60F", "fg": "#000000"},
    2: {"key": "2x", "label": "2X DCA", "zone": "Zona de compra", "color": "#00AA78", "fg": "#FFFFFF"},
    1: {"key": "1x", "label": "1X DCA", "zone": "Zona de aportacion normal", "color": "#FFFFFF", "fg": "#000000"},
    LEVEL_LIGHT_TRIM: {"key": "light-trim", "label": "RECORTE LIGERO", "zone": "Zona de recorte ligero", "color": "#FF9F0A", "fg": "#000000"},
    LEVEL_STRONG_TRIM: {"key": "strong-trim", "label": "RECORTE FUERTE", "zone": "Zona de recorte fuerte", "color": "#FF193C", "fg": "#FFFFFF"},
}


@dataclass(frozen=True)
class DailyBar:
    day: date
    close: float
    low: float | None = None


@dataclass(frozen=True)
class DcaParams:
    """Umbrales de la formula. Valores por defecto = formula calibrada.

    ``signal`` elige la familia de la senal de compra:

    * ``"sma_gap"``: distancia del cierre mensual POR DEBAJO de su media simple
      de ``sma_months`` meses (``1 - cierre / SMA``; la SMA incluye el mes).
    * ``"drawdown"``: caida desde el maximo de cierres mensuales de
      ``high_lookback_months`` meses.

    Con ``sma_gap`` y menos de ``sma_months`` meses de historia (valores
    jovenes) se usa ``drawdown`` como respaldo declarado en ``metrics``.
    """

    signal: str = "sma_gap"
    sma_months: int = 30
    # Historia minima para la SMA larga: con menos de ``sma_months`` meses se
    # usa la media de los meses disponibles (>= este minimo). None = sma_months.
    sma_min_months: int | None = 12
    # Distancia bajo la SMA larga (ajustada por volatilidad) para 2X, 3X y 4X.
    gap_thresholds: tuple[float, float, float] = (0.0, 0.10, 0.20)
    # Ajuste por volatilidad: descuento_ajustado = gap / (vol / vol_ref) ** vol_beta.
    # vol = volatilidad anualizada de rentabilidades log mensuales HASTA EL MES
    # ANTERIOR (no depende del cierre del mes, asi el nivel sigue siendo un precio).
    vol_beta: float = 1.0
    vol_ref: float = 0.30
    vol_lookback_months: int = 36
    vol_min_months: int = 12
    vol_ratio_cap: float = 10.0
    # Por debajo de esta vol anualizada (serie plana, precio congelado o de
    # relleno) la vol no es fiable: no se ajusta el gap (vol_ratio = 1) en vez
    # de dividir por casi cero y fabricar un 4X.
    vol_min_reliable: float = 0.02
    # Sin 4X antes de N meses de historia (valores jovenes). None = sin limite.
    cap4_before_months: int | None = 24
    high_lookback_months: int = 36
    # Caida desde el maximo necesaria para 2X, 3X y 4X (1X es el nivel por defecto).
    dd_thresholds: tuple[float, float, float] = (0.15, 0.25, 0.40)
    # Recortes: extension sobre la SMA corta y RSI mensual.
    trim_sma_months: int = 12
    trim_light_gap: float = 0.80
    trim_strong_gap: float = 1.00
    trim_rsi_light: float = 0.0
    trim_rsi_strong: float = 75.0
    rsi_period: int = 14
    min_months: int = 12
    version: str = "nico-v1"


DEFAULT_PARAMS = DcaParams()

# Formula provisional anterior (SMA 40m sin ajuste de volatilidad). Se conserva
# para comparar y para los tests de regresion del backtest original.
NICO_V0_PARAMS = DcaParams(
    sma_months=40,
    sma_min_months=None,
    gap_thresholds=(0.0, 0.05, 0.10),
    vol_beta=0.0,
    cap4_before_months=None,
    trim_sma_months=10,
    trim_light_gap=0.25,
    trim_strong_gap=0.40,
    trim_rsi_light=75.0,
    trim_rsi_strong=85.0,
    version="nico-v0",
)


def _trailing_vol(closes: Sequence[float], i: int, params: DcaParams) -> float | None:
    """Vol anualizada de rentabilidades log mensuales de los meses ANTERIORES a i."""
    start = max(1, i - params.vol_lookback_months)
    rets = [math.log(closes[j] / closes[j - 1]) for j in range(start, i)]
    if len(rets) < max(2, params.vol_min_months):
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(12.0)


@dataclass(frozen=True)
class MonthlyVerdict:
    period: str  # YYYY-MM
    level: int
    status: str  # "confirmed" | "forming"
    signal_date: date  # fecha del cierre diario usado
    close: float
    metrics: dict[str, float | int | str | None] = field(default_factory=dict)
    # Precio de cierre a partir del cual se entraria en cada nivel de compra
    # (solo informativo; None si el nivel no se puede expresar como precio).
    level_prices: dict[str, float | None] = field(default_factory=dict)
    touched_level: int | None = None  # nivel maximo tocado por el minimo del mes

    @property
    def zone(self) -> dict[str, str]:
        return ZONES[self.level]

    def as_dict(self) -> dict:
        data = asdict(self)
        data["signal_date"] = self.signal_date.isoformat()
        data["zone"] = self.zone
        return data


def monthly_closes(bars: Iterable[DailyBar]) -> list[tuple[str, date, float, float]]:
    """Agrupa barras diarias en meses: (YYYY-MM, fecha ultimo cierre, cierre, minimo)."""
    months: dict[str, list[DailyBar]] = {}
    for bar in sorted(bars, key=lambda b: b.day):
        if bar.close is None or not math.isfinite(bar.close) or bar.close <= 0:
            continue
        months.setdefault(f"{bar.day.year:04d}-{bar.day.month:02d}", []).append(bar)
    out = []
    for key in sorted(months):
        items = months[key]
        lows = [b.low if (b.low is not None and math.isfinite(b.low) and b.low > 0) else b.close for b in items]
        out.append((key, items[-1].day, float(items[-1].close), float(min(lows))))
    return out


def _rsi_series(closes: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    out[period] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    for i in range(period + 1, len(closes)):
        avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
        avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def _sma(closes: Sequence[float], i: int, months: int) -> float | None:
    if months <= 0 or i + 1 < months:
        return None
    return sum(closes[i + 1 - months : i + 1]) / months


def _buy_level(dd: float, thresholds: Sequence[float]) -> int:
    level = 1
    for i, t in enumerate(thresholds):
        if dd >= t:
            level = i + 2
    return level


def evaluate_series(
    bars: Iterable[DailyBar],
    *,
    params: DcaParams = DEFAULT_PARAMS,
    today: date | None = None,
    month_complete: bool | None = None,
) -> list[MonthlyVerdict]:
    """Veredicto de cada mes con historia suficiente.

    El ultimo mes es ``forming`` salvo que ``month_complete`` diga lo contrario o
    ``today`` ya este en un mes posterior al de la ultima barra.
    """
    months = monthly_closes(bars)
    if not months:
        return []
    closes = [m[2] for m in months]
    rsi = _rsi_series(closes, params.rsi_period)
    verdicts: list[MonthlyVerdict] = []
    last_index = len(months) - 1
    if month_complete is None:
        if today is None:
            month_complete = False
        else:
            last_key = months[-1][0]
            month_complete = f"{today.year:04d}-{today.month:02d}" > last_key
    for i, (key, day, close, low) in enumerate(months):
        if i + 1 < params.min_months:
            continue
        prev_window = closes[max(0, i + 1 - params.high_lookback_months) : i]
        high = max([*prev_window, close])
        dd = 1.0 - close / high
        prev_high = max(prev_window) if prev_window else close
        min_sma = params.sma_min_months or params.sma_months
        n_sma = min(params.sma_months, i + 1)
        long_sma = _sma(closes, i, n_sma) if n_sma >= min_sma else None
        use_sma = params.signal == "sma_gap" and long_sma is not None
        signal_used = "sma_gap" if use_sma else "drawdown"
        long_gap = (1.0 - close / long_sma) if long_sma else None
        vol = _trailing_vol(closes, i, params) if params.vol_beta else None
        vol_ratio = 1.0
        if vol is not None:
            if vol >= params.vol_min_reliable:
                vol_ratio = min(max(vol / params.vol_ref, 1e-9), params.vol_ratio_cap)
        scale = vol_ratio**params.vol_beta if params.vol_beta else 1.0
        adj_gap = (long_gap / scale) if long_gap is not None else None
        if use_sma:
            assert adj_gap is not None
            level = _buy_level(adj_gap, params.gap_thresholds)
            # Cierre que activaria cada nivel: la SMA incluye ese mismo cierre y
            # la volatilidad solo usa meses anteriores, asi que es un precio exacto.
            prev_sum = sum(closes[i + 1 - n_sma : i])
            m = n_sma
            level_prices = {}
            for n, t in zip((2, 3, 4), params.gap_thresholds, strict=True):
                need = t * scale
                price = (1.0 - need) * prev_sum / (m - 1 + need) if need < 1.0 and (m - 1 + need) > 0 else None
                level_prices[f"{n}x"] = round(price, 6) if price and price > 0 else None
            low_sma = (prev_sum + low) / m
            touched = _buy_level((1.0 - low / low_sma) / scale, params.gap_thresholds)
        else:
            level = _buy_level(dd, params.dd_thresholds)
            # Con el maximo previo: si el mes cierra por encima, el maximo sube
            # con el y el nivel es 1X.
            level_prices = {
                f"{n}x": round(prev_high * (1.0 - t), 6)
                for n, t in zip((2, 3, 4), params.dd_thresholds, strict=True)
            }
            touched = _buy_level(1.0 - low / max(prev_high, low), params.dd_thresholds)
        trim_sma = _sma(closes, i, params.trim_sma_months)
        trim_gap = (close / trim_sma - 1.0) if trim_sma else None
        r = rsi[i]
        # Sin RSI todavia (historia corta) cuenta como 0: un umbral de RSI 0
        # no exige nada y uno positivo no se cumple.
        r_val = r if r is not None else 0.0
        if level == 1 and trim_gap is not None:
            if trim_gap >= params.trim_strong_gap and r_val >= params.trim_rsi_strong:
                level = LEVEL_STRONG_TRIM
            elif trim_gap >= params.trim_light_gap and r_val >= params.trim_rsi_light:
                level = LEVEL_LIGHT_TRIM
        if params.cap4_before_months and i + 1 < params.cap4_before_months:
            # Valor joven: 4X no existe todavia. Tampoco se muestra su precio ni
            # se dice que el minimo del mes "toco 4X".
            if level == 4:
                level = 3
            touched = min(touched, 3)
            if "4x" in level_prices:
                level_prices["4x"] = None
        verdicts.append(
            MonthlyVerdict(
                period=key,
                level=level,
                status="forming" if (i == last_index and not month_complete) else "confirmed",
                signal_date=day,
                close=close,
                metrics={
                    "signal": signal_used,
                    "drawdown": round(dd, 6),
                    "high": round(high, 6),
                    "sma": round(long_sma, 6) if long_sma else None,
                    "sma_gap": round(long_gap, 6) if long_gap is not None else None,
                    "sma_months_used": n_sma if long_sma else None,
                    "vol": round(vol, 6) if vol is not None else None,
                    "vol_ratio": round(vol_ratio, 6),
                    "adj_gap": round(adj_gap, 6) if adj_gap is not None else None,
                    "trim_sma_gap": round(trim_gap, 6) if trim_gap is not None else None,
                    "rsi": round(r, 4) if r is not None else None,
                    "months_of_history": i + 1,
                },
                level_prices=level_prices,
                touched_level=touched if touched > max(level, 1) else None,
            )
        )
    return verdicts


def current_verdict(
    bars: Iterable[DailyBar],
    *,
    params: DcaParams = DEFAULT_PARAMS,
    today: date | None = None,
) -> MonthlyVerdict | None:
    """Veredicto mas reciente (normalmente el del mes en formacion)."""
    series = evaluate_series(bars, params=params, today=today)
    return series[-1] if series else None


HIT_RATE_HORIZONS: tuple[int, ...] = (3, 6, 12, 24, 36)
HIT_RATE_GROUPS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("2x-4x", "Todos 2X–4X", (2, 3, 4)),
    ("4x", "4X DCA", (4,)),
    ("3x", "3X DCA", (3,)),
    ("2x", "2X DCA", (2,)),
)


def hit_rates(
    bars: Iterable[DailyBar],
    *,
    params: DcaParams = DEFAULT_PARAMS,
    today: date | None = None,
    horizons: Sequence[int] = HIT_RATE_HORIZONS,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """"¿Cuántas veces estaba más arriba?" por nivel de compra (histórico).

    Solo meses CONFIRMADOS: el veredicto de cada mes usa datos hasta su cierre
    (sin look-ahead) y el resultado a N meses usa el cierre del mes i+N, que
    también debe estar cerrado. El mes en formación no entra ni como señal ni
    como resultado. Por cada grupo y horizonte: meses con dato, % con cierre
    más alto y rentabilidad media del precio (sin dividendos si las barras no
    están ajustadas). Histórico e hipotético; no predice resultados.
    """
    series = [v for v in evaluate_series(bars, params=params, today=today) if v.status == "confirmed"]
    # ``start``/``end`` (YYYY-MM) acotan los meses CON SENAL; el resultado a N
    # meses puede caer despues de ``end`` si ese mes ya esta cerrado.
    index = {v.period: i for i, v in enumerate(series)}
    closes = [v.close for v in series]
    periods = [v.period for v in series]

    def _shift(period: str, n: int) -> str:
        y, m = int(period[:4]), int(period[5:7])
        total = y * 12 + (m - 1) + n
        return f"{total // 12:04d}-{total % 12 + 1:02d}"

    rows = []
    for key, label, levels in HIT_RATE_GROUPS:
        members = [
            i
            for i, v in enumerate(series)
            if v.level in levels and (start is None or v.period >= start) and (end is None or v.period <= end)
        ]
        cells = []
        for h in horizons:
            rets = []
            for i in members:
                j = index.get(_shift(periods[i], h))
                if j is None:
                    continue
                rets.append(closes[j] / closes[i] - 1.0)
            n = len(rets)
            cells.append(
                {
                    "horizon_months": h,
                    "months": n,
                    "pct_higher": round(sum(r > 0 for r in rets) / n, 6) if n else None,
                    "avg_return": round(sum(rets) / n, 6) if n else None,
                }
            )
        rows.append({"key": key, "label": label, "levels": list(levels), "signal_months": len(members), "cells": cells})
    in_range = [p for p in periods if (start is None or p >= start) and (end is None or p <= end)]
    return {
        "months_completed": len(in_range),
        "first_period": in_range[0] if in_range else None,
        "last_period": in_range[-1] if in_range else None,
        "horizons": list(horizons),
        "params_version": params.version,
        "rows": rows,
    }


# Niveles de compra que definen una «visita» a zona de oportunidad (2X-4X).
BUY_VISIT_LEVELS: tuple[int, ...] = (2, 3, 4)


def zone_visits(
    bars: Iterable[DailyBar],
    *,
    params: DcaParams = DEFAULT_PARAMS,
    today: date | None = None,
    levels: Sequence[int] = BUY_VISIT_LEVELS,
) -> dict:
    """Duración de las visitas a la zona de compra (2X-4X), en meses.

    Una visita es una racha maximal de meses CONFIRMADOS con nivel en
    ``levels``. Solo las visitas COMPLETADAS (cerradas por un mes confirmado
    fuera de la zona) entran en la media: la racha que llega al último mes
    confirmado sigue abierta, se declara aparte y no cuenta. El mes en
    formación no entra (misma disciplina sin look-ahead que ``hit_rates``).
    Histórico e hipotético; no predice resultados.
    """
    verdicts = evaluate_series(bars, params=params, today=today)
    series = [v for v in verdicts if v.status == "confirmed"]
    forming_period = (
        verdicts[-1].period if verdicts and verdicts[-1].status == "forming" else None
    )
    wanted = {int(level) for level in levels}
    empty = {
        "available": False,
        "reason": "sin meses confirmados",
        "levels": sorted(wanted),
        "months_completed": 0,
        "first_period": None,
        "last_period": None,
        "completed_visits": 0,
        "excluded_gap_visits": 0,
        "avg_months": None,
        "max_months": None,
        "visits": [],
        "open_visit_months": None,
        "params_version": params.version,
    }
    if not series:
        return empty
    def _next(period: str) -> str:
        y, m = int(period[:4]), int(period[5:7])
        return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"

    # Una racha solo demuestra meses OBSERVADOS consecutivos: si entre dos
    # meses de la visita falta un mes del historico (jun 2X, ago 2X), el hueco
    # es desconocido y la duracion no es comparable: la visita se EXCLUYE de
    # la media y se cuenta en ``excluded_gap_visits``; nunca se une a traves
    # del hueco. Igual para la visita abierta: con hueco no se declara largo.
    def _has_gap(start_i: int, end_i: int) -> bool:
        return any(
            _next(series[j].period) != series[j + 1].period
            for j in range(start_i, end_i)
        )

    visits: list[dict] = []
    excluded_gap = 0
    run_start: int | None = None
    for i, verdict in enumerate(series):
        if verdict.level in wanted:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            if _has_gap(run_start, i):  # incluye la adyacencia con el mes que cierra
                excluded_gap += 1
            else:
                visits.append({
                    "start": series[run_start].period,
                    "end": series[i - 1].period,
                    "months": i - run_start,
                })
            run_start = None
    if run_start is None:
        open_months = None
    else:
        # La racha abierta solo declara largo si llega CONTIGUA al mes en
        # formacion: con un mes ausente en medio (jun 2X, jul sin dato, ago
        # 2X en formacion) no se sabe si la visita sigue viva o se cerro en
        # el hueco, asi que se excluye igual que las completadas con gap.
        reaches_present = forming_period is None or _next(series[-1].period) == forming_period
        if _has_gap(run_start, len(series) - 1) or not reaches_present:
            open_months = None
            excluded_gap += 1
        else:
            open_months = len(series) - run_start
    lengths = [visit["months"] for visit in visits]
    avg = None
    if lengths:
        avg = float(
            (Decimal(sum(lengths)) / Decimal(len(lengths))).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        )
    return {
        "available": True,
        "reason": None,
        "levels": sorted(wanted),
        "months_completed": len(series),
        "first_period": series[0].period,
        "last_period": series[-1].period,
        "completed_visits": len(visits),
        "excluded_gap_visits": excluded_gap,
        "avg_months": avg,
        "max_months": max(lengths) if lengths else None,
        "visits": visits,
        "open_visit_months": open_months,
        "params_version": params.version,
    }
