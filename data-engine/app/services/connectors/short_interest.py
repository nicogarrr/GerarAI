"""Senales de posicion corta (FINRA) y volatilidad (VIX, CBOE via Yahoo).

Dos vendors gratuitos y sin clave que faltaban en GerarAI:

* **FINRA — volumen corto diario (RegSHO)**: ficheros de texto publicados en
  ``cdn.finra.org/equity/regsho/daily/CNMSshvol{AAAAMMDD}.txt`` con columnas
  ``Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market``. Es el dato
  gratuito y por ticker que mejor aproxima la presion de ventas en corto.
* **FINRA — posicion corta consolidada (quincenal)**: ``api.finra.org`` sirve el
  dataset ``consolidatedShortInterest`` (short interest, days-to-cover). Ojo: el
  filtro ``queryFilter`` se ignora en acceso anonimo (verificado en vivo), asi
  que el ticker se localiza con una busqueda binaria acotada sobre ``offset``
  (el dataset llega ordenado por ``symbolCode``). Nunca se hacen mas de
  ``max_requests`` peticiones.
* **VIX (^VIX, indice CBOE)**: chart API de Yahoo (mismo patron que
  ``app/api/routes/market.py``). Yahoo es un agregador no oficial: el VIX es un
  indice publico, pero el precio sirve solo como señal, nunca como referencia
  autoritativa.

Idea de estructura inspirada en los conectores gratuitos de
TauricResearch/TradingAgents (Apache-2.0); implementacion propia para GerarAI
con ``httpx`` inyectable (tests hermeticos con ``MockTransport``). Ninguna
funcion de red lanza excepciones: degradan a ``None``.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

# Clave en el registry de salud de fuentes. Un 404 del fichero diario RegSHO
# es "aun no publicado ese dia" (exploracion normal del lookback) y NO
# degrada; red/401/403/429/5xx SI. En la API quincenal 400/404 son neutrales.
REGISTRY_KEY = "finra"

FINRA_REGSHO_DAILY_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{yyyymmdd}.txt"
FINRA_SHORT_INTEREST_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------- FINRA: volumen corto diario (RegSHO) ----------------


# Cabecera oficial del RegSHO diario, verificada en vivo el 2026-10-31 contra
# https://cdn.finra.org/equity/regsho/daily/CNMSshvol20261030.txt (la linea
# real termina en espacio: "Date|Symbol|...|Market ").
REGSHO_DAILY_HEADER = ("Date", "Symbol", "ShortVolume", "ShortExemptVolume", "TotalVolume", "Market")


def has_regsho_daily_header(text: str) -> bool:
    """True si la primera linea es la cabecera oficial del RegSHO diario."""
    lines = text.splitlines()
    if not lines:
        return False
    parts = [part.strip() for part in lines[0].split("|")]
    return parts[:6] == list(REGSHO_DAILY_HEADER)


def parse_regsho_daily(text: str, symbol: str) -> dict | None:
    """Extrae la fila de `symbol` del fichero RegSHO diario (texto con `|`).

    Devuelve ``None`` si el ticker no cotizo ese dia o el fichero esta vacio.
    Lineas malformadas se ignoran en vez de romper el parseo.
    """
    wanted = symbol.strip().upper()
    if not wanted or not text:
        return None
    for line in text.splitlines():
        parts = [part.strip() for part in line.strip().split("|")]
        if len(parts) < 6 or parts[0] == "Date" or parts[1].upper() != wanted:
            continue
        short_volume = _to_float(parts[2])
        short_exempt = _to_float(parts[3])
        total_volume = _to_float(parts[4])
        if short_volume is None or total_volume is None or short_exempt is None:
            continue
        if any(not math.isfinite(v) or v < 0 or not v.is_integer() for v in (short_volume, total_volume)):
            continue
        if short_volume > total_volume:
            continue
        if short_exempt is not None and (
            not math.isfinite(short_exempt)
            or short_exempt < 0
            or short_exempt > short_volume
            or not short_exempt.is_integer()
        ):
            continue
        yyyymmdd = parts[0]
        trade_date = (
            f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
            if len(yyyymmdd) == 8 and yyyymmdd.isdigit()
            else yyyymmdd
        )
        try:
            date.fromisoformat(trade_date)
        except ValueError:
            continue
        ratio = (short_volume / total_volume) if total_volume > 0 else None
        return {
            "symbol": wanted,
            "date": trade_date,
            "short_volume": int(short_volume),
            "short_exempt_volume": int(short_exempt or 0),
            "total_volume": int(total_volume),
            "short_volume_ratio": ratio,
            "markets": parts[5],
            "source": "finra_regsho",
            "source_url": FINRA_REGSHO_DAILY_URL.format(yyyymmdd=yyyymmdd),
        }
    return None


async def fetch_short_volume(
    symbol: str,
    trade_date: date | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    lookback_days: int = 7,
) -> dict | None:
    """Ultimo volumen corto diario de `symbol` publicado por FINRA.

    El fichero del dia se publica tras el cierre y no hay dato en fines de
    semana/festivos: se retrocede hasta `lookback_days` dias hasta encontrar el
    ultimo fichero que contiene al ticker. ``None`` si no hay dato (sin excepciones).
    """
    day = trade_date or datetime.now(UTC).date()
    for offset in range(lookback_days + 1):
        current = day - timedelta(days=offset)
        yyyymmdd = current.strftime("%Y%m%d")
        url = FINRA_REGSHO_DAILY_URL.format(yyyymmdd=yyyymmdd)
        registry = get_data_source_registry()
        try:
            if client is not None:
                response = await client.get(url, headers=dict(_HEADERS))
            else:
                async with httpx.AsyncClient(timeout=30, headers=dict(_HEADERS)) as owned:
                    response = await owned.get(url)
        except httpx.HTTPError as exc:
            registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            return None
        if response.status_code in {401, 403, 429}:
            registry.record_failure(REGISTRY_KEY, f"HTTP {response.status_code}")
            return None
        if response.status_code != 200:
            # 404 = fichero de ese dia aun no publicado (finde/festivo o antes
            # del cierre): exploracion normal del lookback, no fuente caida.
            if response.status_code not in (400, 404):
                registry.record_failure(REGISTRY_KEY, f"HTTP {response.status_code}")
            continue
        if not has_regsho_daily_header(response.text):
            # 200 sin la cabecera oficial (challenge HTML, captive proxy o
            # cambio de formato): deriva de formato, no exito. No seguir con
            # el lookback: los demas dias responderan igual.
            registry.record_failure(REGISTRY_KEY, "200 sin la cabecera oficial RegSHO")
            return None
        registry.record_success(REGISTRY_KEY)
        row = parse_regsho_daily(response.text, symbol)
        if row is not None:
            return row
    return None


# ---------------- FINRA: posicion corta consolidada (quincenal) ----------------


def parse_short_interest_record(record: dict, symbol: str) -> dict | None:
    """Normaliza una fila del dataset `consolidatedShortInterest` de FINRA."""
    if not isinstance(record, dict):
        return None
    code = str(record.get("symbolCode") or "").upper()
    if code != symbol.strip().upper():
        return None
    current = _to_float(record.get("currentShortPositionQuantity"))
    previous = _to_float(record.get("previousShortPositionQuantity"))
    avg_volume = _to_float(record.get("averageDailyVolumeQuantity"))
    days_to_cover = _to_float(record.get("daysToCoverQuantity"))
    if days_to_cover is None and current is not None and avg_volume:
        days_to_cover = current / avg_volume
    change_pct = (current - previous) / previous if current is not None and previous else None
    return {
        "symbol": code,
        "issue_name": record.get("issueName"),
        "settlement_date": record.get("settlementDate"),
        "short_interest": int(current) if current is not None else None,
        "previous_short_interest": int(previous) if previous is not None else None,
        "change_pct": change_pct,
        "average_daily_volume": int(avg_volume) if avg_volume is not None else None,
        "days_to_cover": days_to_cover,
        "market_class": record.get("marketClassCode"),
        "source": "finra_short_interest",
        "source_url": FINRA_SHORT_INTEREST_URL,
    }


async def _short_interest_page(
    offset: int,
    limit: int,
    client: httpx.AsyncClient | None,
) -> list | None:
    params = {"limit": limit, "offset": offset, "sortField": "symbolCode", "sortOrder": "asc"}
    registry = get_data_source_registry()
    try:
        if client is not None:
            response = await client.get(FINRA_SHORT_INTEREST_URL, params=params, headers=dict(_HEADERS))
        else:
            async with httpx.AsyncClient(timeout=30, headers=dict(_HEADERS)) as owned:
                response = await owned.get(FINRA_SHORT_INTEREST_URL, params=params)
    except httpx.HTTPError as exc:
        registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        return None
    if response.status_code != 200:
        if response.status_code not in (400, 404):
            registry.record_failure(REGISTRY_KEY, f"HTTP {response.status_code}")
        return None
    try:
        data = response.json()
    except ValueError:
        registry.record_failure(REGISTRY_KEY, "respuesta no JSON")
        return None
    if not isinstance(data, list):
        registry.record_failure(REGISTRY_KEY, "payload no lista")
        return None
    registry.record_success(REGISTRY_KEY)
    return data


async def fetch_short_interest(
    symbol: str,
    *,
    client: httpx.AsyncClient | None = None,
    page_size: int = 200,
    max_requests: int = 12,
) -> dict | None:
    """Posicion corta consolidada (quincenal) de `symbol`; ``None`` si no hay dato.

    Acceso anonimo: el ``queryFilter`` de FINRA se ignora (verificado en vivo),
    asi que se hace una busqueda binaria acotada por indice de pagina (multiplos
    de `page_size`) aprovechando que el dataset llega ordenado por
    ``symbolCode``. Nunca mas de `max_requests` peticiones y nunca una excepcion
    hacia el llamante.
    """
    wanted = symbol.strip().upper()
    if not wanted or page_size < 1 or max_requests < 1:
        return None

    budget = max_requests
    seen: dict[int, list] = {}

    async def page(index: int) -> list | None:
        nonlocal budget
        if index in seen:
            return seen[index]
        if budget <= 0:
            return None
        budget -= 1
        rows = await _short_interest_page(index * page_size, page_size, client)
        if rows:
            seen[index] = rows
        return rows

    def find(rows: list) -> dict | None:
        for row in rows:
            parsed = parse_short_interest_record(row, wanted)
            if parsed is not None:
                return parsed
        return None

    # 1) Busqueda exponencial del primer indice de pagina cuyo ultimo codigo
    #    alcanza al ticker (o de una pagina vacia = fin del dataset).
    low, high = 0, 1
    while budget > 0:
        rows = await page(high)
        if not rows:
            break
        if str(rows[-1].get("symbolCode") or "").upper() >= wanted:
            break
        low, high = high, high * 2

    # 2) Busqueda binaria dentro de [low, high].
    while low < high and budget > 0:
        mid = (low + high) // 2
        rows = await page(mid)
        if not rows:
            high = mid
            continue
        hit = find(rows)
        if hit is not None:
            return hit
        if wanted < str(rows[0].get("symbolCode") or "").upper():
            high = mid
        else:
            low = mid + 1

    # 3) El ticker puede haber caido en una pagina frontera ya descargada.
    for rows in seen.values():
        hit = find(rows)
        if hit is not None:
            return hit
    return None
