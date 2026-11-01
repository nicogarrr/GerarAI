"""Conector de Alpha Vantage para cotizaciones y datos fundamentales como fuente secundaria.

Fulfills: VAL-DATA-002
Expected Behavior:
- Alpha Vantage como fuente de respaldo (fallback) tras Yahoo Finance
- Control estricto de cuota para el nivel gratuito (free tier: 25 llamadas/día, 5 por minuto)
- Caché/dedup de respuestas para no quemar el presupuesto diario repitiendo llamadas
- Presupuesto diario persistente (Redis; degradado a memoria de proceso sin Redis)
- Degradación elegante: sin cuota se sirve caché o se lanza AlphaVantageQuotaExhausted;
  NUNCA se inventan datos
- Health checks (``quota_status``) que no gastan cuota (cero llamadas HTTP)
- Obtención de cotizaciones (`GLOBAL_QUOTE`) y fundamentales (`OVERVIEW`)
- Gestión de clave de API mediante variables de entorno (ALPHA_VANTAGE_API_KEY)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.connectors.base import get_with_retry
from app.services.data_source_health import get_data_source_registry

logger = logging.getLogger(__name__)

# Alpha Vantage Free Tier: 5 llamadas por minuto (mínimo 12.0s entre llamadas)
AV_MAX_REQUESTS_PER_MINUTE = 5.0
AV_MIN_INTERVAL_SECONDS = 60.0 / AV_MAX_REQUESTS_PER_MINUTE

# Free tier: 25 llamadas/día por clave (fuente: mensaje del propio proveedor,
# "Our standard API rate limit is 25 requests per day"). El contador es por
# clave, no por proceso: un deploy a media tarde NO puede reiniciarlo, así que
# vive en Redis. Sin Redis degrada a memoria de proceso (modo degradado:
# reiniciar el proceso reinicia el contador; el presupuesto real lo lleva el
# proveedor y su mensaje de cuota agotada también corta el día localmente).
AV_DAILY_LIMIT = 25

# TTLs de caché agresivos a propósito: con 25 req/día, repetir la misma
# llamada en minutos quema el día entero. Lo cacheado se devuelve etiquetado
# con `fetched_at` y `from_cache=True`: nunca se presenta como dato fresco
# (veracidad de datos por encima de todo).
AV_QUOTE_CACHE_TTL_SECONDS = 3600  # 1 h: cotizaciones
AV_OVERVIEW_CACHE_TTL_SECONDS = 86400  # 24 h: fundamentales cambian poco

_BUDGET_KEY_PREFIX = "cavaai:alpha-vantage:budget:day:"
_CACHE_KEY_PREFIX = "cavaai:alpha-vantage:cache:"
# 48 h: cubre el día en curso y la lectura del contador a primera hora del siguiente.
_BUDGET_KEY_TTL_SECONDS = 172800

# Reserva atómica entre workers: si el contador llegó al límite no se incrementa
# y la llamada queda rechazada SIN salir a la red (rechazos no gastan cuota).
_BUDGET_RESERVE_SCRIPT = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then
  return {0, used}
end
used = redis.call('INCR', KEYS[1])
if used == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2])) end
return {1, used}
"""


class AlphaVantageQuotaExhausted(RuntimeError):
    """Presupuesto diario de Alpha Vantage agotado (free tier: 25 req/día).

    Nunca se sustituye por datos inventados ni por una respuesta parcial: el
    llamante recibe esta excepción y degrada a caché o a otra fuente.
    """

    def __init__(self, message: str, *, used: int, limit: int, reset: str) -> None:
        super().__init__(message)
        self.used = used
        self.limit = limit
        self.reset = reset


