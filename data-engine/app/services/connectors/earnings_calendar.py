"""Calendario publico de earnings y dividendos de NASDAQ.

Idea originada en ``s-kerin/finance_calendars`` (licencia permisiva MIT):
leer el calendario publico de NASDAQ (``api.nasdaq.com/api/calendar/...``)
dia a dia con ``httpx`` y tolerancia a fallos. Diseno inspirado en el,
implementacion propia para GerarAI: cliente asincrono inyectable en tests,
normalizacion minima de filas, fallo por dia registrado en ``errors`` sin
abortar el rango, y degradacion a ``None`` cuando un dia (o el servicio)
no responde: el llamante recibe ``status="unavailable"`` en lugar de una
excepcion.

No requiere API key, pero NASDAQ rechaza peticiones sin ``User-Agent`` de
navegador, de ahi las cabeceras por defecto.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

# Clave en el registry de salud de fuentes (api.nasdaq.com, URLs fijas por
# fecha): cualquier fallo de red/HTTP/no-JSON es de la fuente. El conector
# degrada a None para no romper el flujo; el registry es la senal honesta.
REGISTRY_KEY = "nasdaq"

EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings"
DIVIDENDS_URL = "https://api.nasdaq.com/api/calendar/dividends"

MAX_DAYS_PER_REQUEST = 31
# Concurrencia acotada entre dias: secuencial eran ~2.4s x dia (17s para la
# semana por defecto en prod); sin tope, 31 dias a la vez martirizan NASDAQ.
# 4 -> 8 (19 oct 2026): 15 dias con 4 no cabian en el deadline de 8 s en frio
# (medido en prod: partial, ultimo dia agotado); NASDAQ respondia bien.
RANGE_CONCURRENCY = 8

# Deadline TOTAL del rango (16 oct 2026: /api/calendar/catalysts tardaba >10s
# en prod y la pagina moria con un 504 de plataforma). Los dias ya resueltos
# se conservan; los que no alcanzan el deadline van a ``errors`` con el
# motivo explicito. Nunca se rellenan huecos.
RANGE_DEADLINE_S = 8.0
# Por debajo de este resto no merece abrir otra consulta: no daria tiempo.
_MIN_DAY_BUDGET_S = 0.5

# Cache por dia (1 h: los resultados casi no cambian y cada restart la deja fria) + singleflight:
# peticiones concurrentes al mismo dia comparten UNA consulta en vuelo.
# Solo aplica sin cliente inyectado (produccion); con cliente inyectado
# (tests) la cache queda fuera para que cada test controle su red.
_DAY_CACHE_TTL_S = 3600.0
_day_cache: dict[tuple[str, date], tuple[float, list[dict[str, Any]]]] = {}
# Cache negativa breve: con NASDAQ caido o lento cada vista del calendario
# (calendario, catalizadores, bloque del inicio) volvia a esperar a la red
# hasta agotar el deadline del rango. Un dia que acaba de fallar se declara
# «no disponible» al momento durante este rato y luego se reintenta.
_DAY_FAILURE_TTL_S = 60.0
_day_failures: dict[tuple[str, date], float] = {}
_day_inflight: dict[tuple[int, str, date], asyncio.Task[list[dict[str, Any]] | None]] = {}
# Stale-while-revalidate: un dia caducado (mas de 1 h) pero de menos de 24 h
# se sirve al momento y se refresca en segundo plano. Antes, cada hora, la
# primera vista del calendario/catalizadores esperaba de nuevo a NASDAQ
# (~3 s por dia, hasta el deadline de 8 s). Si el refresco falla se sigue
# sirviendo la copia y la cache negativa evita reintentar en bucle.
_DAY_STALE_MAX_S = 24 * 3600.0

# Pool HTTP compartido. Antes cada dia abria un AsyncClient nuevo (TLS nueva
# por consulta); el pool reutiliza conexiones entre dias y entre rangos.
_SHARED_CLIENT: httpx.AsyncClient | None = None


def _pooled_client() -> httpx.AsyncClient:
    """Cliente compartido del conector; se crea una vez por proceso."""
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        _SHARED_CLIENT = httpx.AsyncClient(
            timeout=20,
            headers=BROWSER_HEADERS,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )
    return _SHARED_CLIENT


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GerarAI/0.1) GerarAI Research",
    "Accept": "application/json",
}


def _parse_float(value: Any) -> float | None:
    if value in (None, "", "--", "N/A", "time-not-supplied"):
        return None
    text = str(value).strip()
    # NASDAQ entrega los negativos entre parentesis: "($0.05)" = -0.05.
    negative = text.startswith("(") and text.endswith(")")
    try:
        number = float(text.replace(",", "").strip("()%$"))
    except (TypeError, ValueError):
        return None
    return -number if negative else number


def normalize_earnings_row(row: dict[str, Any], day: date) -> dict[str, Any]:
    """Normaliza una fila del calendario de earnings a un evento propio."""
    return {
        "symbol": str(row.get("symbol", "")).upper(),
        "company": row.get("name"),
        "date": day.isoformat(),
        "time": row.get("time"),
        "eps_forecast": _parse_float(row.get("epsForecast")),
        "n_estimates": _parse_float(row.get("noOfEsts")),
        "fiscal_quarter_ending": row.get("fiscalQuarterEnding"),
        "market_cap": _parse_float(row.get("marketCap")),
    }


def normalize_dividend_row(row: dict[str, Any], day: date) -> dict[str, Any]:
    """Normaliza una fila del calendario de dividendos a un evento propio."""
    return {
        "symbol": str(row.get("symbol", "")).upper(),
        "company": row.get("companyName") or row.get("name"),
        "date": day.isoformat(),
        "ex_date": row.get("dividend_Ex_Date"),
        "payment_date": row.get("payment_Date"),
        "record_date": row.get("record_Date"),
        "amount": _parse_float(row.get("dividend_Rate") or row.get("amount")),
    }


async def _get_json(
    url: str,
    params: dict[str, str],
    client: httpx.AsyncClient | None,
) -> dict | None:
    """GET con degradacion a None ante cualquier fallo de red o parseo."""
    registry = get_data_source_registry()
    started = time.monotonic()
    if client is not None:
        try:
            response = await client.get(url, params=params, headers=BROWSER_HEADERS)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 — el calendario nunca debe romper el flujo
            registry.record_failure(REGISTRY_KEY, type(exc).__name__)
            return None
    else:
        try:
            pooled = _pooled_client()
            response = await pooled.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 — ver nota anterior
            registry.record_failure(REGISTRY_KEY, type(exc).__name__)
            return None
    if not isinstance(payload, dict):
        registry.record_failure(REGISTRY_KEY, "payload no dict")
        return None
    registry.record_success(REGISTRY_KEY, (time.monotonic() - started) * 1000)
    return payload


async def fetch_earnings_day(
    day: date,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]] | None:
    """Eventos de earnings de un dia, o None si NASDAQ no responde."""
    payload = await _get_json(EARNINGS_URL, {"date": day.isoformat()}, client)
    if not payload:
        return None
    data = payload.get("data") or {}
    rows = data.get("rows") or []
    events = [normalize_earnings_row(row, day) for row in rows if row.get("symbol")]
    return events


async def fetch_dividends_day(
    day: date,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]] | None:
    """Eventos de dividendos de un dia, o None si NASDAQ no responde."""
    payload = await _get_json(DIVIDENDS_URL, {"date": day.isoformat()}, client)
    if not payload:
        return None
    data = payload.get("data") or {}
    calendar = data.get("calendar") or data
    rows = calendar.get("rows") or []
    return [normalize_dividend_row(row, day) for row in rows if row.get("symbol")]


def _check_range(desde: date, hasta: date) -> None:
    if desde > hasta:
        raise ValueError("desde no puede ser posterior a hasta")
    if (hasta - desde).days + 1 > MAX_DAYS_PER_REQUEST:
        raise ValueError(f"rango máximo: {MAX_DAYS_PER_REQUEST} días")


# Marca interna para "el rango agoto su deadline": NO es un fallo del
# proveedor (None) ni un dato; se traduce a un error explicito por dia.
_DEADLINE: Any = object()


async def _fetch_day_pooled(
    kind: str,
    day: date,
    fetch_day: Any,
    client: httpx.AsyncClient | None,
) -> list[dict[str, Any]] | None:
    """Cache breve + singleflight por (tipo, dia) en el camino de produccion.

    Con cliente inyectado (tests) va directo a ``fetch_day``: la cache es
    estado de proceso y los tests deben controlar su red exacta.
    """
    if client is not None:
        return await fetch_day(day, client)
    key = (kind, day)
    loop = asyncio.get_running_loop()
    hit = _day_cache.get(key)
    failed_at = _day_failures.get(key)
    recently_failed = failed_at is not None and time.monotonic() - failed_at < _DAY_FAILURE_TTL_S
    if hit is not None:
        age = time.monotonic() - hit[0]
        if age < _DAY_CACHE_TTL_S:
            return hit[1]
        if age < _DAY_STALE_MAX_S:
            if not recently_failed:
                _day_flight(loop, kind, day, fetch_day)
            return hit[1]
    if recently_failed:
        return None
    return await _day_flight(loop, kind, day, fetch_day)


def _store_day(key: tuple[str, date], task: asyncio.Task[list[dict[str, Any]] | None]) -> None:
    """Guarda el resultado de una consulta de dia (en primer o segundo plano)."""
    if task.cancelled():  # p.ej. el loop de un asyncio.run que termina: no es un fallo de NASDAQ
        return
    events = None if task.exception() is not None else task.result()
    if events is not None:
        _day_cache[key] = (time.monotonic(), events)
        _day_failures.pop(key, None)
    else:
        _day_failures[key] = time.monotonic()


def _day_flight(
    loop: asyncio.AbstractEventLoop, kind: str, day: date, fetch_day: Any
) -> asyncio.Task[list[dict[str, Any]] | None]:
    """Consulta compartida (singleflight) de un dia; guarda el resultado al acabar.

    El singleflight es por event loop: una Task creada en otro loop no se
    puede esperar desde este ("attached to a different loop").
    """
    flight_key = (id(loop), kind, day)
    task = _day_inflight.get(flight_key)
    if task is None:
        task = asyncio.ensure_future(fetch_day(day, None))
        _day_inflight[flight_key] = task

        def _done(t: asyncio.Task[list[dict[str, Any]] | None]) -> None:
            _day_inflight.pop(flight_key, None)
            _store_day((kind, day), t)

        task.add_done_callback(_done)
    return task


async def _fetch_days(
    fetch_day: Any,
    desde: date,
    hasta: date,
    client: httpx.AsyncClient | None,
    *,
    kind: str = "earnings",
    deadline_s: float = RANGE_DEADLINE_S,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Consulta los dias del rango en paralelo acotado, con deadline total.

    ``asyncio.gather`` conserva el orden de los dias en el resultado, asi el
    orden por dia de ``events`` y ``errors`` es identico al bucle secuencial
    original, y cada dia que falla sigue yendo a ``errors`` sin abortar el
    rango. Ningun dia espera mas alla del deadline del rango: los dias sin
    presupuesto se declaran en ``errors`` con el motivo; los ya resueltos se
    conservan. La espera del singleflight va con ``shield``: que este rango se
    quede sin tiempo nunca cancela la consulta compartida en vuelo.
    """
    days: list[date] = []
    current = desde
    while current <= hasta:
        days.append(current)
        current += timedelta(days=1)
    semaphore = asyncio.Semaphore(RANGE_CONCURRENCY)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_s

    async def _one(day: date) -> list[dict[str, Any]] | None:
        async with semaphore:
            remaining = deadline - loop.time()
            if remaining < _MIN_DAY_BUDGET_S:
                return _DEADLINE
            try:
                return await asyncio.wait_for(
                    asyncio.shield(_fetch_day_pooled(kind, day, fetch_day, client)),
                    timeout=remaining,
                )
            except TimeoutError:  # builtin TimeoutError a partir de 3.11; asyncio.* cubre ambas
                return _DEADLINE

    per_day = await asyncio.gather(*(_one(day) for day in days))
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for day, day_events in zip(days, per_day, strict=True):
        if day_events is _DEADLINE:
            errors.append(f"{day.isoformat()}: sin datos (deadline del rango de {deadline_s:g}s agotado)")
        elif day_events is None:
            errors.append(f"{day.isoformat()}: calendario no disponible")
        else:
            events.extend(day_events)
    return events, errors


async def fetch_earnings_range(
    desde: date,
    hasta: date,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Agrega earnings dia a dia; los dias que fallan van a ``errors``.

    Si ningun dia responde, ``status`` es ``"unavailable"`` y ``events`` es
    ``[]``; si solo fallan algunos, ``status`` es ``"partial"``.
    """
    _check_range(desde, hasta)
    events, errors = await _fetch_days(fetch_earnings_day, desde, hasta, client, kind="earnings")
    if errors and not events:
        status = "unavailable"
    elif errors:
        status = "partial"
    else:
        status = "ok"
    return {
        "status": status,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "count": len(events),
        "events": events,
        "errors": errors,
    }


async def fetch_dividends_range(
    desde: date,
    hasta: date,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Agrega dividendos dia a dia con la misma semantica de degradacion."""
    _check_range(desde, hasta)
    events, errors = await _fetch_days(fetch_dividends_day, desde, hasta, client, kind="dividends")
    if errors and not events:
        status = "unavailable"
    elif errors:
        status = "partial"
    else:
        status = "ok"
    return {
        "status": status,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "count": len(events),
        "events": events,
        "errors": errors,
    }
