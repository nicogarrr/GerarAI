"""Tarjeta DCA de la watchlist: nivel por semana/mes/trimestre/año, racha, riesgo y «¿por qué?».

Idea de producto tomada de dcaoptimizer (chips por marco temporal, meses en la
zona, etiqueta de riesgo, movimiento desde el último cambio); el cálculo es el
motor PROPIO de GerarAI (``dca_signal_engine``) y los nombres y colores de
zona son los de GerarAI, sin cambios. La señal oficial (avisos, plan) sigue
siendo SOLO la mensual; semana, trimestre y año son la misma fórmula sobre
cierres de ese periodo, como contexto. Puro: sin DB ni red.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

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

# Sesiones con precio en vivo (la de ahora o la del ultimo print). Con
# "cerrado" el ultimo cierre asentado ya es la verdad mas fresca: no se
# sustituye nada y no es un dato que falte.
LIVE_SESSIONS: tuple[str, ...] = ("pre", "regular", "post")

# Banda de cordura del precio actual frente al ultimo cierre asentado: una
# cotización que difiere mas de esto se descarta como dato erroneo (no se
# veta la tarjeta: sigue con cierres y avisa).
MAX_LIVE_DEVIATION = 0.30

# Mismo mapa de subunidades que extended_quote_service._SUBUNIT_CURRENCY: la
# historia diaria declara "GBp" crudo y la cotización extendida lo normaliza
# a "GBX"; sin normalizar ambos lados la comparación descartaría un precio
# correcto por falsa diferencia de divisa.
_SUBUNIT_CURRENCY = {"GBp": "GBX", "ZAc": "ZAC"}


def _norm_currency(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    return _SUBUNIT_CURRENCY.get(raw) or raw or None


def usable_current_price(
    *,
    status: str | None,
    session: str | None,
    price_session: str | None,
    price: float | None,
    timestamp: int | None,
    quote_currency: str | None,
    history_currency: str | None,
    last_settled_close: float | None,
    today: date,
    max_deviation: float = MAX_LIVE_DEVIATION,
) -> tuple[float | None, str | None]:
    """Precio actual apto para el periodo en formación, o por qué no.

    Devuelve ``(precio, None)`` usable o ``(None, motivo)``; el motivo es una
    clave estable para i18n (``unavailable``, ``closed``, ``no_price``,
    ``stale``, ``currency_mismatch``, ``out_of_band``). Nunca lanza: sin
    precio actual la tarjeta sigue con cierres y lo declara.
    """
    if status == "unavailable":
        return None, "unavailable"
    if session not in LIVE_SESSIONS:
        # Mercado cerrado: el cierre asentado es el dato mas fresco; no falta
        # nada y un print viejo de la ultima sesion no es un precio actual.
        return None, "closed"
    if price_session is not None and price_session not in LIVE_SESSIONS:
        # La sesion actual esta abierta pero el print seleccionado no es de
        # una sesion en vivo (p. ej. un punto fuera de horario): no es un
        # precio actual aunque la sesion diga "pre".
        return None, "closed"
    if price is None or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
        return None, "no_price"
    # ``today`` es la fecha de mercado (America/New_York) del llamante.
    if timestamp is None:
        return None, "stale"
    try:
        ts_date = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(ZoneInfo("America/New_York")).date()
    except (OverflowError, OSError, ValueError):
        # Epoch fuera de rango o invalido: mismo fallback que un print viejo.
        return None, "stale"
    if ts_date != today:
        return None, "stale"
    quote_ccy, history_ccy = _norm_currency(quote_currency), _norm_currency(history_currency)
    # Fail-closed: sin divisa declarada en cualquiera de los dos lados no se
    # puede descartar una falsa equivalencia (GBp vs GBP, etc.); fallback a
    # cierres.
    if not quote_ccy or not history_ccy or quote_ccy != history_ccy:
        return None, "currency_mismatch"
    if (
        last_settled_close is not None
        and math.isfinite(last_settled_close)
        and last_settled_close > 0
        and abs(price / last_settled_close - 1.0) > max_deviation
    ):
        return None, "out_of_band"
    return float(price), None

# Bandas de riesgo por volatilidad anualizada (mensual, 36 meses). 25 % es el
# corte de «poco volátil» medido en el backtest del plan (#4730).
RISK_LOW_VOL = 0.25
RISK_HIGH_VOL = 0.50
SHORT_HISTORY_MONTHS = 36


def _zone(level: int) -> dict:
    return {"level": level, **ZONES[level]}


def _previous_key(key: str, period: str) -> str:
    """Clave del periodo inmediatamente anterior (2026-11 -> 2026-10, 2026-W01 -> 2025-W52...)."""
    if period == "month":
        total = int(key[:4]) * 12 + int(key[5:7]) - 2
        return f"{total // 12:04d}-{total % 12 + 1:02d}"
    if period == "quarter":
        total = int(key[:4]) * 4 + int(key[6]) - 2
        return f"{total // 4:04d}-Q{total % 4 + 1}"
    if period == "year":
        return f"{int(key) - 1:04d}"
    if period == "week":
        monday = date.fromisocalendar(int(key[:4]), int(key[6:8]), 1)
        iso = (monday - timedelta(days=7)).isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    raise ValueError(f"periodo desconocido: {period!r}")


def _streak(verdicts: Sequence[MonthlyVerdict], period: str = "month") -> int:
    """Periodos OBSERVADOS seguidos (incluido el último) con el mismo nivel que el último.

    Como en ``zone_visits``: si falta un periodo en el historico (valor
    suspendido, hueco del proveedor), lo que paso en el es desconocido y la
    racha no se une a traves del hueco; solo cuenta lo que esta probado.
    """
    if not verdicts:
        return 0
    level = verdicts[-1].level
    count = 0
    expected: str | None = None
    for verdict in reversed(verdicts):
        if verdict.level != level or (expected is not None and verdict.period != expected):
            break
        count += 1
        expected = _previous_key(verdict.period, period)
    return count


def _last_change(verdicts: Sequence[MonthlyVerdict]) -> dict | None:
    """El último mes CONFIRMADO con otro nivel antes de la racha actual, y el movimiento desde él."""
    if not verdicts:
        return None
    current = verdicts[-1]
    run = _streak(verdicts)
    for verdict in reversed(verdicts[: len(verdicts) - run]):
        # Con un hueco la racha se corta sin cambio de nivel: el cambio es el
        # ultimo mes confirmado con OTRO nivel.
        if verdict.status != "confirmed" or verdict.level == current.level:
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
    current_price: float | None = None,
    live: dict | None = None,
) -> dict:
    """Tarjeta completa a partir de las barras diarias asentadas (las de la señal diaria).

    ``current_price`` (ya validado por ``usable_current_price`` y en la unidad
    de la serie) entra solo como cierre provisional del periodo en formación,
    etiquetado ``close_kind="live"``; ``live`` es el bloque descriptivo para
    la UI (precio real, sesión, hora) o el motivo de no usarlo.
    """
    monthly = evaluate_series(bars, params=params, today=today, current_price=current_price)
    timeframes = []
    for key, short, label in TIMEFRAMES:
        series = monthly if key == "month" else evaluate_series(bars, params=params, today=today, period=key, current_price=current_price)
        if not series:
            timeframes.append({"key": key, "short": short, "label": label, "available": False,
                               "reason": f"hacen falta {params.min_months} periodos de historia"})
            continue
        last = series[-1]
        timeframes.append({
            "key": key, "short": short, "label": label, "available": True,
            "zone": _zone(last.level), "status": last.status, "period": last.period,
            "streak": _streak(series, key),
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
            "close_kind": last.close_kind,
            "months_in_zone": _streak(monthly),
        },
        "timeframes": timeframes,
        "last_change": _last_change(monthly),
        "risk": _risk(last, pre_revenue=pre_revenue, stale=stale),
        "why": _why(last, params),
        "live": live,
    }
