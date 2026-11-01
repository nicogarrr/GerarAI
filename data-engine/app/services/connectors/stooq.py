"""Unauthenticated Stooq daily historical OHLCV, as an optional price fallback.

Stooq is an unofficial provider. A challenge page or No data is never a price;
the caller receives an error and must keep an honest unavailable state.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

# Clave en el registry de salud de fuentes. "No data" (simbolo sin barras en
# el rango) y 400/404 son dato por ticker y NO degradan; una challenge page
# HTML, un CSV con esquema distinto o un 5xx SI (la fuente cambio o cayo).
REGISTRY_KEY = "stooq"


class StooqClient:
    name = "stooq"
    base_url = "https://stooq.com/q/d/l/"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    def configured(self) -> bool:
        return True

    async def daily_prices(self, ticker: str, *, start: date, end: date) -> list[dict[str, Any]]:
        """Read daily bars, preserving Stooq's symbol and observed trading date."""
        if start > end:
            raise ValueError("start must not be after end")
        from app.services.listing_identity import BASIC_FIT

        symbol = ticker.strip().lower()
        if symbol == BASIC_FIT.yahoo.lower():
            symbol = BASIC_FIT.stooq
        if not symbol or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-^" for c in symbol):
            raise ValueError("Invalid Stooq symbol")
        params = {"s": symbol, "i": "d", "d1": start.strftime("%Y%m%d"), "d2": end.strftime("%Y%m%d")}
        registry = get_data_source_registry()
        started = time.perf_counter()
        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    response = await client.get(self.base_url, params=params)
            else:
                response = await self.client.get(self.base_url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                # Simbolo sin cobertura: la fuente respondio; no se degrada.
                raise
            registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
            raise
        except httpx.TransportError as exc:
            registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            raise
        text = response.text.strip()
        if text.lower().startswith("no data"):
            # Respuesta valida: sin barras para ese simbolo/rango. Exito.
            registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
            return []
        if "<html" in text[:300].lower():
            registry.record_failure(REGISTRY_KEY, "respuesta HTML (challenge page)")
            raise RuntimeError("Stooq returned HTML instead of price data")
        rows = csv.DictReader(io.StringIO(text))
        if rows.fieldnames != ["Date", "Open", "High", "Low", "Close", "Volume"]:
            registry.record_failure(REGISTRY_KEY, "esquema CSV inesperado")
            raise RuntimeError("Stooq returned an unexpected CSV schema")
        result = []
        for row in rows:
            try:
                day = date.fromisoformat(row["Date"])
                prices = {key.lower(): Decimal(row[key]) for key in ("Open", "High", "Low", "Close")}
                volume = int(row["Volume"])
                if (
                    not (start <= day <= end)
                    or any(p <= 0 or not p.is_finite() for p in prices.values())
                    or volume < 0
                ):
                    raise ValueError("Invalid date, price or volume")
            except (ValueError, InvalidOperation, TypeError, KeyError) as exc:
                registry.record_failure(REGISTRY_KEY, "fila OHLCV invalida")
                raise RuntimeError("Stooq returned an invalid OHLCV row") from exc
            result.append(
                {
                    "date": day,
                    **prices,
                    "volume": volume,
                    "source": self.name,
                    "source_url": str(response.url),
                    "symbol": symbol,
                }
            )
        registry.record_success(REGISTRY_KEY, (time.perf_counter() - started) * 1000)
        return result
