import time

import httpx

from app.core.config import get_settings
from app.services.connectors.base import UpstreamRateLimited, get_with_retry
from app.services.data_source_health import get_data_source_registry

# Clave en el registry de salud de fuentes. 400/404 son dato por ticker y
# 402 es entitlement por endpoint (fuera de plan): ninguno degrada la fuente
# completa; 401/403 (clave/legacy), 429 y 5xx SI.
REGISTRY_KEY = "fmp"


class FMPClient:
    """FMP connector.

    FMP retired the legacy /api/v3 endpoints for current API keys (they return
    403 "Legacy Endpoint no longer supported"), so every method targets the
    /stable API with ?symbol= query parameters. Provider/entitlement errors
    (e.g. 402 on endpoints outside the current plan) surface as exceptions so
    callers mark coverage unavailable instead of fabricating data.

    429 y 5xx se reintentan con backoff y respetando Retry-After: el plan FREE
    de FMP es 250 llamadas/DIA
    (fuente: site.financialmodelingprep.com/developer/docs/pricing, consultada
    2026-09-26) y una ingesta de un universo de 100 emisores con 4 endpoints
    cada uno (400 llamadas) lo agota con facilidad; un 429 por cuota diaria no
    se recupera dentro de la corrida y sale como UpstreamRateLimited. Antes un
    429 era un fallo definitivo y el llamante marcaba la cobertura como no
    disponible.
    """

    base_url = "https://financialmodelingprep.com/stable"

    def __init__(self) -> None:
        self.settings = get_settings()

    def configured(self) -> bool:
        return bool(self.settings.fmp_api_key)

    async def _get(
        self, path: str, params: dict | None = None, *, max_retries: int | None = None
    ) -> list | dict:
        if not self.configured():
            raise RuntimeError("FMP no está configurado en este despliegue (FMP_API_KEY vacía)")
        merged = {**(params or {}), "apikey": self.settings.fmp_api_key}
        url = f"{self.base_url}{path}"
        registry = get_data_source_registry()
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                retry_kwargs = {} if max_retries is None else {"max_retries": max_retries}
                response = await get_with_retry(lambda: client.get(url, params=merged), **retry_kwargs)
                payload = response.json()
        except UpstreamRateLimited:
            registry.record_failure(REGISTRY_KEY, "HTTP 429: cuota diaria/rate limit agotada")
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 402, 404):
                # 400/404: ticker sin dato. 402: endpoint fuera de plan
                # (entitlement por endpoint, no fuente caida).
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

    async def company_profile(self, ticker: str) -> list | dict:
        return await self._get("/profile", {"symbol": ticker.upper()})

    async def quote(self, ticker: str, *, max_retries: int | None = None) -> list | dict:
        """Cotizacion puntual: price, volume y timestamp REAL de la quote.

        El profile no trae timestamp de cotizacion (sus campos de fecha son
        metadatos como ipoDate), asi que fechar precios con el escribia barras
        en dias sin mercado con el ultimo cierre conocido.
        """
        return await self._get("/quote", {"symbol": ticker.upper()}, max_retries=max_retries)

    async def dividends(self, ticker: str) -> list | dict:
        """Declared dividend records for a symbol (FMP stable/dividends).

        Returns the raw provider payload. Entitlement/auth errors surface as
        exceptions so callers can mark coverage unavailable instead of
        fabricating dividend data.
        """
        return await self._get("/dividends", {"symbol": ticker.upper()})

    async def splits(self, ticker: str) -> list | dict:
        """Historical stock splits for a symbol (FMP stable/splits).

        Errors surface as exceptions so callers mark coverage unavailable
        instead of guessing share-count adjustments.
        """
        return await self._get("/splits", {"symbol": ticker.upper()})

    async def income_statement(self, ticker: str, limit: int = 10) -> list | dict:
        return await self._get("/income-statement", {"symbol": ticker.upper(), "limit": limit})

    async def balance_sheet(self, ticker: str, limit: int = 10) -> list | dict:
        return await self._get("/balance-sheet-statement", {"symbol": ticker.upper(), "limit": limit})

    async def cash_flow(self, ticker: str, limit: int = 10) -> list | dict:
        return await self._get("/cash-flow-statement", {"symbol": ticker.upper(), "limit": limit})

    async def ratios(self, ticker: str, limit: int = 10) -> list | dict:
        return await self._get("/ratios", {"symbol": ticker.upper(), "limit": limit})

    async def news(self, ticker: str, limit: int = 25) -> list | dict:
        """Latest stock news for a symbol (FMP stable/news/stock).

        FMP plans without news coverage answer 402 here; the error propagates
        so callers mark news coverage unavailable rather than showing stale or
        invented headlines.
        """
        return await self._get("/news/stock", {"symbols": ticker.upper(), "limit": limit})