def _parse_av_float(value: Any) -> float | None:
    """Float o None. Alpha Vantage serializa los huecos como la cadena "None":
    ``float("None")`` rompía la respuesta y ``or 0.0`` la convertía en un 0,0
    inventado. Dato que falta = None, nunca 0.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("none", "null", "n/a", "-"):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    # "NaN"/"Infinity" parsean como float pero no son un dato: fuera.
    if not math.isfinite(number):
        return None
    return number


def _parse_av_int(value: Any) -> int | None:
    number = _parse_av_float(value)
    return int(number) if number is not None else None


def _same_symbol(requested: str, returned: str) -> bool:
    """Comparación de símbolo tolerante solo a separador (. vs -): si Alpha
    Vantage responde con OTRA empresa (p.ej. truncar SAN.MC a SAN daba el ADR
    americano), no se sirve bajo ningún concepto."""
    norm = lambda s: s.upper().replace(".", "").replace("-", "")  # noqa: E731
    return norm(requested) == norm(returned)


def _is_daily_limit_message(text: str) -> bool:
    """Distingue el aviso de cuota DIARIA del de frecuencia POR MINUTO.

    Heurística (SUPUESTO): el mensaje de cuota diaria habla de "per day" sin
    mencionar el ritmo por minuto; los mensajes de frecuencia mencionan
    "per minute" (a veces junto a "per day" describiendo el plan, no el
    agotamiento). Solo el aviso diario marca el día como agotado.
    """
    t = text.lower()
    return "per day" in t and "per minute" not in t


class AlphaVantageRateLimiter:
    """Limitador de tasa en memoria por proceso para respetar los 5 req/min de Alpha Vantage."""

    def __init__(self, min_interval: float = AV_MIN_INTERVAL_SECONDS) -> None:
        self.min_interval = float(min_interval)
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def wait(self) -> None:
        with self._lock:
            while True:
                remaining = self._next_allowed_at - time.perf_counter()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.5))
            self._next_allowed_at = time.perf_counter() + self.min_interval

    async def wait_async(self) -> None:
        """Turno de tasa SIN bloquear el event loop.

        ``wait()`` duerme con ``time.sleep`` dentro del lock: correcto entre
        hilos, pero llamado desde código async congela TODO el event loop del
        proceso hasta 12 s por llamada (60s / 5 req-min). Aquí la espera es
        ``asyncio.sleep`` fuera del lock y el turno se recalcula al despertar.
        """
        while True:
            with self._lock:
                remaining = self._next_allowed_at - time.perf_counter()
                if remaining <= 0:
                    self._next_allowed_at = time.perf_counter() + self.min_interval
                    return
            await asyncio.sleep(min(remaining, 0.5))

    def reset(self) -> None:
        with self._lock:
            self._next_allowed_at = 0.0


_av_limiter = AlphaVantageRateLimiter()


class AlphaVantageDailyBudget:
    """Presupuesto diario persistente de llamadas a Alpha Vantage.

    La reserva cuenta llamadas INTENTADAS, incluidas las que fallan a nivel de
    red: el proveedor también las cuenta. Con Redis la reserva es atómica
    entre procesos (script Lua) y sobrevive deploys; sin Redis degrada a un
    contador por proceso (documentado arriba como modo degradado).
    """

    def __init__(
        self,
        limit: int = AV_DAILY_LIMIT,
        *,
        date_fn: Any = None,
        redis_client_fn: Any = None,
    ) -> None:
        if int(limit) <= 0:
            raise ValueError(f"limit debe ser > 0, recibido {limit}")
        self.limit = int(limit)
        self._date_fn: Any = date_fn or (lambda: datetime.now(UTC).date())
        # Inyectable en tests; por defecto el cliente compartido de app.core.cache
        # (fail-open: devuelve None sin REDIS_URL o durante el backoff).
        self._redis_client_fn = redis_client_fn
        self._lock = threading.Lock()
        self._memory_counts: dict[str, int] = {}
        # Días que el PROVEEDOR dijo agotados: corta en local aunque el
        # contador no hubiera llegado al límite (p.ej. contador reiniciado).
        self._exhausted_dates: set[str] = set()

    def _today(self) -> tuple[str, str]:
        day = self._date_fn().isoformat()
        return day, f"{_BUDGET_KEY_PREFIX}{day}"

    def _redis(self) -> Any:
        if self._redis_client_fn is not None:
            return self._redis_client_fn()
        from app.core.cache import _redis_client

        return _redis_client()

    def reserve(self) -> bool:
        """Reserva una llamada del día. False si el presupuesto está agotado."""
        day, key = self._today()
        if day in self._exhausted_dates:
            return False
        client = self._redis()
        if client is not None:
            try:
                allowed, _used = client.eval(
                    _BUDGET_RESERVE_SCRIPT, 1, key, self.limit, _BUDGET_KEY_TTL_SECONDS
                )
                return bool(allowed)
            except Exception as exc:  # noqa: BLE001 — degradar a memoria, nunca inventar cuota
                logger.warning(
                    "Alpha Vantage budget: Redis falló (%s); contador degradado a memoria de proceso",
                    type(exc).__name__,
                )
        with self._lock:
            used = self._memory_counts.get(day, 0)
            if used >= self.limit:
                return False
            self._memory_counts[day] = used + 1
            return True

    def mark_exhausted(self) -> None:
        """Marca el día como agotado porque el PROVEEDOR lo dijo en su respuesta."""
        day, key = self._today()
        self._exhausted_dates.add(day)
        client = self._redis()
        if client is not None:
            try:
                client.set(key, self.limit, ex=_BUDGET_KEY_TTL_SECONDS)
            except Exception:  # noqa: BLE001 — best-effort; la marca local ya corta
                logger.warning("No se pudo registrar el presupuesto diario en Redis; se usa la marca local", exc_info=True)
        with self._lock:
            self._memory_counts[day] = max(self._memory_counts.get(day, 0), self.limit)

    def used_today(self) -> int:
        day, key = self._today()
        client = self._redis()
        if client is not None:
            try:
                raw = client.get(key)
                if raw is not None:
                    return int(raw)
            except Exception:  # noqa: BLE001 — lectura degradada a memoria
                logger.warning("No se pudo leer el presupuesto diario de Redis; se degrada a memoria", exc_info=True)
        with self._lock:
            return self._memory_counts.get(day, 0)

    def status(self) -> dict[str, Any]:
        """Lectura local del presupuesto: NUNCA llama a Alpha Vantage."""
        day, _key = self._today()
        used = self.used_today()
        if day in self._exhausted_dates:
            used = max(used, self.limit)
        backend = "redis" if self._redis() is not None else "memory"
        return {
            "date": day,
            "limit": self.limit,
            "used": used,
            "remaining": max(0, self.limit - used),
            "backend": backend,
        }


def _cache_key(params: dict[str, Any]) -> str:
    """Clave determinista de caché/dedup a partir de los parámetros (sin apikey)."""
    return ":".join(f"{k}={params[k]}" for k in sorted(params))


class AlphaVantageClient:
    """Cliente HTTP asíncrono para Alpha Vantage.

    - Limitación de tasa (5 req/min) y reintentos acotados vía ``get_with_retry``.
    - Presupuesto diario persistente (25 req/día free tier): los rechazos por
      presupuesto NO salen a la red.
    - Caché de respuestas (memoria + Redis) y dedup de llamadas idénticas en
      vuelo: N peticiones concurrentes al mismo dato gastan 1 llamada.
    """

    name = "alpha_vantage"
    base_url = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        daily_limit: int | None = None,
        rate_limiter: AlphaVantageRateLimiter | None = None,
        budget: AlphaVantageDailyBudget | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")
        if budget is not None:
            self.budget = budget
        else:
            limit = daily_limit or int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", str(AV_DAILY_LIMIT)))
            self.budget = AlphaVantageDailyBudget(limit=limit)
        self._limiter = rate_limiter if rate_limiter is not None else _av_limiter
        # Caché en memoria: {clave: (expira_en_monotonic, sobre)}. Redis es el
        # nivel compartido entre procesos; la memoria cubre el caso sin Redis.
        self._mem_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._mem_cache_lock = threading.Lock()
        # Dedup single-flight: un asyncio.Lock por clave de petición en vuelo.
        self._flight_locks: dict[str, asyncio.Lock] = {}
        self._flight_locks_guard = threading.Lock()

    def configured(self) -> bool:
        """Indica si la clave de API está configurada en el entorno."""
        return bool(self.api_key)

    # ------------------------- caché de respuestas -------------------------

    def _redis_cache_client(self) -> Any:
        from app.core.cache import _redis_client

        return _redis_client()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        """Sobre cacheado {fetched_at, payload} o None. Fail-open ante errores."""
        now = time.monotonic()
        with self._mem_cache_lock:
            entry = self._mem_cache.get(key)
            if entry is not None:
                if entry[0] > now:
                    return dict(entry[1])
                del self._mem_cache[key]
        client = self._redis_cache_client()
        if client is not None:
            try:
                raw = client.get(_CACHE_KEY_PREFIX + key)
                if raw is not None:
                    envelope = json.loads(raw)
                    if isinstance(envelope, dict) and "payload" in envelope:
                        return envelope
            except Exception as exc:  # noqa: BLE001 — la caché nunca rompe la llamada
                logger.debug("Alpha Vantage cache: lectura Redis falló: %s", type(exc).__name__)
        return None

    def _cache_set(self, key: str, envelope: dict[str, Any], ttl: int) -> None:
        with self._mem_cache_lock:
            self._mem_cache[key] = (time.monotonic() + ttl, envelope)
        client = self._redis_cache_client()
        if client is not None:
            try:
                client.set(_CACHE_KEY_PREFIX + key, json.dumps(envelope, default=str), ex=ttl)
            except Exception as exc:  # noqa: BLE001 — la caché nunca rompe la llamada
                logger.debug("Alpha Vantage cache: escritura Redis falló: %s", type(exc).__name__)

    def _flight_lock(self, key: str) -> asyncio.Lock:
        with self._flight_locks_guard:
            lock = self._flight_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._flight_locks[key] = lock
            return lock

    # ----------------------------- peticiones -----------------------------

    async def _fetch(self, params: dict[str, Any], *, ttl: int) -> dict[str, Any]:
        """GET con caché, dedup en vuelo, presupuesto diario y control de tasa.

        Devuelve {data, fetched_at, from_cache}. La caché se consulta ANTES
        del presupuesto: con la cuota agotada se siguen sirviendo respuestas
        cacheadas (etiquetadas), nunca datos inventados.
        """
        if not self.configured():
            raise RuntimeError("Alpha Vantage no está configurado (falta ALPHA_VANTAGE_API_KEY)")

        key = _cache_key(params)
        cached = self._cache_get(key)
        if cached is not None:
            return {"data": cached["payload"], "fetched_at": cached["fetched_at"], "from_cache": True}

        lock = self._flight_lock(key)
        try:
            async with lock:
                # Segunda comprobación: quien esperaba el lock puede tener ya
                # la respuesta que el primero acaba de cachear (dedup).
                cached = self._cache_get(key)
                if cached is not None:
                    return {
                        "data": cached["payload"],
                        "fetched_at": cached["fetched_at"],
                        "from_cache": True,
                    }
                data = await self._fetch_network(params)
                envelope = {"fetched_at": datetime.now(UTC).isoformat(), "payload": data}
                self._cache_set(key, envelope, ttl)
                return {"data": data, "fetched_at": envelope["fetched_at"], "from_cache": False}
        finally:
            # Liberar la entrada del dict; los esperantes ya tienen el objeto.
            with self._flight_locks_guard:
                self._flight_locks.pop(key, None)

    def _quota_exhausted(self) -> AlphaVantageQuotaExhausted:
        status = self.budget.status()
        return AlphaVantageQuotaExhausted(
            "Alpha Vantage: presupuesto diario agotado "
            f"({status['used']}/{status['limit']} el {status['date']} UTC); "
            "se sirve caché si existe o se degrada a otra fuente",
            used=status["used"],
            limit=status["limit"],
            reset="00:00 UTC",
        )

    async def _fetch_network(self, params: dict[str, Any]) -> dict[str, Any]:
        """Llamada real con presupuesto y tasa aplicados a CADA intento.

        get_with_retry(max_retries=1) puede hacer 2 peticiones reales: reservar
        fuera del retry garantizaba 2 llamadas por unidad y el tope de 25/día
        dejaba de estar garantizado. Cada intento reserva su unidad (el
        proveedor la cuenta aunque falle) y espera su turno de tasa; si el
        presupuesto se agota entre intentos, el reintento NO sale a la red.
        """
        registry = get_data_source_registry()
        query_params = {**params, "apikey": self.api_key}

        async def _call() -> httpx.Response:
            if not self.budget.reserve():
                raise self._quota_exhausted()
            # Control de tasa (5 req/min), también por intento real; versión
            # async: la espera no congela el event loop del proceso.
            await self._limiter.wait_async()
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await client.get(self.base_url, params=query_params)

        started = time.perf_counter()
        try:
            response = await get_with_retry(_call, max_retries=1)
            data = response.json()
        except AlphaVantageQuotaExhausted:
            registry.record_failure(self.name, "presupuesto diario agotado (free tier)")
            raise
        except Exception as exc:
            registry.record_failure(self.name, type(exc).__name__)
            raise

        if isinstance(data, dict):
            # Alpha Vantage devuelve avisos de límite en JSON con status 200.
            # El de cuota DIARIA llega en "Information" (25 requests per day);
            # el de frecuencia por minuto en "Note".
            limit_note = data.get("Information") or data.get("Note")
            if limit_note and _is_daily_limit_message(str(limit_note)):
                self.budget.mark_exhausted()
                registry.record_failure(self.name, "cuota diaria agotada según el proveedor")
                status = self.budget.status()
                raise AlphaVantageQuotaExhausted(
                    f"Alpha Vantage: el proveedor agotó la cuota diaria: {limit_note}",
                    used=status["used"],
                    limit=status["limit"],
                    reset="00:00 UTC",
                )
            if "Note" in data:
                registry.record_failure(self.name, "rate limit por minuto")
                raise RuntimeError(f"Alpha Vantage rate limit reached: {data['Note']}")
            if "Information" in data:
                registry.record_failure(self.name, "rate limit por minuto")
                raise RuntimeError(f"Alpha Vantage rate limit reached: {data['Information']}")
            if "Error Message" in data:
                raise ValueError(f"Alpha Vantage error: {data['Error Message']}")

        registry.record_success(self.name, (time.perf_counter() - started) * 1000)
        return data if isinstance(data, dict) else {}

    # ---------------------------- health local -----------------------------

    def quota_status(self) -> dict[str, Any]:
        """Estado del presupuesto diario SIN llamar a Alpha Vantage.

        Health check de cuota: solo lee el contador local (Redis/memoria) y la
        configuración. Cero llamadas HTTP al proveedor, así que consultarlo en
        bucle no gasta ni una unidad del free tier.
        """
        status = self.budget.status()
        return {
            "configured": self.configured(),
            "allowed": self.configured() and status["remaining"] > 0,
            "date_utc": status["date"],
            "daily_limit": status["limit"],
            "used_today": status["used"],
            "remaining_today": status["remaining"],
            "budget_backend": status["backend"],
            "resets_at": "00:00 UTC",
        }

    # ------------------------------ endpoints ------------------------------

    async def quote(self, ticker: str) -> dict[str, Any]:
        """Obtiene la última cotización para un ticker (GLOBAL_QUOTE).

        El ticker se envía COMPLETO (con sufijo de mercado): truncar "SAN.MC"
        a "SAN" devolvía el ADR americano, otra empresa bajo otro precio. Si la
        respuesta trae un símbolo distinto se rechaza: nunca se sirve otra empresa.
        """
        clean_ticker = ticker.strip().upper()
        result = await self._fetch(
            {"function": "GLOBAL_QUOTE", "symbol": clean_ticker},
            ttl=AV_QUOTE_CACHE_TTL_SECONDS,
        )
        data = result["data"]
        quote_data = data.get("Global Quote", {})
        if not quote_data:
            raise RuntimeError(f"Alpha Vantage no devolvió cotización para {ticker}")
        returned_symbol = str(quote_data.get("01. symbol", "")).strip()
        if returned_symbol and not _same_symbol(clean_ticker, returned_symbol):
            raise RuntimeError(
                f"Alpha Vantage devolvió '{returned_symbol}' al pedir '{clean_ticker}': "
                "respuesta rechazada para no servir otra empresa"
            )

        price = _parse_av_float(quote_data.get("05. price"))
        if price is None:
            raise RuntimeError(f"Alpha Vantage devolvió cotización sin precio para {ticker}")

        return {
            "symbol": returned_symbol or clean_ticker,
            "price": price,
            "volume": _parse_av_int(quote_data.get("06. volume")),
            "latest_trading_day": quote_data.get("07. latest trading day", ""),
            "previous_close": _parse_av_float(quote_data.get("08. previous close")),
            "change": _parse_av_float(quote_data.get("09. change")),
            "change_percent": quote_data.get("10. change percent", "0%"),
            "source": self.name,
            "fetched_at": result["fetched_at"],
            "from_cache": result["from_cache"],
        }

    async def overview(self, ticker: str) -> dict[str, Any]:
        """Obtiene datos fundamentales y métricas clave de la empresa (OVERVIEW).

        Ticker completo (sin truncar sufijo) y métricas None cuando faltan:
        Alpha Vantage las manda como la cadena "None" y convertirlas a 0.0
        inventaba un PER o un market cap de cero.
        """
        clean_ticker = ticker.strip().upper()
        result = await self._fetch(
            {"function": "OVERVIEW", "symbol": clean_ticker},
            ttl=AV_OVERVIEW_CACHE_TTL_SECONDS,
        )
        data = result["data"]
        if not data or "Symbol" not in data:
            raise RuntimeError(f"Alpha Vantage no devolvió datos fundamentales para {ticker}")
        returned_symbol = str(data.get("Symbol", "")).strip()
        if returned_symbol and not _same_symbol(clean_ticker, returned_symbol):
            raise RuntimeError(
                f"Alpha Vantage devolvió '{returned_symbol}' al pedir '{clean_ticker}': "
                "respuesta rechazada para no servir otra empresa"
            )

        return {
            "symbol": returned_symbol or clean_ticker,
            "name": data.get("Name", ""),
            "description": data.get("Description", ""),
            "sector": data.get("Sector", ""),
            "industry": data.get("Industry", ""),
            "market_cap": _parse_av_float(data.get("MarketCapitalization")),
            "pe_ratio": _parse_av_float(data.get("PERatio")),
            "pb_ratio": _parse_av_float(data.get("PriceToBookRatio")),
            "dividend_yield": _parse_av_float(data.get("DividendYield")),
            "eps": _parse_av_float(data.get("EPS")),
            "source": self.name,
            "fetched_at": result["fetched_at"],
            "from_cache": result["from_cache"],
        }


_default_client: AlphaVantageClient | None = None
_default_client_lock = threading.Lock()


def get_alpha_vantage_client() -> AlphaVantageClient:
    """Singleton de proceso para health checks y consumidores sin inyección."""
    global _default_client
    with _default_client_lock:
        if _default_client is None:
            _default_client = AlphaVantageClient()
        return _default_client
