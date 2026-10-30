"""Conector de Alpha Vantage para cotizaciones y datos fundamentales como fuente secundaria.

Fulfills: VAL-DATA-002
Expected Behavior:
- Alpha Vantage como fuente de respaldo (fallback) tras Yahoo Finance
- Control estricto de cuota para el nivel gratuito (free tier: máximo 5 llamadas por minuto)
- Obtención de cotizaciones (`GLOBAL_QUOTE`) y fundamentales (`OVERVIEW`)
- Gestión de clave de API mediante variables de entorno (ALPHA_VANTAGE_API_KEY)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

from app.services.connectors.base import get_with_retry

# Alpha Vantage Free Tier: 5 llamadas por minuto (mínimo 12.0s entre llamadas)
AV_MAX_REQUESTS_PER_MINUTE = 5.0
AV_MIN_INTERVAL_SECONDS = 60.0 / AV_MAX_REQUESTS_PER_MINUTE


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

    def reset(self) -> None:
        with self._lock:
            self._next_allowed_at = 0.0


_av_limiter = AlphaVantageRateLimiter()


class AlphaVantageClient:
    """Cliente HTTP asíncrono para Alpha Vantage con limitación de tasa y reintentos."""

    name = "alpha_vantage"
    base_url = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")

    def configured(self) -> bool:
        """Indica si la clave de API está configurada en el entorno."""
        return bool(self.api_key)

    async def _fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una petición GET respetando la tasa de 5 req/min."""
        if not self.configured():
            raise RuntimeError("Alpha Vantage no está configurado (falta ALPHA_VANTAGE_API_KEY)")

        # Control de tasa
        _av_limiter.wait()

        query_params = {**params, "apikey": self.api_key}

        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await client.get(self.base_url, params=query_params)

        response = await get_with_retry(_call, max_retries=1)
        data = response.json()

        if isinstance(data, dict):
            # Alpha Vantage devuelve notas de límite de tasa en JSON con status 200
            if "Note" in data:
                raise RuntimeError(f"Alpha Vantage rate limit reached: {data['Note']}")
            if "Error Message" in data:
                raise ValueError(f"Alpha Vantage error: {data['Error Message']}")

        return data if isinstance(data, dict) else {}

    async def quote(self, ticker: str) -> dict[str, Any]:
        """Obtiene la última cotización para un ticker (GLOBAL_QUOTE)."""
        clean_ticker = ticker.split(".")[0].upper()
        data = await self._fetch({"function": "GLOBAL_QUOTE", "symbol": clean_ticker})
        quote_data = data.get("Global Quote", {})
        if not quote_data:
            raise RuntimeError(f"Alpha Vantage no devolvió cotización para {ticker}")

        return {
            "symbol": quote_data.get("01. symbol", clean_ticker),
            "price": float(quote_data.get("05. price", 0.0)),
            "volume": int(quote_data.get("06. volume", 0)),
            "latest_trading_day": quote_data.get("07. latest trading day", ""),
            "previous_close": float(quote_data.get("08. previous close", 0.0)),
            "change": float(quote_data.get("09. change", 0.0)),
            "change_percent": quote_data.get("10. change percent", "0%"),
            "source": self.name,
        }

    async def overview(self, ticker: str) -> dict[str, Any]:
        """Obtiene datos fundamentales y métricas clave de la empresa (OVERVIEW)."""
        clean_ticker = ticker.split(".")[0].upper()
        data = await self._fetch({"function": "OVERVIEW", "symbol": clean_ticker})
        if not data or "Symbol" not in data:
            raise RuntimeError(f"Alpha Vantage no devolvió datos fundamentales para {ticker}")

        return {
            "symbol": data.get("Symbol", clean_ticker),
            "name": data.get("Name", ""),
            "description": data.get("Description", ""),
            "sector": data.get("Sector", ""),
            "industry": data.get("Industry", ""),
            "market_cap": float(data.get("MarketCapitalization") or 0.0),
            "pe_ratio": float(data.get("PERatio") or 0.0),
            "pb_ratio": float(data.get("PriceToBookRatio") or 0.0),
            "dividend_yield": float(data.get("DividendYield") or 0.0),
            "eps": float(data.get("EPS") or 0.0),
            "source": self.name,
        }
