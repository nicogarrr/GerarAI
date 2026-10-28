"""Unauthenticated Stooq daily historical OHLCV, as an optional price fallback.

Stooq is an unofficial provider. A challenge page or No data is never a price;
the caller receives an error and must keep an honest unavailable state.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


class StooqClient:
    name = "stooq"
    base_url = "https://stooq.com/q/d/l/"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    def configured(self) -> bool:
        return True

    async def daily_prices(
        self, ticker: str, *, start: date, end: date
    ) -> list[dict[str, Any]]:
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
        if self.client is None:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(self.base_url, params=params)
        else:
            response = await self.client.get(self.base_url, params=params)
        response.raise_for_status()
        text = response.text.strip()
        if text.lower().startswith("no data"):
            return []
        if "<html" in text[:300].lower():
            raise RuntimeError("Stooq returned HTML instead of price data")
        rows = csv.DictReader(io.StringIO(text))
        if rows.fieldnames != ["Date", "Open", "High", "Low", "Close", "Volume"]:
            raise RuntimeError("Stooq returned an unexpected CSV schema")
        result = []
        for row in rows:
            try:
                day = date.fromisoformat(row["Date"])
                prices = {key.lower(): Decimal(row[key]) for key in ("Open", "High", "Low", "Close")}
                volume = int(row["Volume"])
                if not (start <= day <= end) or any(p <= 0 or not p.is_finite() for p in prices.values()) or volume < 0:
                    raise ValueError("Invalid date, price or volume")
            except (ValueError, InvalidOperation, TypeError, KeyError) as exc:
                raise RuntimeError("Stooq returned an invalid OHLCV row") from exc
            result.append({"date": day, **prices, "volume": volume, "source": self.name, "source_url": str(response.url), "symbol": symbol})
        return result
