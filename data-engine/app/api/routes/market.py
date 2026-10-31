"""Market indices endpoint: real index/futures/crypto quotes via Yahoo Finance.

Fuente: Yahoo Finance chart API (gratuita, sin key) con User-Agent de navegador.
Cache en memoria de 60s para no golpear Yahoo en cada carga de la home.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services import market_change, market_themes, movers_cache
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

# Un solo cliente HTTP para /quote y /candles: antes cada fallo de caché abría
# un httpx.Client nuevo (DNS + TCP + TLS a Yahoo en cada petición). httpx.Client
# es seguro entre hilos, y las rutas síncronas corren en el threadpool.
# Timeouts: conectar 5 s (Yahoo caído no bloquea un hilo 15 s solo en el
# handshake), esperar un hueco del pool 5 s, lectura 15 s (quote) / 20 s (velas).
_YAHOO_QUOTE_TIMEOUT = httpx.Timeout(15.0, connect=5.0, pool=5.0)
_YAHOO_CANDLES_TIMEOUT = httpx.Timeout(20.0, connect=5.0, pool=5.0)
_YAHOO_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0)
_yahoo_client: httpx.Client | None = None
_yahoo_client_lock = threading.Lock()


def _shared_yahoo_client() -> httpx.Client:
    """Cliente Yahoo compartido (keep-alive); se recrea si alguien lo cerró."""
    global _yahoo_client
    with _yahoo_client_lock:
        if _yahoo_client is None or _yahoo_client.is_closed:
            _yahoo_client = httpx.Client(
                headers=dict(_HEADERS), timeout=_YAHOO_QUOTE_TIMEOUT, limits=_YAHOO_LIMITS
            )
        return _yahoo_client


def close_shared_yahoo_client() -> None:
    """Cierra el cliente compartido (apagado del proceso y tests)."""
    global _yahoo_client
    with _yahoo_client_lock:
        if _yahoo_client is not None:
            _yahoo_client.close()
        _yahoo_client = None

# La conversión de clases US punto->guion (BRK.B -> BRK-B) vive en el
# conector Yahoo (fuente única); aquí se reexporta con el nombre histórico.
from app.services.connectors.yahoo import yahoo_chart_symbol as _yahoo_chart_symbol

logger = logging.getLogger(__name__)


def _bar_in_open_session(meta: dict, bar_ts, *, now_ts: float | None = None) -> bool:
    """True si la barra pertenece a la sesion regular en curso (aun sin cierre)."""
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = period.get("start"), period.get("end")
    if not all(isinstance(v, (int, float)) for v in (start, end, bar_ts)):
        return False
    now_ts = time.time() if now_ts is None else now_ts
    return start <= now_ts < end and bar_ts >= start


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
            timeout=_YAHOO_QUOTE_TIMEOUT,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        result = resp.json()["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes_raw = quote["close"]
        # Tras el cierre Yahoo tarda horas en rellenar `close` de la vela del
        # dia (llega None) aunque meta.regularMarketPrice ya es el cierre
        # (medido 27-oct-2026 20:14 ET: AAPL servia el cierre del 26 con
        # cd=26 teniendo regularMarketPrice=347.1 de las 20:00 ET). Solo si
        # el sello del propio proveedor (regularMarketTime) es posterior al fin
        # de la sesion regular de esa vela, esa vela se da por cerrada.
        _meta0 = result.get("meta") or {}
        _stamps0 = result.get("timestamp") or []
        _reg = ((_meta0.get("currentTradingPeriod") or {}).get("regular")) or {}
        _rmt, _rmp = _meta0.get("regularMarketTime"), _meta0.get("regularMarketPrice")
        if (
            closes_raw
            and closes_raw[-1] is None
            and len(_stamps0) == len(closes_raw)
            and all(isinstance(v, (int, float)) for v in (_reg.get("start"), _reg.get("end"), _rmt))
            and isinstance(_rmp, (int, float)) and _rmp > 0
            and _reg["start"] <= _stamps0[-1] < _reg["end"]
            and _rmt >= _reg["end"]
        ):
            closes_raw = list(closes_raw)
            closes_raw[-1] = float(_rmp)
        # Indice de la ultima vela con cierre no nulo: al filtrar el array se
        # pierde la alineacion con result["timestamp"], y la fecha honesta de
        # "c" es la de SU vela (desbloquea el etiquetado de ultimo cierre,
        # F358). Velas colgantes en None (dia en curso sin cierre) no mueven
        # la fecha al futuro.
        last_idx = next(
            (i for i in range(len(closes_raw) - 1, -1, -1) if closes_raw[i] is not None),
            None,
        )
        meta = result.get("meta") or {}
        # La barra de la sesion EN CURSO es provisional (Yahoo la rellena con el
        # ultimo precio): no es un cierre. Se descarta para que "c"/"cd" sean
        # el ultimo cierre oficial (medido 19-oct-2026: CGEO.L daba 4.205 con
        # fecha 19-oct a mitad de sesion LSE; el cierre oficial era 4.255 del 16).
        stamps_raw = result.get("timestamp") or []
        last_bar_ts = stamps_raw[last_idx] if last_idx is not None and last_idx < len(stamps_raw) else None
        if last_idx is not None and _bar_in_open_session(meta, last_bar_ts):
            closes_raw = list(closes_raw)[:last_idx]
            last_idx = next(
                (i for i in range(len(closes_raw) - 1, -1, -1) if closes_raw[i] is not None),
                None,
            )
        closes = [value for value in closes_raw if value is not None]
        if last_idx is None or not closes or closes[-1] <= 0:
            return None
        last = float(closes[-1])
        # Cierre previo REAL o None: antes caia a `last` y la variacion salia
        # como 0,00 % inventado (sin cierre previo no hay variacion que dar).
        if len(closes) >= 2:
            previous = float(closes[-2])
        else:
            cpc = meta.get("chartPreviousClose")
            previous = float(cpc) if isinstance(cpc, (int, float)) and cpc > 0 else None
        if previous is not None and previous <= 0:
            previous = None
        # Todas las magnitudes deben pertenecer a la misma vela seleccionada;
        # no tomar el último OHLC provisional tras descartar su cierre.
        def selected_value(key):
            values = quote.get(key) or []
            value = values[last_idx] if last_idx < len(values) else None
            # Dato ausente -> None; antes se rellenaba con el cierre y el
            # rango del dia salia 0 (maxima = minima = apertura = cierre).
            return float(value) if value is not None else None

        change = (last - previous) if previous is not None else None
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
            "dp": (change / previous * 100) if change is not None else None,
            "h": selected_value("high"),
            "l": selected_value("low"),
            "o": selected_value("open"),
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
    # Un simbolo con caracteres de control ("%00") rompia la URL de Yahoo en
    # httpx (InvalidURL -> 500). Nunca hay cotizacion para eso: 404.
    if not normalized or not normalized.isprintable() or len(normalized) > 32:
        raise HTTPException(status_code=404, detail=ui_error(404, "no_quote_available").detail)
    now = time.monotonic()
    with _quote_cache_lock:
        cached = _quote_cache.get(normalized)
        if cached and now - cached["at"] < _QUOTE_CACHE_TTL:
            return cached["data"]
    data = _fetch_yahoo_quote(_shared_yahoo_client(), normalized)
    if not data:
        raise HTTPException(status_code=404, detail=ui_error(404, "no_quote_available").detail)
    with _quote_cache_lock:
        if len(_quote_cache) >= _QUOTE_CACHE_MAX:
            _quote_cache.clear()
        _quote_cache[normalized] = {"at": now, "data": data}
    return data


# --- Lote para el sondeo de oportunidades del Inicio ---------------------
# El Inicio probaba N candidatas con N fetches desde Vercel (cache en
# memoria de 45s por instancia serverless: cada instancia fria era un miss).
# El lote concentra la lectura en el backend con cache Redis compartida de
# 60s (MISMA frescura que la cache en memoria del single de arriba): una
# llamada por carga en vez de N, y los misses se comparten entre usuarios y
# workers de gunicorn. Redis caido -> fail-open al fetch directo.
_QUOTES_BATCH_MAX = 30
_QUOTE_REDIS_PREFIX = "cavaai:market:quote:"


def _quote_redis_key(symbol: str) -> str:
    return f"{_QUOTE_REDIS_PREFIX}{symbol}"


def _batch_redis_client():
    """Cliente Redis del cache layer (backoff interno); None si no disponible."""
    try:
        from app.core.cache import _redis_client

        return _redis_client()
    except Exception:  # noqa: BLE001 - cache best-effort
        return None


class MarketQuotesBatchIn(BaseModel):
    symbols: list[str]


def _normalize_batch_symbols(symbols: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in symbols:
        normalized = raw.strip().upper()
        # Misma regla que el single: nada de controles ni longitudes locas.
        if not normalized or not normalized.isprintable() or len(normalized) > 32:
            continue
        seen.setdefault(normalized)
    return list(seen)


@router.post("/quotes/batch")
def market_quotes_batch(body: MarketQuotesBatchIn) -> dict:
    """Cotizaciones por lote (shape Finnhub via Yahoo), cache Redis 60s.

    Respuesta por simbolo: payload o null (sin dato NUNCA es error global).
    """
    if len(body.symbols) > _QUOTES_BATCH_MAX:
        raise HTTPException(
            status_code=400,
            detail=ui_error(400, "quotes_batch_too_large").detail,
        )
    symbols = _normalize_batch_symbols(body.symbols)
    if not symbols:
        return {"quotes": {}}

    redis_client = _batch_redis_client()
    now = time.monotonic()
    quotes: dict[str, dict | None] = {}
    misses: list[str] = []
    for symbol in symbols:
        # L1: la cache en memoria del single (60s), misma frescura.
        with _quote_cache_lock:
            cached = _quote_cache.get(symbol)
        if cached and now - cached["at"] < _QUOTE_CACHE_TTL:
            quotes[symbol] = cached["data"]
            continue
        # L2: Redis compartida entre workers y usuarios.
        if redis_client is not None:
            try:
                raw = redis_client.get(_quote_redis_key(symbol))
                if raw:
                    quotes[symbol] = json.loads(raw)
                    continue
            except Exception:  # noqa: BLE001 - fail-open al fetch
                logger.warning("quote cache: lectura Redis fallo; fail-open al fetch", exc_info=True)
        misses.append(symbol)

    if misses:
        client = _shared_yahoo_client()
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(lambda s: _fetch_yahoo_quote(client, s), misses))
        for symbol, data in zip(misses, fetched):
            quotes[symbol] = data
            if not data:
                continue
            with _quote_cache_lock:
                if len(_quote_cache) >= _QUOTE_CACHE_MAX:
                    _quote_cache.clear()
                _quote_cache[symbol] = {"at": now, "data": data}
            if redis_client is not None:
                try:
                    redis_client.setex(
                        _quote_redis_key(symbol),
                        int(_QUOTE_CACHE_TTL),
                        json.dumps(data),
                    )
                except Exception:  # noqa: BLE001 - no cachear nunca rompe la lectura
                    logger.warning("quote cache: escritura Redis fallo; se sirve sin cache", exc_info=True)
    return {"quotes": quotes}


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
            timeout=_YAHOO_CANDLES_TIMEOUT,
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
        payload = {"s": "ok", "c": c, "t": t, "o": o, "h": h, "l": l, "v": v}
        # Divisa de ESTA misma respuesta de Yahoo (GBp en LSE, ZAc en JSE...): las
        # velas no la traen por fila, y sin ella la cabecera no puede probar la unidad.
        meta_currency = (result.get("meta") or {}).get("currency")
        if isinstance(meta_currency, str) and meta_currency.strip():
            payload["currency"] = meta_currency.strip()
        return payload
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
    if not normalized or not normalized.isprintable() or len(normalized) > 32 or to_ts <= from_ts:
        raise HTTPException(status_code=404, detail=ui_error(404, "no_candles_available").detail)
    interval = _YAHOO_INTERVAL_BY_RESOLUTION[resolution]
    # El rango exacto cambia en cada petición; se agrupa por hora de fin para
    # que el gráfico de la ficha (ventana de 1 año) comparta caché.
    cache_key = (normalized, interval, from_ts // 86400, to_ts // 3600)
    now = time.monotonic()
    with _candles_cache_lock:
        cached = _candles_cache.get(cache_key)
        if cached and now - cached["at"] < _CANDLES_CACHE_TTL:
            return cached["data"]
    data = _fetch_yahoo_candles(_shared_yahoo_client(), normalized, from_ts, to_ts, interval)
    if not data:
        raise HTTPException(status_code=404, detail=ui_error(404, "no_candles_available").detail)
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


_common_sessions = market_change.common_sessions


# Suelo de liquidez de los rankings de Movers (justificación completa en
# docs/features/MOVERS_LIQUIDITY_FILTER.md):
# - Cierre >= 5 en la divisa del valor: el umbral clásico de "penny stock"
#   (la SEC fija $5). Por debajo, unos céntimos de ruido producen un +30 %
#   que no es una oportunidad operable, y las microcaps copaban Subidas.
# - Negociación de la sesión (cierre × volumen) >= 1 000 000 en la divisa
#   del valor: por debajo, una orden pequeña ya mueve el precio.
# Volumen ausente = negociación no medible: el valor queda fuera de los
# rankings (nunca entra con un dato supuesto) y se cuenta en
# `excluded_illiquid`. El universo no se filtra, y /api/market/changes
# (watchlist) tampoco: la cartera del usuario necesita su variación aunque
# el valor sea ilíquido.
MIN_MOVERS_PRICE = 5.0
MIN_MOVERS_TURNOVER = 1_000_000.0


def _is_liquid_for_movers(mover: dict) -> bool:
    if mover["price"] is None or mover["price"] < MIN_MOVERS_PRICE:
        return False
    volume = mover["volume"]
    return volume is not None and mover["price"] * volume >= MIN_MOVERS_TURNOVER


@router.get("/movers")
def market_movers(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=25),
) -> dict:
    """Gainers/losers/más activas desde market_prices (cierres datados).

    Sin filas devuelve universo vacío, nunca KeyError ni 500. El cambio sale de
    `market_change.compute_session_changes`, la misma función que usan Mercado
    y watchlist. Los rankings solo admiten valores que superan el suelo de
    liquidez documentado arriba; el universo y sus exclusiones se declaran.
    El cálculo se cachea `movers_cache.TTL_SECONDS` y se invalida cuando
    `upsert_prices` escribe cierres."""
    # Cálculo de todo el universo cacheado (TTL corto + invalidación al
    # escribir cierres: ver app/services/movers_cache.py).
    movers, stale_excluded, session_day = movers_cache.get_or_compute(
        lambda: market_change.compute_session_changes(db)
    )
    if not movers:
        return {
            "as_of": None,
            "universe": 0,
            "session_date": None,
            "excluded_not_comparable": 0,
            "excluded_illiquid": 0,
            "liquidity_floor": {"min_price": MIN_MOVERS_PRICE, "min_turnover": MIN_MOVERS_TURNOVER},
            "last_registered_at": None,
            "gainers": [],
            "losers": [],
            "most_active": [],
        }
    as_of = max((m["date"] for m in movers if m["date"]), default=None)
    # Hora del último dato: el registro más reciente entre las filas del
    # universo (updated_at, ISO tz-aware; el max lexicográfico es seguro con
    # un formato ISO homogéneo de la misma columna).
    last_registered_at = max(
        (m["registered_at"] for m in movers if m["registered_at"]), default=None
    )
    with_change = [m for m in movers if m["change_pct"] is not None]
    liquid = [m for m in with_change if _is_liquid_for_movers(m)]
    excluded_illiquid = len(with_change) - len(liquid)
    gainers = sorted(liquid, key=lambda m: m["change_pct"], reverse=True)[:limit]
    losers = sorted(liquid, key=lambda m: m["change_pct"])[:limit]
    # "Mas activas" ordena por volumen REAL: sin dato de volumen no hay ranking,
    # y el mismo suelo de liquidez que en subidas/bajadas.
    with_volume = [
        m for m in movers if m["volume"] is not None and m["current"] and _is_liquid_for_movers(m)
    ]
    most_active = sorted(with_volume, key=lambda m: m["volume"], reverse=True)[:limit]
    return {
        "as_of": as_of,
        "universe": len(movers),
        "session_date": session_day.isoformat() if session_day else None,
        "excluded_not_comparable": stale_excluded,
        "excluded_illiquid": excluded_illiquid,
        "liquidity_floor": {"min_price": MIN_MOVERS_PRICE, "min_turnover": MIN_MOVERS_TURNOVER},
        "last_registered_at": last_registered_at,
        "gainers": gainers,
        "losers": losers,
        "most_active": most_active,
    }


@router.get("/changes")
def market_changes(
    tickers: str = Query(min_length=1, max_length=2000),
    db: Session = Depends(get_db),
) -> dict:
    """Variación diaria de tickers concretos con la misma fórmula que Movers.

    Un ticker sin cierres comparables devuelve change_pct null (la UI muestra
    N/D), nunca un valor de otra fuente."""
    wanted = {t.strip().upper() for t in tickers.split(",") if t.strip()}
    movers, _, session_day = market_change.compute_session_changes(db, tickers=wanted)
    items = {
        m["ticker"].upper(): {
            "price": m["price"],
            "currency": m["currency"],
            "change": round(m["price"] - m["previous_close"], 4)
            if m["previous_close"] is not None
            else None,
            "change_pct": m["change_pct"],
            "previous_close": m["previous_close"],
            "date": m["date"],
            "previous_date": m["previous_date"],
        }
        for m in movers
        if m["ticker"].upper() in wanted
    }
    return {
        "session_date": session_day.isoformat() if session_day else None,
        "items": items,
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
