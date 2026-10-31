"""OpenFIGI v3 identifier mapping without an API key.

Return all matches rather than guessing a listing when an ISIN maps to
multiple venues. Callers must disambiguate exchange/currency before use.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

# Clave en el registry de salud de fuentes. 400/404 (job mal formado) y un
# payload con "error" por identificador son dato por consulta y NO degradan;
# 429/5xx agotados, red y payload invalido SI.
REGISTRY_KEY = "openfigi"


class OpenFIGIClient:
    name = "openfigi"
    base_url = "https://api.openfigi.com/v3/mapping"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    def configured(self) -> bool:
        return True

    async def map_identifier(
        self, value: str, *, id_type: str = "ID_ISIN", exch_code: str | None = None
    ) -> dict[str, Any]:
        """One mapping job. Status `ambiguous` is deliberately not a ticker pick."""
        if id_type not in {"ID_ISIN", "ID_BB_GLOBAL"}:
            raise ValueError("Only ISIN and FIGI mappings are supported")
        value = value.strip().upper()
        if not value or len(value) > 40:
            raise ValueError("Invalid identifier")
        job = {"idType": id_type, "idValue": value}
        if exch_code:
            job["exchCode"] = exch_code.strip().upper()
        registry = get_data_source_registry()
        started = time.perf_counter()
        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(self.base_url, json=[job])
            else:
                response = await self.client.post(self.base_url, json=[job])
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                # Job mal formado: la fuente respondio; no se degrada.
                raise
            registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
            raise
        except httpx.TransportError as exc:
            registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            raise
        except ValueError:
            registry.record_failure(REGISTRY_KEY, "respuesta no JSON")
            raise
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            registry.record_failure(REGISTRY_KEY, "payload de mapeo invalido")
            raise RuntimeError("OpenFIGI returned an invalid mapping response")
        result = payload[0]
        if result.get("error"):
            # Error por identificador (dato por consulta): la fuente respondio.
            registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
            return {
                "status": "error",
                "identifier": value,
                "matches": [],
                "error": str(result["error"]),
                "source": self.name,
                "source_url": self.base_url,
            }
        matches = result.get("data") or []
        if not isinstance(matches, list) or any(not isinstance(row, dict) for row in matches):
            registry.record_failure(REGISTRY_KEY, "matches de mapeo invalidos")
            raise RuntimeError("OpenFIGI returned invalid mapping matches")
        clean = [
            {
                key: row.get(key)
                for key in (
                    "figi",
                    "compositeFIGI",
                    "shareClassFIGI",
                    "ticker",
                    "name",
                    "exchCode",
                    "marketSector",
                    "securityType",
                    "securityType2",
                )
            }
            for row in matches
            if row.get("figi")
        ]
        # La fuente respondio bien (mapeado, ambiguo, sin cobertura o error
        # por identificador): exito de fuente en todos los casos.
        registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
        return {
            "status": "unavailable" if not clean else "matched" if len(clean) == 1 else "ambiguous",
            "identifier": value,
            "matches": clean,
            "source": self.name,
            "source_url": self.base_url,
        }


# --- Instrument-reference helpers (sync, httpx directo, sin dependencia nueva) ---
#
# El cliente async de arriba se conserva intacto (contrato de
# test_connector_openfigi.py). Lo de abajo lo usa el seed de instrumentos:
# rate limit propio (25 req/min sin key), cache en memoria con TTL y
# reintento solo ante 429/5xx, nunca ante 4xx.

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
OPENFIGI_API_KEY_HEADER = "X-OPENFIGI-APIKEY"


def is_retryable_status(status_code: int) -> bool:
    """Solo 429 y 5xx se reintentan. Un 4xx es un fallo de dato, nunca se reintenta."""
    return status_code in RETRYABLE_STATUS_CODES


class OpenFIGIRateLimiter:
    """Token bucket por ventana deslizante (N req/min). Sin key: 25 req/min."""

    def __init__(self, requests_per_minute: int = 25) -> None:
        self.requests_per_minute = max(1, requests_per_minute)
        self._hits: deque[float] = deque()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()

    def wait_seconds(self) -> float:
        """Segundos a esperar antes del proximo request (0 = via libre)."""
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._hits) < self.requests_per_minute:
                return 0.0
            return max(0.0, 60.0 - (now - self._hits[0]))

    def record(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._hits.append(now)

    def wait_if_needed(self) -> None:
        delay = self.wait_seconds()
        if delay > 0:
            time.sleep(delay)


class OpenFIGICache:
    """Cache en memoria con TTL. Clave = (idType, idValue, exchCode)."""

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self.ttl_seconds = max(1, ttl_seconds)
        self._store: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()

    def get(self, id_type: str, id_value: str, exch_code: str = "") -> dict[str, Any] | None:
        key = (id_type, id_value, exch_code)
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            expires_at, value = hit
            if time.monotonic() >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, id_type: str, id_value: str, value: dict[str, Any], exch_code: str = "") -> None:
        key = (id_type, id_value, exch_code)
        with self._lock:
            self._store[key] = (time.monotonic() + self.ttl_seconds, value)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class OpenFIGIConnector:
    """Conector sync para el seed de instrumentos (httpx directo, sin key por defecto).

    - Rate limit propio configurable (default 25 req/min, limite anonimo oficial).
    - Cache en memoria con TTL (default 24 h).
    - Reintento con backoff solo ante 429/5xx (max_retries); los 4xx se
      devuelven como error sin reintentar. Sin tarjeta, sin registro obligatorio.
    """

    name = "openfigi"
    base_url = "https://api.openfigi.com/v3/mapping"

    def __init__(
        self,
        api_key: str | None = None,
        requests_per_minute: int = 25,
        cache_ttl_seconds: int = 86400,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or None
        self.limiter = OpenFIGIRateLimiter(requests_per_minute)
        self.cache = OpenFIGICache(cache_ttl_seconds)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        if base_url:
            self.base_url = base_url
        self._client = client

    def configured(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {OPENFIGI_API_KEY_HEADER: self.api_key}
        return {}

    def _post(self, payload: list[dict[str, str]]) -> httpx.Response:
        if self._client is not None:
            return self._client.post(self.base_url, json=payload, headers=self._headers())
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.post(self.base_url, json=payload, headers=self._headers())

    def map_identifier(
        self, value: str, *, id_type: str = "ID_ISIN", exch_code: str | None = None
    ) -> dict[str, Any]:
        """Un job de mapeo sync con cache + rate limit + retry acotado."""
        if id_type not in {"ID_ISIN", "ID_BB_GLOBAL"}:
            raise ValueError("Only ISIN and FIGI mappings are supported")
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 40:
            raise ValueError("Invalid identifier")
        exchange = (exch_code or "").strip().upper()
        cached = self.cache.get(id_type, normalized, exchange)
        if cached is not None:
            return cached
        job: dict[str, str] = {"idType": id_type, "idValue": normalized}
        if exchange:
            job["exchCode"] = exchange
        self.limiter.wait_if_needed()
        last_error: str | None = None
        response: httpx.Response | None = None
        registry = get_data_source_registry()
        for attempt in range(self.max_retries + 1):
            self.limiter.record()
            try:
                response = self._post([job])
            except httpx.TransportError as exc:
                registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
                raise
            if response.status_code == 200:
                break
            if not is_retryable_status(response.status_code):
                if response.status_code not in (400, 404):
                    # 401/403 (clave rechazada/bloqueo) degrada igual que en el
                    # async; 400/404 (job mal formado) es dato por consulta.
                    registry.record_failure(REGISTRY_KEY, f"HTTP {response.status_code}")
                result: dict[str, Any] = {
                    "status": "error",
                    "identifier": normalized,
                    "matches": [],
                    "error": f"HTTP {response.status_code}",
                    "source": self.name,
                    "source_url": self.base_url,
                }
                return result
            last_error = f"HTTP {response.status_code}"
            if attempt < self.max_retries:
                time.sleep(min(2.0**attempt, 8.0))
        if response is None or response.status_code != 200:
            # 429/5xx agotados tras reintentos: la fuente no esta disponible.
            get_data_source_registry().record_failure(
                REGISTRY_KEY, f"{last_error or 'HTTP error'} (reintentos agotados)"
            )
            result = {
                "status": "error",
                "identifier": normalized,
                "matches": [],
                "error": last_error or "HTTP error",
                "source": self.name,
                "source_url": self.base_url,
            }
            return result
        try:
            payload = response.json()
        except ValueError:
            registry.record_failure(REGISTRY_KEY, "respuesta no JSON")
            raise
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            registry.record_failure(REGISTRY_KEY, "payload de mapeo invalido")
            raise RuntimeError("OpenFIGI returned an invalid mapping response")
        body = payload[0]
        if body.get("error"):
            # Error por identificador (dato por consulta): la fuente respondio,
            # cuenta como exito de salud igual que en la via async.
            registry.record_success(REGISTRY_KEY)
            result = {
                "status": "error",
                "identifier": normalized,
                "matches": [],
                "error": str(body["error"]),
                "source": self.name,
                "source_url": self.base_url,
            }
            self.cache.set(id_type, normalized, result, exchange)
            return result
        matches = body.get("data") or []
        if not isinstance(matches, list) or any(not isinstance(row, dict) for row in matches):
            get_data_source_registry().record_failure(REGISTRY_KEY, "matches de mapeo invalidos")
            raise RuntimeError("OpenFIGI returned invalid mapping matches")
        clean = [
            {
                key: row.get(key)
                for key in (
                    "figi",
                    "compositeFIGI",
                    "shareClassFIGI",
                    "ticker",
                    "name",
                    "exchCode",
                    "marketSector",
                    "securityType",
                    "securityType2",
                )
            }
            for row in matches
            if row.get("figi")
        ]
        result = {
            "status": "unavailable" if not clean else "matched" if len(clean) == 1 else "ambiguous",
            "identifier": normalized,
            "matches": clean,
            "source": self.name,
            "source_url": self.base_url,
        }
        self.cache.set(id_type, normalized, result, exchange)
        get_data_source_registry().record_success(REGISTRY_KEY)
        return result
