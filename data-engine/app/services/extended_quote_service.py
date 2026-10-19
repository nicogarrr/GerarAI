"""Read-only, timestamped Yahoo quotes. No database or stale-on-error fallback."""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.services.connectors.yahoo import YahooFinanceClient, yahoo_chart_symbol

SessionName = Literal["pre", "regular", "post", "cerrado"]
SOURCE = "Yahoo Finance (no oficial), retraso posible"

# Subunidades que Yahoo distingue solo por mayusculas/minusculas (mismo
# mapa que analyst_targets_service). Sin normalizar, "GBp" no pasa la
# validacion de divisa del frontend (/^[A-Z]{3}$/) y la cabecera de la
# ficha entera salia N/D pese a tener precio (CGEO.L, 19 oct 2026).
_SUBUNIT_CURRENCY = {"GBp": "GBX", "ZAc": "ZAC"}


def _display_currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    return _SUBUNIT_CURRENCY.get(raw) or raw


class ExtendedQuote(BaseModel):
    ticker: str
    status: Literal["available", "retrasado", "unavailable"] = "unavailable"
    session: SessionName = "cerrado"
    price_session: SessionName | None = None
    price: float | None = None
    timestamp: int | None = None
    currency: str | None = None
    source: str = SOURCE
    fetched_at: int
    trading_date: str | None = None
    previous_close: float | None = None
    previous_close_timestamp: int | None = None
    previous_close_date: str | None = None
    change: float | None = None
    change_percent: float | None = None
    regular_close: float | None = None
    regular_close_timestamp: int | None = None
    regular_close_date: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    metrics_timestamp: int | None = None
    metrics_session: str | None = None
    # "Ultimo cierre vs anterior" con cierres oficiales de nuestra BD (misma
    # regla que /api/market/changes). Solo con mercado cerrado y dos sesiones
    # comunes consecutivas; nunca se mezcla con el previous_close de Yahoo.
    close_change: float | None = None
    close_change_percent: float | None = None
    close_change_date: str | None = None
    close_change_previous_date: str | None = None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _epoch(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def parse_extended_chart(ticker: str, node: dict[str, Any], now: int, daily_node: dict[str, Any] | None = None) -> ExtendedQuote:
    meta = node.get("meta") or {}
    periods = meta.get("currentTradingPeriod") or {}
    bounds: dict[str, tuple[int, int]] = {}
    for name in ("pre", "regular", "post"):
        period = periods.get(name) or {}
        start, end = _epoch(period.get("start")), _epoch(period.get("end"))
        if start is not None and end is not None and end > start:
            bounds[name] = (start, end)
    # Without the exchange's real session bounds, do not guess market hours.
    if "regular" not in bounds:
        return ExtendedQuote(ticker=ticker, fetched_at=now)

    historical: dict[str, list[tuple[int, int]]] = {}
    # On weekends Yahoo may give currentTradingPeriod for the next session,
    # while tradingPeriods dates the returned Friday candles.
    for name in ("pre", "regular", "post"):
        groups = (node.get("meta", {}).get("tradingPeriods") or {}).get(name, [])
        historical[name] = []
        for group in groups:
            for period in group:
                start, end = _epoch(period.get("start")), _epoch(period.get("end"))
                if start is not None and end is not None and end > start:
                    historical[name].append((start, end))

    def session_at(ts: int) -> SessionName:
        for name in ("pre", "regular", "post"):
            intervals = ([bounds[name]] if name in bounds else []) + historical[name]
            if any(start <= ts < end for start, end in intervals):
                return name
        return "cerrado"

    session = session_at(now)
    result = ExtendedQuote(ticker=ticker, fetched_at=now, session=session, currency=_display_currency(meta.get("currency")))
    quotes = (node.get("indicators") or {}).get("quote") or []
    candles = quotes[0] if quotes else {}
    timestamps = node.get("timestamp") or []
    closes = candles.get("close") or []
    points: list[tuple[int, float, int]] = []
    for i, raw in enumerate(timestamps):
        ts = _epoch(raw)
        price = _number(closes[i]) if i < len(closes) else None
        if ts is not None and ts <= now and price is not None:
            points.append((ts, price, i))
    points.sort()
    regular = [p for p in points if session_at(p[0]) == "regular"]
    regular_indices = [
        (ts, i) for i, raw in enumerate(timestamps)
        if (ts := _epoch(raw)) is not None and ts <= now and session_at(ts) == "regular"
    ]
    regular_intervals = [bounds["regular"]] + historical["regular"]

    def is_regular_close(ts: int) -> bool:
        # The last 1m candle or the timestamped closing print, never an
        # arbitrary intraday meta price presented as a session close.
        return any(now >= end and end - 60 <= ts <= end + 60 for _, end in regular_intervals)

    close_candidates = [(ts, price) for ts, price, _ in regular if is_regular_close(ts)]
    regular_time = _epoch(meta.get("regularMarketTime"))
    regular_price = _number(meta.get("regularMarketPrice"))
    if regular_time and regular_time <= now and regular_price is not None and is_regular_close(regular_time):
        close_candidates.append((regular_time, regular_price))
    if close_candidates:
        result.regular_close_timestamp, result.regular_close = max(close_candidates)
    if session != "cerrado":
        selected = points[-1] if points else None
    else:
        closed_points = [p for p in points if session_at(p[0]) == "post" or (session_at(p[0]) == "regular" and is_regular_close(p[0]))]
        selected = closed_points[-1] if closed_points else None
        if result.regular_close_timestamp and (
            selected is None or result.regular_close_timestamp > selected[0]
        ):
            if result.regular_close is not None:
                selected = (result.regular_close_timestamp, result.regular_close, -1)
    if session == "regular":
        result.regular_close = None
        result.regular_close_timestamp = None
    if selected is None:
        return result
    result.timestamp, result.price = selected[0], selected[1]
    result.price_session = session_at(selected[0])
    if selected[2] == -1 and selected[0] == result.regular_close_timestamp:
        result.price_session = "regular"
    timezone = meta.get("exchangeTimezoneName")
    if not timezone:
        return ExtendedQuote(ticker=ticker, fetched_at=now, session=session)
    tz = ZoneInfo(timezone)
    result.trading_date = datetime.fromtimestamp(selected[0], tz).date().isoformat()
    result.status = "retrasado" if session != "cerrado" and now - selected[0] > 1200 else "available"
    result.previous_close = _number(meta.get("previousClose"))
    # Yahoo normally omits the previous close's date. Do not invent it from
    # yesterday (holidays) or assign the current candle's date to it.
    prev_ts = _epoch(meta.get("previousCloseTime"))
    if prev_ts and prev_ts < bounds["regular"][0]:
        result.previous_close_timestamp = prev_ts
    if session != "cerrado" and result.previous_close is not None:
        result.change = result.price - result.previous_close
        result.change_percent = result.change / result.previous_close * 100
    if regular_indices:
        regular_indices.sort()
        last_ts = regular_indices[-1][0]
        covered_period = next((
            (start, end) for start, end in regular_intervals if start <= last_ts < end
        ), None)
        # A complete list of the bars that happen to exist is not complete
        # session coverage. Reject missing opening minutes, internal gaps,
        # and missing tail minutes rather than claim daily extrema.
        covered = False
        if covered_period:
            start, end = covered_period
            expected_last = min(end - 60, max(start, (now // 60) * 60 - 60))
            covered = (
                regular_indices[0][0] == start
                and last_ts >= expected_last
                and all(b[0] - a[0] == 60 for a, b in zip(regular_indices, regular_indices[1:], strict=False))
            )

        def values(key: str) -> list[float]:
            series = candles.get(key) or []
            return [v for _, i in regular_indices if i < len(series) and (v := _number(series[i])) is not None]

        highs, lows = values("high"), values("low")
        # Incomplete OHLC series cannot establish a daily max/min/open.
        first_i = regular_indices[0][1]
        open_series = candles.get("open") or []
        result.open = (
            _number(open_series[first_i])
            if first_i < len(open_series) and any(regular_indices[0][0] == start for start, _ in [bounds["regular"]] + historical["regular"])
            else None
        )
        result.high = max(highs) if covered and len(highs) == len(regular_indices) else None
        result.low = min(lows) if covered and len(lows) == len(regular_indices) else None
        result.metrics_timestamp = regular_indices[-1][0]
        result.metrics_session = datetime.fromtimestamp(regular_indices[-1][0], tz).date().isoformat()
    # Yahoo's timestamped regular-market aggregates cover traded prices even
    # when minute bars omit zero-trade minutes or append a sub-minute print.
    # Never infer day extrema from incomplete candles. Require the metadata's
    # own regularMarketTime on this exchange session's date and coherent range.
    bounds_session_date = datetime.fromtimestamp(bounds["regular"][0], tz).date()
    session_date = bounds_session_date
    # Weekend/holiday: currentTradingPeriod already names the NEXT session,
    # but the candles and the metadata describe the LAST completed one
    # (Yahoo serves Friday's bars with Monday's bounds). Without reframing,
    # the previous close and the daily extrema stay N/D all weekend - the
    # date checks ran against the wrong session. BME (SAN.MC, TRE.MC) hits
    # this hard: its no-trade minutes come back null, so the candle audit
    # can never publish extrema and the dated metadata is the only source.
    future_bounds = bounds["regular"][0] > now
    if future_bounds and regular_indices:
        session_date = datetime.fromtimestamp(regular_indices[-1][0], tz).date()
    if result.regular_close_timestamp:
        result.regular_close_date = datetime.fromtimestamp(result.regular_close_timestamp, tz).date().isoformat()
    meta_date = datetime.fromtimestamp(regular_time, tz).date() if regular_time else None
    meta_live_session = regular_time is not None and bounds["regular"][0] <= regular_time <= now
    meta_last_completed = regular_time is not None and future_bounds and regular_time <= now
    if regular_time and meta_date == session_date and (meta_live_session or meta_last_completed):
        high = _number(meta.get("regularMarketDayHigh"))
        low = _number(meta.get("regularMarketDayLow"))
        if high is not None and low is not None and regular_price is not None and low <= regular_price <= high:
            result.high, result.low = high, low
            result.metrics_timestamp = regular_time
            result.metrics_session = session_date.isoformat()

    # A daily bar dates a session, not its exact closing second. Expose a
    # date-only field, and only when its raw close matches previousClose.
    # Never date it by calendar subtraction, current price or adjusted close.
    if result.previous_close_timestamp:
        result.previous_close_date = datetime.fromtimestamp(result.previous_close_timestamp, tz).date().isoformat()
    if daily_node:
        daily_meta = daily_node.get("meta") or {}
        if (daily_meta.get("symbol") == meta.get("symbol") == yahoo_chart_symbol(ticker)
                and daily_meta.get("currency") == meta.get("currency")
                and daily_meta.get("exchangeTimezoneName") == timezone
                and daily_meta.get("dataGranularity") == "1d"):
            daily_quotes = (daily_node.get("indicators") or {}).get("quote") or []
            daily_closes = (daily_quotes[0].get("close") or []) if daily_quotes else []
            dated = []
            for i, raw in enumerate(daily_node.get("timestamp") or []):
                ts = _epoch(raw)
                close = _number(daily_closes[i]) if i < len(daily_closes) else None
                if ts and ts <= now:
                    dated.append((ts, datetime.fromtimestamp(ts, tz).date(), close))
            # "Cierre anterior": la vela diaria mas reciente ANTERIOR a la
            # sesion mostrada cuyo cierre crudo coincide con previousClose.
            prior = [row for row in dated if row[1] < session_date]
            if prior:
                _, day, close = max(prior, key=lambda row: row[0])
                if (not result.previous_close_timestamp and close is not None
                        and result.previous_close is not None
                        and math.isclose(close, result.previous_close, rel_tol=1e-6, abs_tol=1e-5)):
                    result.previous_close_date = day.isoformat()
            # "Cierre regular": la ultima sesion completada (anterior a la
            # proxima sesion de los bounds, que en finde ya es la futura).
            # Durante sesion abierta esto es ayer, nunca el valor intradia
            # de hoy reetiquetado como cierre.
            completed = [row for row in dated if row[1] < bounds_session_date]
            if completed and result.regular_close is None:
                _, day, close = max(completed, key=lambda row: row[0])
                if close is not None:
                    result.regular_close, result.regular_close_date = close, day.isoformat()
            today = [row for row in dated if row[1] == session_date]
            daily_time = _epoch(daily_meta.get("regularMarketTime"))
            daily_price = _number(daily_meta.get("regularMarketPrice"))
            # Closed daily bar can include the real closing auction beyond the
            # last regular minute. Require dated post-end regular metadata and
            # matching daily raw close. Never promote an old intraday meta price.
            # El fin de sesion se mide contra la ULTIMA sesion completada
            # (bounds o historico), no contra los bounds: en fin de semana o
            # antes de la apertura los bounds ya son la PROXIMA sesion, asi
            # que `now >= bounds end` no se cumpliria nunca y quedaba como
            # falso cierre el ultimo tick intradia (ASML 17:29, pre-subasta:
            # 1.473,40 frente al cierre oficial de subasta 1.477,20).
            completed_ends = [end for _, end in regular_intervals if end <= now]
            session_end = max(completed_ends) if completed_ends else None
            if (today and session != "regular" and session_end is not None
                    and daily_time is not None
                    and session_end <= daily_time <= now
                    and datetime.fromtimestamp(daily_time, tz).date() == session_date):
                _, day, close = max(today, key=lambda row: row[0])
                if close is not None and daily_price is not None and math.isclose(close, daily_price, rel_tol=1e-6, abs_tol=1e-5):
                    result.regular_close, result.regular_close_date = close, day.isoformat()
                    result.regular_close_timestamp = None  # Date is known, exact close time is not.
                    if (result.session == "cerrado" and result.price_session == "regular"
                            and result.timestamp is not None and result.timestamp <= daily_time):
                        result.price, result.timestamp = daily_price, daily_time
                        result.trading_date = day.isoformat()
    # En premercado, la referencia de la variacion y del «Cierre anterior»
    # es el ultimo cierre completado. Cuando esta funcion ya lo verifico
    # (print de cierre o vela diaria fechada), manda sobre meta.previousClose:
    # Yahoo lo mantiene obsoleto tras el fin de semana (el jueves, un lunes
    # en premercado) y la cabecera restaba contra un cierre distinto del
    # «Cierre regular» fechado que pinta al lado (ASTS 19-oct: -$3.26 con
    # cierre 40,66 visible; el cambio real contra ese cierre era +$0.54).
    # En sesion regular y post previousClose ya viene fresco de la propia
    # sesion y no se toca. Si previousClose coincide con el cierre
    # verificado, solo se recalcula la variacion contra la referencia fechada.
    if (
        result.session == "pre"
        and result.price is not None
        and result.regular_close is not None
        and result.regular_close > 0
    ):
        if result.previous_close is None or not math.isclose(
            result.previous_close, result.regular_close, rel_tol=1e-6, abs_tol=1e-5
        ):
            result.previous_close = result.regular_close
            result.previous_close_timestamp = result.regular_close_timestamp
            result.previous_close_date = result.regular_close_date
        result.change = result.price - result.regular_close
        result.change_percent = result.change / result.regular_close * 100
    return result


class ExtendedQuoteService:
    def __init__(self) -> None:
        self.client = YahooFinanceClient()
        self.cache: dict[str, tuple[float, dict[str, Any], int, dict[str, Any] | None]] = {}

    async def get(self, ticker: str) -> ExtendedQuote:
        ticker = ticker.strip().upper()
        now = int(time.time())
        try:
            cached = self.cache.get(ticker)
            if cached and time.monotonic() - cached[0] < 60:
                node, daily = cached[1], cached[3]
            else:
                intraday, daily_result = await asyncio.gather(
                    self.client.extended_chart(ticker), asyncio.wait_for(self.client.recent_daily_chart(ticker), timeout=3),
                    return_exceptions=True,
                )
                if isinstance(intraday, BaseException):
                    raise intraday
                node = intraday
                daily = daily_result if isinstance(daily_result, dict) else None
                self.cache = {k: v for k, v in self.cache.items() if time.monotonic() - v[0] < 60}
                self.cache[ticker] = (time.monotonic(), node, int(time.time()), daily)
            # Reclassify each read: cached candles can cross sessions/stale limit.
            return parse_extended_chart(ticker, node, int(time.time()), daily).model_copy(
                update={"fetched_at": self.cache[ticker][2]}
            )
        except Exception:
            self.cache.pop(ticker, None)
            return ExtendedQuote(ticker=ticker, fetched_at=now)


extended_quote_service = ExtendedQuoteService()
