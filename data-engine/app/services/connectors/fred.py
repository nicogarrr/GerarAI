"""Serie macro de FRED (St. Louis Fed) con clave gratuita opcional.

Idea originada en TauricResearch/TradingAgents
``tradingagents/dataflows/fred.py`` (Apache-2.0): la clave gratuita se lee de
``FRED_API_KEY`` y, si falta, el conector se degrada a "no disponible" en vez
de romper el flujo. Implementacion propia para GerarAI: ``httpx`` asincrono con
User-Agent de navegador, alias legibles -> series FRED, y funciones de modulo
que devuelven ``None`` sin clave.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.connectors.base import UpstreamRateLimited, get_with_retry
from app.services.data_source_health import get_data_source_registry

# Clave de este proveedor en el registry de salud de fuentes (ver yahoo.py:
# sin registrar outcomes el circuit breaker nunca transita). FRED devuelve
# 400 para series inexistentes: eso es dato por serie, no fuente caida.
REGISTRY_KEY = "fred"

_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": ("Mozilla/5.0 (compatible; GerarAI/0.1; +mailto:contact@example.com)"),
    "Accept": "application/json",
}


class FREDClient:
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self.client = client

    @property
    def headers(self) -> dict[str, str]:
        return dict(_BROWSER_HEADERS)

    def configured(self) -> bool:
        return bool(get_api_key())

    async def series(self, series_id: str, limit: int = 120) -> dict:
        if not self.configured():
            raise RuntimeError("FRED_API_KEY is not configured")
        params = {
            "series_id": series_id,
            "api_key": get_api_key(),
            "file_type": "json",
            "limit": limit,
            "sort_order": "desc",
        }
        url = f"{self.base_url}/series/observations"
        registry = get_data_source_registry()
        started = time.perf_counter()
        try:
            if self.client is not None:
                response = await get_with_retry(
                    lambda: self.client.get(url, params=params, headers=self.headers)
                )
            else:
                async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
                    response = await get_with_retry(lambda: client.get(url, params=params))
            payload = response.json()
        except UpstreamRateLimited:
            # 429 agotado por get_with_retry: sin este except el fallo no se
            # registraba nunca (UpstreamRateLimited no es HTTPStatusError).
            registry.record_failure(REGISTRY_KEY, "HTTP 429: rate limit agotado")
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                # Serie inexistente o peticion mal formada: la fuente respondio.
                raise
            registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
            raise
        except httpx.TransportError as exc:
            registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            raise
        except ValueError:
            registry.record_failure(REGISTRY_KEY, "respuesta no JSON")
            raise
        registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
        return payload

    async def series_csv(self, series_id: str, limit: int = 10) -> dict:
        """Serie via fredgraph.csv (endpoint publico, SIN clave).

        Devuelve el mismo shape que ``series`` ({"observations": [...]},
        mas reciente primero) para que el consumidor no distinga la via.
        Fuente declarada: https://fred.stlouisfed.org/graph/fredgraph.csv
        """
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        registry = get_data_source_registry()
        started = time.perf_counter()
        try:
            if self.client is not None:
                response = await self.client.get(url, headers=self.headers)
            else:
                async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
                    response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                # Serie inexistente: dato por serie, no fuente caida.
                raise
            registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
            raise
        except httpx.TransportError as exc:
            registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            raise
        text = response.text
        header = text.split("\n", 1)[0].strip().lower()
        first_col = header.split(",", 1)[0]
        # Cabecera real verificada contra la fuente viva el 2026-10-31:
        # "observation_date,CPIAUCSL" (primera columna observation_date; la
        # segunda es el propio id de serie). "DATE" era el formato legado.
        if text.lstrip().startswith("<") or first_col not in ("observation_date", "date"):
            # Un 200 con HTML (challenge) o un CSV con cabecera distinta no es
            # salud: validar el esquema ANTES de registrar el exito.
            registry.record_failure(REGISTRY_KEY, "respuesta no CSV (challenge o cambio de formato)")
            raise RuntimeError("FRED no devolvio un CSV con la cabecera esperada")
        registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
        observations = []
        for line in text.splitlines()[1:]:
            date, _, value = line.partition(",")
            if not date:
                continue
            observations.append({"date": date.strip(), "value": value.strip()})
        observations.reverse()  # CSV viene ascendente; la API devuelve desc
        return {"observations": observations[:limit]}


# Alias legibles -> IDs de serie FRED. Un ID crudo valido se usa tal cual.
MACRO_SERIES: dict[str, str] = {
    "cpi": "CPIAUCSL",
    "inflation": "CPIAUCSL",
    "unemployment": "UNRATE",
    "unemployment_rate": "UNRATE",
    "fed_funds_rate": "FEDFUNDS",
    "fed_funds": "FEDFUNDS",
    "gdp": "GDP",
    "real_gdp": "GDPC1",
    "10y_treasury": "DGS10",
    "2y_treasury": "DGS2",
    "m2": "M2SL",
    "industrial_production": "INDPRO",
    "retail_sales": "RSAFS",
    "housing_starts": "HOUST",
}


def get_api_key() -> str | None:
    """Clave FRED desde el entorno (``FRED_API_KEY``) o settings; None si falta."""
    return os.getenv("FRED_API_KEY") or get_settings().fred_api_key or None


def is_configured() -> bool:
    return bool(get_api_key())


def resolve_series_id(indicator: str) -> str:
    """Alias -> ID FRED; un ID crudo (corto, sin espacios) pasa tal cual."""
    key = indicator.strip().lower().replace(" ", "_").replace("-", "_")
    if key in MACRO_SERIES:
        return MACRO_SERIES[key]
    candidate = indicator.strip().upper()
    if not candidate or len(candidate) > 30 or any(c.isspace() for c in candidate):
        raise ValueError(
            f"'{indicator}' no es un alias macro conocido ni un ID FRED valido. "
            "Usa un alias (p. ej. 'cpi', 'unemployment', '10y_treasury') o un ID "
            "crudo (p. ej. 'CPIAUCSL')."
        )
    return candidate


async def fetch_observations(
    indicator: str,
    limit: int = 12,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Observaciones FRED o ``None`` si no hay clave (degradacion gratuita)."""
    api_key = get_api_key()
    if not api_key:
        return None
    series_id = resolve_series_id(indicator)
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "limit": limit,
        "sort_order": "desc",
    }
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        if client is not None:
            response = await client.get(
                f"{FREDClient.base_url}/series/observations",
                params=params,
                headers=dict(_BROWSER_HEADERS),
            )
        else:
            async with httpx.AsyncClient(timeout=30, headers=dict(_BROWSER_HEADERS)) as owned:
                response = await owned.get(f"{FREDClient.base_url}/series/observations", params=params)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            # Serie inexistente o peticion mal formada: la fuente respondio.
            raise
        registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    except ValueError:
        registry.record_failure(REGISTRY_KEY, "respuesta no JSON")
        raise
    registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    data.setdefault("series_id", series_id)
    return data


async def latest_observation(
    indicator: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Ultima observacion {series_id, date, value} o ``None`` sin clave/datos."""
    try:
        data = await fetch_observations(indicator, limit=12, client=client)
    except ValueError:
        raise
    except Exception:
        return None
    if not data:
        return None
    series_id = data.get("series_id", resolve_series_id(indicator))
    points = [
        o
        for o in (data.get("observations") or [])
        if isinstance(o, dict) and o.get("value") not in (".", None, "")
    ]
    if not points:
        return None
    last = points[0]
    try:
        value: Any = float(last["value"])
    except (KeyError, TypeError, ValueError):
        value = last.get("value")
    return {"series_id": series_id, "date": last.get("date"), "value": value}
