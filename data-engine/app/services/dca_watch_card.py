"""Tarjeta DCA de la watchlist: nivel por semana/mes/trimestre/año, racha, riesgo y «¿por qué?».

Idea de producto tomada de dcaoptimizer (chips por marco temporal, meses en la
zona, etiqueta de riesgo, movimiento desde el último cambio); el cálculo es el
motor PROPIO de GerarAI (``dca_signal_engine``) y los nombres y colores de
zona son los de GerarAI, sin cambios. La señal oficial (avisos, plan) sigue
siendo SOLO la mensual; semana, trimestre y año son la misma fórmula sobre
cierres de ese periodo, como contexto. Puro: sin DB ni red.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    ZONES,
    DailyBar,
    DcaParams,
    MonthlyVerdict,
    evaluate_series,
)

TIMEFRAMES: tuple[tuple[str, str, str], ...] = (
    ("week", "S", "Semanal"),
    ("month", "M", "Mensual"),
    ("quarter", "T", "Trimestral"),
    ("year", "A", "Anual"),
)

# Bandas de riesgo por volatilidad anualizada (mensual, 36 meses). 25 % es el
# corte de «poco volátil» medido en el backtest del plan (#4730).
RISK_LOW_VOL = 0.25
RISK_HIGH_VOL = 0.50
SHORT_HISTORY_MONTHS = 36


def _zone(level: int) -> dict:
    return {"level": level, **ZONES[level]}


def _streak(verdicts: Sequence[MonthlyVerdict]) -> int:
    """Periodos seguidos (incluido el último) con el mismo nivel que el último."""
    if not verdicts:
        return 0
    level = verdicts[-1].level
    count = 0
    for verdict in reversed(verdicts):
        if verdict.level != level:
            break
        count += 1
    return count


def _last_change(verdicts: Sequence[MonthlyVerdict]) -> dict | None:
    """El último mes CONFIRMADO con otro nivel antes de la racha actual, y el movimiento desde él."""
    if not verdicts:
        return None
    current = verdicts[-1]
    run = _streak(verdicts)
    for verdict in reversed(verdicts[: len(verdicts) - run]):
        if verdict.status != "confirmed":
            continue
        return {
            "from": _zone(verdict.level),
            "to": _zone(current.level),
            "period": verdict.period,
            "signal_date": verdict.signal_date.isoformat(),
            "close": verdict.close,
            "change": current.close / verdict.close - 1.0 if verdict.close else None,
        }
    return None


def _risk(last: MonthlyVerdict, *, pre_revenue: bool, stale: bool) -> dict:
    vol = last.metrics.get("vol")
    history = int(last.metrics.get("months_of_history") or 0)
    reasons: list[dict] = []
    if isinstance(vol, (int, float)):
        band = "low" if vol < RISK_LOW_VOL else ("high" if vol >= RISK_HIGH_VOL else "medium")
        reasons.append({"key": "volatility", "value": vol})
    else:
        band = "medium"
        reasons.append({"key": "volatility_unknown", "value": None})
    if pre_revenue:
        band = "high"
        reasons.append({"key": "pre_revenue", "value": None})
    if history < SHORT_HISTORY_MONTHS:
        if band == "low":
            band = "medium"
        reasons.append({"key": "short_history", "value": history})
    if stale:
        reasons.append({"key": "stale", "value": None})
    labels = {"low": "Riesgo bajo", "medium": "Riesgo medio", "high": "Riesgo alto"}
    return {"key": band, "label": labels[band], "reasons": reasons}


def _why(last: MonthlyVerdict, params: DcaParams) -> dict:
    m = last.metrics
    return {
        "signal": m.get("signal"),
        "binding": m.get("binding"),
        "close": last.close,
        "drawdown": m.get("drawdown"),
        "high": m.get("high"),
        "high_lookback_months": params.high_lookback_months,
        "dd_thresholds": list(params.dd_thresholds),
        "sma": m.get("sma"),
        "sma_months": m.get("sma_months_used"),
        "sma_gap": m.get("sma_gap"),
        "adj_gap": m.get("adj_gap"),
        "gap_thresholds": list(params.gap_thresholds),
        "vol": m.get("vol"),
        "vol_ratio": m.get("vol_ratio"),
        "vol_ref": params.vol_ref,
        "level_drawdown": m.get("level_drawdown"),
        "level_sma_gap": m.get("level_sma_gap"),
        "rsi": m.get("rsi"),
        "months_of_history": m.get("months_of_history"),
        "level_prices": dict(last.level_prices),
        "params_version": params.version,
    }


def build_watch_card(
    bars: Sequence[DailyBar],
    *,
    today: date,
    params: DcaParams = DEFAULT_PARAMS,
    pre_revenue: bool = False,
    stale: bool = False,
) -> dict:
    """Tarjeta completa a partir de las barras diarias asentadas (las de la señal diaria)."""
    monthly = evaluate_series(bars, params=params, today=today)
    timeframes = []
    for key, short, label in TIMEFRAMES:
        series = monthly if key == "month" else evaluate_series(bars, params=params, today=today, period=key)
        if not series:
            timeframes.append({"key": key, "short": short, "label": label, "available": False,
                               "reason": f"hacen falta {params.min_months} periodos de historia"})
            continue
        last = series[-1]
        timeframes.append({
            "key": key, "short": short, "label": label, "available": True,
            "zone": _zone(last.level), "status": last.status, "period": last.period,
            "streak": _streak(series),
        })
    if not monthly:
        return {"available": False, "reason": f"hacen falta {params.min_months} meses de historia",
                "timeframes": timeframes}
    last = monthly[-1]
    return {
        "available": True,
        "official_timeframe": "month",
        "current": {
            **_zone(last.level),
            "status": last.status,
            "period": last.period,
            "signal_date": last.signal_date.isoformat(),
            "close": last.close,
            "months_in_zone": _streak(monthly),
        },
        "timeframes": timeframes,
        "last_change": _last_change(monthly),
        "risk": _risk(last, pre_revenue=pre_revenue, stale=stale),
        "why": _why(last, params),
    }
