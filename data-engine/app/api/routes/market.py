"""Market indices endpoint: real index/futures/crypto quotes via Yahoo Finance.

Fuente: Yahoo Finance chart API (gratuita, sin key) con User-Agent de navegador.
Cache en memoria de 60s para no golpear Yahoo en cada carga de la home.
"""
from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Company, MarketPrice
from app.services import market_themes
from app.services.provenance import SourceKind, coverage_for_age, provenance

router = APIRouter()

# F152: unidad explícita por serie. Los niveles de índice (^GSPC, ^IXIC) no
# son dólares - pintarlos como «7743,41 US$» era una unidad falsa. El front
# formatea según `unit`: "index" sin sufijo monetario, "usd" con US$.
_INDEXES = [
    {"symbol": "^GSPC", "name": "S&P 500", "unit": "index"},
    {"symbol": "^IXIC", "name": "Nasdaq Composite", "unit": "index"},
    {"symbol": "BTC-USD", "name": "Bitcoin", "unit": "usd"},
    {"symbol": "GC=F", "name": "Oro", "unit": "usd"},
    {"symbol": "SI=F", "name": "Plata", "unit": "usd"},
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_cache: dict = {"at": 0.0, "items": [], "fetched_at": None}
_CACHE_TTL = 60.0
_FETCH_MAX_WORKERS = 5
_cache_lock = threading.RLock()


def _fetch_index(client: httpx.Client, symbol: str) -> dict | None:
    try:
        resp = client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "5d", "interval": "1d"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        result = payload["chart"]["result"][0]
        raw_closes = result["indicators"]["quote"][0]["close"]
        valid = [(i, value) for i, value in enumerate(raw_closes) if value is not None]
        closes = [value for _, value in valid]
        if len(closes) < 2:
            return None
        last, previous = closes[-1], closes[-2]
        # Sin cierre previo REAL no hay variacion medible, y publicarla como
        # 0.00% afirma "hoy plano" sobre un dato inexistente. El tipo
        # MarketIndex declara changePercent como `number` (no null) en
        # lib/actions/market.actions.ts, asi que en vez de meter un null que
        # contradiria ese contrato la serie no se publica: el hueco sale por
        # `coverage` (partial/empty), que la UI ya declara como tal.
        if previous <= 0:
            return None
        change = last - previous
        timestamps = result.get("timestamp") or []
        last_idx = valid[-1][0]
        observed_at = timestamps[last_idx] if last_idx < len(timestamps) else None
        return {
            "symbol": symbol,
            "priceAsOf": observed_at,
            "price": round(float(last), 2),
            "change": round(float(change), 2),
            "changePercent": round((change / previous) * 100, 2),
        }
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None


_QUOTE_CACHE_TTL = 60.0
_QUOTE_CACHE_MAX = 512
_quote_cache: dict[str, dict] = {}
_quote_cache_lock = threading.RLock()

_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

# La conversión de clases US punto->guion (BRK.B -> BRK-B) vive en el
# conector Yahoo (fuente única); aquí se reexporta con el nombre histórico.
from app.services.connectors.yahoo import yahoo_chart_symbol as _yahoo_chart_symbol


def _fetch_yahoo_quote(client: httpx.Client, symbol: str) -> dict | None:
    """Cotización puntual via Yahoo chart API con shape Finnhub {c,d,dp,h,l,o,pc}.

    Yahoo es la única fuente gratuita sin key que cubre mercados no-US
    (IBEX .MC, .PA, .DE...); Finnhub free no los sirve. Devuelve None ante
    cualquier dato incompleto en lugar de inventar valores.
    """
    symbol = _yahoo_chart_symbol(symbol)
    try:
        resp = client.get(
            f"{_YAHOO_CHART_URL}/{symbol}",
            params={"range": "5d", "interval": "1d"},
            timeout=15,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        result = resp.json()["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes_raw = quote["close"]
        # Indice de la ultima vela con cierre no nulo: al filtrar el array se
        # pierde la alineacion con result["timestamp"], y la fecha honesta de
        # "c" es la de SU vela (desbloquea el etiquetado de ultimo cierre,
        # F358). Velas colgantes en None (dia en curso sin cierre) no mueven
        # la fecha al futuro.
        last_idx = next(
            (i for i in range(len(closes_raw) - 1, -1, -1) if closes_raw[i] is not None),
            None,
        )
        closes = [value for value in closes_raw if value is not None]
        if last_idx is None or not closes or closes[-1] <= 0:
            return None
        meta = result.get("meta") or {}
        last = float(closes[-1])
        previous = (
            float(closes[-2])
            if len(closes) >= 2
            else float(meta.get("chartPreviousClose") or last)
        )
        opens = [value for value in (quote.get("open") or []) if value is not None]
        highs = [value for value in (quote.get("high") or []) if value is not None]
        lows = [value for value in (quote.get("low") or []) if value is not None]
        change = last - previous
        timestamps = result.get("timestamp") or []
        candle_ts = timestamps[last_idx] if last_idx < len(timestamps) else None
        candle_date = None
        if isinstance(candle_ts, (int, float)):
            from datetime import datetime
            from zoneinfo import ZoneInfo

            # cd exige zona de mercado VALIDA: sin ella, una fecha UTC podria
            # ser el dia equivocado cerca de medianoche local, y una fecha
            # mal zonificada es peor que ninguna (fail closed: ct sigue
            # viajando, cd queda None).
            tz_name = meta.get("exchangeTimezoneName")
            tz = None
            if isinstance(tz_name, str) and tz_name:
                try:
                    tz = ZoneInfo(tz_name)
                except (KeyError, ValueError):
                    tz = None
            if tz is not None:
                candle_date = datetime.fromtimestamp(candle_ts, tz).date().isoformat()
        return {
            "c": last,
            # Preserve the daily candle contract; paper fills use timestamped spot only.
            "live_c": meta.get("regularMarketPrice"),
            "live_t": meta.get("regularMarketTime"),
            "currency": meta.get("currency"),
            "d": change,
            "dp": (change / previous * 100) if previous else 0.0,
            "h": float(highs[-1]) if highs else last,
            "l": float(lows[-1]) if lows else last,
            "o": float(opens[-1]) if opens else last,
            "pc": previous,
            # Fecha real de la vela que publica "c" (epoch y fecha ISO en la
            # zona del mercado); None si Yahoo no sirvio timestamps - nunca
            # se inventa.
            "ct": int(candle_ts) if isinstance(candle_ts, (int, float)) else None,
            "cd": candle_date,
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


@router.get("/quote/{symbol}")
def market_quote(symbol: str) -> dict:
    """Cotización puntual con shape Finnhub, fuente Yahoo Finance chart API.

    Revive el fallback del frontend (getStockQuote) para tickers que Finnhub
    free no cubre (IBEX .MC y otros mercados). Caché en memoria de 60s por
    símbolo para no golpear Yahoo en bucles (watchlist, overview).
    """
    normalized = symbol.strip().upper()
    if not normalized:
        raise HTTPException(status_code=404, detail="Sin cotización disponible")
    now = time.monotonic()
    with _quote_cache_lock:
        cached = _quote_cache.get(normalized)
        if cached and now - cached["at"] < _QUOTE_CACHE_TTL:
            return cached["data"]
    headers = dict(_HEADERS)
    with httpx.Client(headers=headers) as client:
        data = _fetch_yahoo_quote(client, normalized)
    if not data:
        raise HTTPException(status_code=404, detail="Sin cotización disponible")
    with _quote_cache_lock:
        if len(_quote_cache) >= _QUOTE_CACHE_MAX:
            _quote_cache.clear()
        _quote_cache[normalized] = {"at": now, "data": data}
    return data


_CANDLES_CACHE_TTL = 900.0
_CANDLES_CACHE_MAX = 128
_candles_cache: dict[tuple, dict] = {}
_candles_cache_lock = threading.RLock()

_YAHOO_INTERVAL_BY_RESOLUTION = {"D": "1d", "W": "1wk", "M": "1mo", "60": "60m"}


def _fetch_yahoo_candles(
    client: httpx.Client, symbol: str, from_ts: int, to_ts: int, interval: str
) -> dict | None:
    """Velas históricas vía Yahoo chart API con shape Finnhub {s,c,t,o,h,l,v}.

    Finnhub free no sirve /stock/candle para mercados no-US; Yahoo sí. Las
    posiciones con close null (huecos) se descartan en TODOS los arrays para
    mantener la alineación por índice que espera el frontend.
    """
    symbol = _yahoo_chart_symbol(symbol)
    try:
        resp = client.get(
            f"{_YAHOO_CHART_URL}/{symbol}",
            params={"period1": from_ts, "period2": to_ts, "interval": interval},
            timeout=20,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        result = resp.json()["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        closes_raw = quote["close"]
        opens_raw = quote.get("open") or []
        highs_raw = quote.get("high") or []
        lows_raw = quote.get("low") or []
        volumes_raw = quote.get("volume") or []
        t: list[int] = []
        c: list[float] = []
        o: list[float | None] = []
        h: list[float | None] = []
        l: list[float | None] = []
        v: list[float | None] = []
        def optional_value(values: list, index: int) -> float | None:
            if index >= len(values) or values[index] is None:
                return None
            try:
                value = float(values[index])
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None

        for index, close in enumerate(closes_raw):
            if close is None:
                continue
            close = float(close)
            t.append(int(timestamps[index]))
            c.append(close)
            o.append(optional_value(opens_raw, index))
            h.append(optional_value(highs_raw, index))
            l.append(optional_value(lows_raw, index))
            # F318: volumen desconocido = None (la UI muestra N/D y el
            # análisis técnico lo ignora), nunca un 0.0 fabricado que se
            # presenta como dato conocido y arrastra las medias a 0/0.
            v.append(optional_value(volumes_raw, index))
        if not c:
            return None
        return {"s": "ok", "c": c, "t": t, "o": o, "h": h, "l": l, "v": v}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


@router.get("/candles/{symbol}")
def market_candles(
    symbol: str,
    from_ts: int = Query(alias="from", ge=0),
    to_ts: int = Query(alias="to", ge=1),
    resolution: Literal["D", "W", "M", "60"] = "D",
) -> dict:
    """Velas históricas con shape Finnhub, fuente Yahoo Finance chart API.

    Fallback del frontend (getCandles) para mercados que Finnhub free no
    cubre (IBEX .MC y otros). Caché en memoria de 15 min por
    (símbolo, resolución, rango horario).
    """
    normalized = symbol.strip().upper()
    if not normalized or to_ts <= from_ts:
        raise HTTPException(status_code=404, detail="Sin velas disponibles")
    interval = _YAHOO_INTERVAL_BY_RESOLUTION[resolution]
    # El rango exacto cambia en cada petición; se agrupa por hora de fin para
    # que el gráfico de la ficha (ventana de 1 año) comparta caché.
    cache_key = (normalized, interval, from_ts // 86400, to_ts // 3600)
    now = time.monotonic()
    with _candles_cache_lock:
        cached = _candles_cache.get(cache_key)
        if cached and now - cached["at"] < _CANDLES_CACHE_TTL:
            return cached["data"]
    headers = dict(_HEADERS)
    with httpx.Client(headers=headers) as client:
        data = _fetch_yahoo_candles(client, normalized, from_ts, to_ts, interval)
    if not data:
        raise HTTPException(status_code=404, detail="Sin velas disponibles")
    with _candles_cache_lock:
        if len(_candles_cache) >= _CANDLES_CACHE_MAX:
            _candles_cache.clear()
        _candles_cache[cache_key] = {"at": now, "data": data}
    return data


@router.get("/indices")
def market_indices() -> dict:
    now = time.monotonic()
    with _cache_lock:
        cache_hit = now - _cache["at"] < _CACHE_TTL and bool(_cache["items"])
        items = list(_cache["items"]) if cache_hit else []
        fetched_at = _cache["fetched_at"] if cache_hit else None
    if not cache_hit:
        items = []
        headers = dict(_HEADERS)
        # Yahoo respeta mejor el UA completo; el proxy/rate limit es suave a 5 tickers.
        with httpx.Client(headers=headers) as client, ThreadPoolExecutor(
            max_workers=min(_FETCH_MAX_WORKERS, len(_INDEXES))
        ) as pool:
            futures = {
                pool.submit(_fetch_index, client, index["symbol"]): index
                for index in _INDEXES
            }
            for future, index in futures.items():
                quote = future.result()
                if quote:
                    items.append({**index, **quote})
        fetched_at = datetime.now(UTC)
        with _cache_lock:
            _cache["at"] = time.monotonic()
            _cache["items"] = list(items)
            _cache["fetched_at"] = fetched_at
    return {
        "source": "yahoo_finance",
        "as_of": time.time(),
        "indices": items,
        "provenance": provenance(
            "Yahoo Finance",
            SourceKind.UNOFFICIAL,
            source_url="https://finance.yahoo.com/",
            fetched_at=fetched_at,
            coverage=coverage_for_age(
                "yahoo_finance", fetched_at, partial=0 < len(items) < len(_INDEXES), empty=not items
            ),
            note="Fuente no oficial (agregador); no usar como precio autoritativo.",
        ),
    }


def _common_sessions(db: Session) -> tuple:
    """(ultima sesion comun, sesion anterior) de market_prices.

    Una fecha cuenta como sesion si es laborable y tiene cierres de al menos la
    mitad de la MEDIANA de empresas por fecha en las ultimas 10 fechas
    laborables. Con el maximo como referencia, una carga masiva puntual (1142
    empresas un dia, ~60-120 los siguientes) dejaba como unica sesion valida
    la de la carga y congelaba el ranking en una fecha vieja. Un cierre suelto
    de fin de semana o de un solo ticker tampoco define la sesion."""
    rows = db.execute(
        select(MarketPrice.date, func.count(func.distinct(MarketPrice.company_id)))
        .group_by(MarketPrice.date)
        .order_by(MarketPrice.date.desc())
        .limit(30)
    ).all()
    weekdays = [(day, count) for day, count in rows if day.weekday() < 5][:10]
    if not weekdays:
        return None, None
    counts = sorted(count for _, count in weekdays)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    threshold = median / 2
    sessions = [day for day, count in weekdays if count >= threshold]
    return (sessions[0] if sessions else None), (sessions[1] if len(sessions) > 1 else None)


@router.get("/movers")
def market_movers(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=25),
) -> dict:
    """Gainers/losers/más activas calculados desde market_prices local.

    Diseño frío-seguro: sin filas no hay KeyError ni 500 — se devuelve
    universo vacío y la UI lo muestra como estado honesto. El cambio se
    calcula entre los dos últimos cierres de cada compañía (nunca se asume
    caché caliente ni fechas globales).
    """
    # Ventana POR COMPAÑÍA: los dos últimos cierres de cada una, sin suelo
    # temporal global. Un corte global de N días expulsaba del universo a
    # cualquier compañía con el último cierre más viejo que la ventana, y a
    # otra con el último cierre dentro pero el anterior fuera le publicaba
    # precio con variación null: dos resultados distintos del mismo hueco de
    # datos. El contrato es "los dos últimos cierres de cada compañía".
    # Coste acotado por índice (uq company_id+date): un max() por compañía en
    # cada CTE y una lectura por clave; nunca un row_number sobre toda la
    # historia.
    latest_day = db.scalar(select(func.max(MarketPrice.date)))
    if latest_day is None:
        return {
            "as_of": None,
            "universe": 0,
            "gainers": [],
            "losers": [],
            "most_active": [],
        }
    latest_pairs = (
        select(
            MarketPrice.company_id.label("company_id"),
            func.max(MarketPrice.date).label("last_date"),
        )
        .group_by(MarketPrice.company_id)
        .cte("movers_latest")
    )
    previous_pairs = (
        select(
            MarketPrice.company_id.label("company_id"),
            func.max(MarketPrice.date).label("prev_date"),
        )
        .join(
            latest_pairs,
            and_(
                MarketPrice.company_id == latest_pairs.c.company_id,
                MarketPrice.date < latest_pairs.c.last_date,
            ),
        )
        .group_by(MarketPrice.company_id)
        .cte("movers_previous")
    )

    def _rows_at(pair_cte, date_column) -> list:
        return list(
            db.execute(
                select(
                    MarketPrice.company_id,
                    MarketPrice.date,
                    MarketPrice.close,
                    MarketPrice.volume,
                    MarketPrice.updated_at,
                    Company.ticker,
                    Company.name,
                    Company.sector,
                    Company.currency,
                )
                .join(
                    pair_cte,
                    and_(
                        MarketPrice.company_id == pair_cte.c.company_id,
                        MarketPrice.date == date_column,
                    ),
                )
                .join(Company, Company.id == MarketPrice.company_id)
            ).all()
        )

    def _entry(day, close, volume, registered, ticker, name, sector, currency) -> dict:
        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "currency": currency,
            "price": float(close or 0),
            # Volumen desconocido o 0 = None (la UI muestra N/D): una sesion
            # negociada no tiene volumen 0, es un dato ausente de la fuente.
            "volume": int(volume) if volume else None,
            "date": day.isoformat() if day else None,
            # Hora de observacion/registro (updated_at, tz-aware): dentro de
            # la misma sesion conviven filas refrescadas a distinta hora y la
            # fecha diaria sola no las distingue en el ranking.
            "registered_at": registered.isoformat() if registered else None,
        }

    latest: dict[int, dict] = {}
    for company_id, day, close, volume, registered, ticker, name, sector, currency in _rows_at(
        latest_pairs, latest_pairs.c.last_date
    ):
        latest[company_id] = _entry(day, close, volume, registered, ticker, name, sector, currency)
    previous: dict[int, dict] = {}
    for company_id, day, close, volume, registered, ticker, name, sector, currency in _rows_at(
        previous_pairs, previous_pairs.c.prev_date
    ):
        previous[company_id] = _entry(day, close, volume, registered, ticker, name, sector, currency)
    # Sesion comun: los rankings comparan manzanas con manzanas. Una fila solo
    # entra si su ultimo cierre es el de la ultima sesion comun Y su cierre
    # previo es el de la sesion inmediatamente anterior; con otro hueco, el
    # cambio seria de varios dias (o de una sesion vieja) presentado como el de
    # hoy (F9/F10). Las demas siguen en el universo, fuera de los rankings.
    session_day, prev_session_day = _common_sessions(db)
    movers = []
    stale_excluded = 0
    for company_id, last in latest.items():
        prev = previous.get(company_id)
        base = float(prev["price"]) if prev else 0.0
        current = session_day is not None and last["date"] == session_day.isoformat()
        comparable = (
            current
            and prev is not None
            and prev["date"] == (prev_session_day.isoformat() if prev_session_day else None)
        )
        # Sin cierre anterior no hay cambio medible: None (la UI muestra "—"),
        # nunca un 0.0% que aparenta un dato que no existe.
        change_pct = (
            round((last["price"] - base) / base * 100, 2) if base and comparable else None
        )
        if not current:
            stale_excluded += 1
        movers.append({**last, "change_pct": change_pct, "current": current})
    as_of = max(
        (entry["date"] for entry in latest.values() if entry["date"]),
        default=None,
    )
    with_change = [m for m in movers if m["change_pct"] is not None]
    gainers = sorted(with_change, key=lambda m: m["change_pct"], reverse=True)[:limit]
    losers = sorted(with_change, key=lambda m: m["change_pct"])[:limit]
    # "Mas activas" ordena por volumen REAL: las filas sin dato de volumen
    # no pueden coronarse ni hundirse en el ranking por un 0 inventado.
    with_volume = [m for m in movers if m["volume"] is not None and m["current"]]
    most_active = sorted(with_volume, key=lambda m: m["volume"], reverse=True)[:limit]
    return {
        "as_of": as_of,
        "universe": len(movers),
        "session_date": session_day.isoformat() if session_day else None,
        "excluded_not_comparable": stale_excluded,
        "gainers": gainers,
        "losers": losers,
        "most_active": most_active,
    }


_themes_cache = market_themes.ThemesCache()


def _compute_themes_payload() -> dict:
    now = datetime.now(UTC)
    # Desde mediados de diciembre del año anterior: cubre el ultimo cierre de ese año
    # (base del YTD) y el cierre de hace un mes con una sola descarga por simbolo.
    from_ts = int(datetime(now.year - 1, 12, 10, tzinfo=UTC).timestamp())
    to_ts = int(now.timestamp())
    with httpx.Client(headers=dict(_HEADERS)) as client:
        candles = market_themes.fetch_all(
            market_themes.all_symbols(),
            lambda symbol: _fetch_yahoo_candles(client, symbol, from_ts, to_ts, "1d"),
        )
    return market_themes.compute_themes(candles, generated_at=now)


@router.get("/themes")
def market_themes_ranking() -> dict:
    """Ranking de temas de mercado (cestas curadas, media simple, YTD y 1M)."""
    return market_themes.with_live_intraday(_themes_cache.get(_compute_themes_payload))
