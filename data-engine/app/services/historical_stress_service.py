"""Calendar-year historical stress, using daily Yahoo adjusted closes.

Current equity weights are a buy-and-hold scenario, NOT the user's realized
portfolio. No proxy, cash, FX or missing-position renormalization is used.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Position
from app.services.connectors.yahoo import YahooFinanceClient
from app.services.data_source_health import get_data_source_registry

_REGISTRY_KEY = "yahoo_finance"
from app.services.propicks_price_service import yahoo_symbol
from app.valuation.currency import normalize_currency

YEARS = (2008, 2020, 2022)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
# Fallos de proveedor en memoria corta y presupuesto total de la peticion: con
# Yahoo caido o lento no se repiten N peticiones en cada carga.
_FAILED_UNTIL: dict[str, float] = {}
FAILURE_TTL_SECONDS = 120.0
BUDGET_SECONDS = 25.0


async def load_history(ticker: str) -> dict[str, Any]:
    """Bounded daily chart; never fall back to unadjusted close."""
    cached = _CACHE.get(ticker)
    if cached and time.monotonic() - cached[0] < 21600:
        return cached[1]
    # Este servicio llama a Yahoo por HTTP propio (no pasa por el connector):
    # registra sus outcomes en el MISMO registry, o un CAPTCHA/bloqueo de Yahoo
    # quedaba invisible en /api/health/data-sources.
    registry = get_data_source_registry()
    started = time.perf_counter()
    url = f"{YahooFinanceClient.base_url}/{quote(ticker, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                headers=YahooFinanceClient.headers,
                params={
                    "period1": int(datetime(2007, 12, 1, tzinfo=UTC).timestamp()),
                    "period2": int(datetime.now(UTC).timestamp()),
                    "interval": "1d",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status not in (400, 404):  # 400/404: ticker inexistente, no la fuente
            reason = (
                f"HTTP {status}: rate limit o CAPTCHA probable" if status in (429, 999) else f"HTTP {status}"
            )
            registry.record_failure(_REGISTRY_KEY, reason)
        raise
    except httpx.TransportError as exc:
        registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    except ValueError:
        registry.record_failure(_REGISTRY_KEY, "respuesta no JSON (posible CAPTCHA o cambio de HTML)")
        raise
    registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    # A partir de aqui es dato por ticker (chart.error, serie incompleta):
    # no degrada la fuente.
    node = payload["chart"]["result"][0]
    timezone = ZoneInfo(node["meta"]["exchangeTimezoneName"])
    today = datetime.now(timezone).date()
    timestamps = node.get("timestamp", [])
    values = node.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    if len(timestamps) != len(values):
        raise ValueError("Incomplete adjusted-close series")
    prices = {}
    for stamp, value in zip(timestamps, values, strict=True):
        day = datetime.fromtimestamp(stamp, timezone).date()
        if day < today and value is not None and math.isfinite(float(value)) and value > 0:
            prices[day] = float(value)
    result = {
        "prices": prices,
        "source": "Yahoo Finance",
        "source_url": str(response.url),
        "fetched_at": datetime.now(UTC).isoformat(),
        "currency": node["meta"].get("currency"),
    }
    if len(_CACHE) >= 256:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[ticker] = (time.monotonic(), result)
    return result


def calculate_window(prices: dict[date, float], year: int) -> dict[str, Any]:
    """Baseline immediately before Jan 1; peak/trough only inside this window.

    Recovery = first observed adjusted close >= drawdown peak after trough.
    Recovery can occur during the year; censor at the last observed close.
    """
    start, end = date(year, 1, 1), date(year, 12, 31)
    base_days = sorted(d for d in prices if start - timedelta(days=7) <= d < start)
    window_days = sorted(d for d in prices if start <= d <= end)
    empty: dict[str, Any] = {"year": year, "status": "SIN_DATOS", "reason": "missing_history"}
    if not base_days or len(window_days) < 180 or (end - window_days[-1]).days > 7:
        return empty
    days = [base_days[-1], *window_days]
    if any((b - a).days > 7 for a, b in zip(days, days[1:])):
        return {**empty, "reason": "history_gaps"}
    if any(not math.isfinite(prices[d]) or prices[d] <= 0 for d in days):
        return empty
    peak_day = worst_peak = trough = days[0]
    max_dd = 0.0
    for day in days[1:]:
        if prices[day] > prices[peak_day]:
            peak_day = day
        dd = prices[day] / prices[peak_day] - 1
        if dd < max_dd:
            max_dd, worst_peak, trough = dd, peak_day, day
    recovery = None
    recovery_gap = False
    previous = trough
    for day in sorted(d for d in prices if d > trough):
        if (day - previous).days > 7:
            recovery_gap = True
            break
        if prices[day] >= prices[worst_peak]:
            recovery = day
            break
        previous = day
    if max_dd == 0:
        recovery = trough
    return {
        "year": year,
        "status": "calculated",
        "reason": None,
        "start_date": days[0].isoformat(),
        "end_date": days[-1].isoformat(),
        "observations": len(window_days),
        "return": prices[days[-1]] / prices[days[0]] - 1,
        "max_drawdown": max_dd,
        "peak_date": worst_peak.isoformat(),
        "trough_date": trough.isoformat(),
        "recovery_date": recovery.isoformat() if recovery else None,
        "recovery_days": (recovery - worst_peak).days if recovery else None,
        "recovery_status": "recovered" if recovery else "history_gaps" if recovery_gap else "not_recovered",
        "last_observation": max(prices).isoformat(),
    }


def _failed_windows(reason: str) -> list[dict[str, Any]]:
    return [{"year": year, "status": "SIN_DATOS", "reason": reason} for year in YEARS]


class HistoricalStressService:
    async def build(
        self, db: Session, *, ticker: str | None = None, budget_seconds: float = BUDGET_SECONDS
    ) -> dict[str, Any]:
        weights: dict[str, float] = {}
        missing_values: list[str] = []
        weight_dates: dict[str, str | None] = {}
        # Instrumento REAL por ticker: Yahoo resuelve el ticker pelado en la linea US
        # (ADR/gemelo); se pide yahoo_symbol(company) y se exige divisa coincidente.
        instruments: dict[str, dict[str, Any]] = {}
        if ticker:
            tickers = [ticker.upper()]
            known = db.scalars(select(Company).where(Company.ticker == ticker.upper())).first()
            if known is not None:
                instruments[tickers[0]] = {
                    "symbol": yahoo_symbol(known),
                    "currency": (known.currency or "").strip().upper() or None,
                }
            else:  # sin ficha de empresa: ticker pelado y divisa sin verificar (se declara)
                instruments[tickers[0]] = {"symbol": tickers[0], "currency": None}
        else:
            rows = db.execute(
                select(Position, Company).join(Company, Position.company_id == Company.id)
            ).all()
            values: dict[str, float] = {}
            currencies: set[str] = set()
            for position, company in rows:
                if not position.quantity:
                    continue
                if position.quantity < 0:
                    missing_values.append(company.ticker)
                    continue
                tick = company.ticker
                instruments[tick] = {
                    "symbol": yahoo_symbol(company),
                    "currency": (company.currency or "").strip().upper() or None,
                }
                weight_dates[tick] = position.as_of.isoformat() if position.as_of else None
                value = position.market_value_base
                if value is None or not math.isfinite(float(value)) or value <= 0:
                    missing_values.append(tick)
                else:
                    values[tick] = values.get(tick, 0.0) + float(value)
                    currencies.add(position.base_currency)
            if len(currencies) > 1:
                missing_values.extend(values)
            total = sum(values.values())
            weights = {tick: value / total for tick, value in values.items()} if total else {}
            tickers = sorted(set(values) | set(missing_values))
        semaphore = asyncio.Semaphore(4)

        async def fetch(tick: str) -> tuple[str, dict[str, Any]]:
            instrument = instruments.get(tick) or {"symbol": None, "currency": None}
            empty = {
                "prices": {},
                "source": "Yahoo Finance",
                "source_url": None,
                "fetched_at": datetime.now(UTC).isoformat(),
                "currency": None,
                "symbol": instrument["symbol"],
                "failure": None,
            }
            if instrument["symbol"] is None:
                return tick, {**empty, "failure": "no_safe_symbol"}
            if _FAILED_UNTIL.get(instrument["symbol"], 0.0) > time.monotonic():
                return tick, {**empty, "failure": "provider_error"}
            async with semaphore:
                try:
                    history = await load_history(instrument["symbol"])
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                    _FAILED_UNTIL[instrument["symbol"]] = time.monotonic() + FAILURE_TTL_SECONDS
                    return tick, {**empty, "failure": "provider_error"}
            expected = instrument["currency"]
            got = (history.get("currency") or "").strip().upper() or None
            # Misma divisa principal: GBX/GBp (peniques) y GBP son la misma linea
            # de Londres; el estres usa rendimientos, que no dependen de la escala.
            if expected and normalize_currency(got)[0] != normalize_currency(expected)[0]:
                # Otra linea de cotizacion u otro emisor: nunca un sustituto.
                return tick, {
                    **empty,
                    "source_url": history.get("source_url"),
                    "currency": got,
                    "failure": "currency_mismatch" if got else "currency_unverified",
                }
            return tick, {**history, "symbol": instrument["symbol"], "failure": None}

        tasks = {asyncio.ensure_future(fetch(tick)): tick for tick in tickers}
        histories: dict[str, dict[str, Any]] = {}
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=budget_seconds)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                tick, payload = task.result()
                histories[tick] = payload
        for tick in tickers:
            if tick not in histories:  # presupuesto agotado: parcial marcado, no inventado
                instrument = instruments.get(tick) or {"symbol": None, "currency": None}
                histories[tick] = {
                    "prices": {},
                    "source": "Yahoo Finance",
                    "source_url": None,
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "currency": None,
                    "symbol": instrument["symbol"],
                    "failure": "provider_error",
                }
        companies = [
            {
                "ticker": tick,
                "weight": weights.get(tick),
                "weight_as_of": weight_dates.get(tick),
                **{k: v for k, v in histories[tick].items() if k not in ("prices", "failure")},
                "history_failure": histories[tick]["failure"],
                "windows": (
                    _failed_windows(histories[tick]["failure"])
                    if histories[tick]["failure"]
                    else [calculate_window(histories[tick]["prices"], year) for year in YEARS]
                ),
            }
            for tick in tickers
        ]
        portfolio = []
        for year in YEARS:
            missing = [
                c["ticker"]
                for c in companies
                if next(w for w in c["windows"] if w["year"] == year)["status"] != "calculated"
            ]
            if missing or missing_values or not weights:
                portfolio.append(
                    {
                        "year": year,
                        "status": "SIN_DATOS",
                        "reason": "incomplete_portfolio",
                        "missing_tickers": sorted(set(missing + missing_values)),
                    }
                )
                continue
            start = date(year, 1, 1)
            common = set.intersection(*(set(histories[t]["prices"]) for t in weights))
            bases = sorted(d for d in common if start - timedelta(days=7) <= d < start)
            if not bases:
                portfolio.append({"year": year, "status": "SIN_DATOS", "reason": "history_gaps"})
                continue
            base = bases[-1]
            path: dict[date, float] = {
                d: float(
                    sum(
                        weights[t] * histories[t]["prices"][d] / histories[t]["prices"][base] for t in weights
                    )
                )
                for d in common
                if d >= base
            }
            portfolio.append(calculate_window(path, year))
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "company" if ticker else "portfolio",
            "data_kind": "observed" if ticker else "INFERIDO",
            "companies": companies,
            "portfolio": portfolio if not ticker else [],
            "methodology": "adjusted_close_calendar_year;current_equity_weights_buy_and_hold;local_currency;no_fx;no_cash;no_proxies",
            "weight_sources": "positions.market_value_base" if not ticker else None,
        }
