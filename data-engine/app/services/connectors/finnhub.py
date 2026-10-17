from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.services.connectors.base import get_with_retry


class FinnhubClient:
    """Finnhub connector.

    429 y 5xx se reintentan con backoff y respetando Retry-After. El plan FREE
    de Finnhub son 60 llamadas/minuto (fuente: finnhub.io/pricing, consultada
    2026-09-26) y el consumo normal ya lo ronda: el
    refresco de precios hace fan-out sobre todo el universo de empresas del
    tenant con 6 conexiones simultaneas, y la lectura de multiples paginas de
    IR suma mas. Antes un 429 era un fallo definitivo y el llamante lo
    registraba como proveedor no disponible, con lo que los precios de esa
    corrida se perdian sin reintento.
    """

    base_url = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        self.settings = get_settings()

    def configured(self) -> bool:
        return bool(self.settings.finnhub_api_key)

    async def _get(self, path: str, params: dict[str, Any], *, max_retries: int | None = None) -> Any:
        if not self.configured():
            raise RuntimeError("FINNHUB_API_KEY is not configured")
        url = f"{self.base_url}{path}"
        query = {**params, "token": self.settings.finnhub_api_key}
        retry_kwargs = {} if max_retries is None else {"max_retries": max_retries}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await get_with_retry(lambda: client.get(url, params=query), **retry_kwargs)
            return response.json()

    async def quote(self, ticker: str, *, max_retries: int | None = None) -> dict[str, Any]:
        payload = await self._get("/quote", {"symbol": ticker.upper()}, max_retries=max_retries)
        if not isinstance(payload, dict):
            raise RuntimeError("Finnhub returned an invalid quote")
        return payload

    async def profile(self, ticker: str) -> dict[str, Any]:
        """Company profile (/stock/profile2): real name, market cap, IR url.

        Raises RuntimeError without API key or on invalid payloads so the
        caller can degrade to the existing Company master seed.
        """
        payload = await self._get("/stock/profile2", {"symbol": ticker.upper()})
        if not isinstance(payload, dict):
            raise RuntimeError("Finnhub returned an invalid profile")
        return payload

    async def us_symbols(self) -> list[dict[str, Any]]:
        """Universo US completo (/stock/symbol?exchange=US, tier gratis).

        Cada entrada: symbol, description, mic, type, currency... Sirve para
        crear fichas Company en bulk sin llamadas por simbolo.
        """
        payload = await self._get("/stock/symbol", {"exchange": "US"})
        if not isinstance(payload, list):
            raise RuntimeError("Finnhub returned an invalid symbol universe")
        return [row for row in payload if isinstance(row, dict)]

    async def metric(self, ticker: str) -> dict[str, Any]:
        """Basic financials (/stock/metric?metric=all): margenes, crecimiento,
        per-share, valoracion. Devuelve el dict "metric" tal cual (sin
        normalizar); el caller decide que hechos deriva y como los etiqueta.
        """
        payload = await self._get("/stock/metric", {"symbol": ticker.upper(), "metric": "all"})
        if not isinstance(payload, dict) or not isinstance(payload.get("metric"), dict):
            raise RuntimeError("Finnhub returned invalid metrics")
        return payload["metric"]
