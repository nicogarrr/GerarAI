"""Yahoo Finance chart API (sin key): cotizaciones y eventos de dividendo/split.

Sustituto gratuito del proveedor FMP (eliminado: su key está muerta) para
precios y acciones corporativas. La chart API exige User-Agent de navegador
y no requiere autenticación. Los errores se propagan como excepciones para
que el caller pueda pasar al siguiente proveedor de la cadena.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

# Yahoo nombra las clases de acciones US con guion (BRK-B), no con punto
# (BRK.B, convención de Finnhub y del master). Las bolsas no-US llevan
# sufijo de DOS letras (.MC, .AS, .TO, .SW, .DE); la clase US es UNA letra
# A o B, así que el patrón no colisiona con sufijos de bolsa. Verificado
# contra la chart API el 2026-10-19: BRK.B da 404 y BRK-B devuelve serie.
_SHARE_CLASS_DOTTED = re.compile(r"^([A-Z]{1,5})\.([AB])$")


def yahoo_chart_symbol(symbol: str) -> str:
    """Símbolo de la chart API de Yahoo para el ticker pedido.

    Convierte la clase US en notación de punto (BRK.B) a la notación de
    guion que Yahoo exige (BRK-B); cualquier otro símbolo pasa intacto.
    """
    normalized = symbol.strip().upper()
    match = _SHARE_CLASS_DOTTED.fullmatch(normalized)
    return f"{match.group(1)}-{match.group(2)}" if match else normalized



def _with_exchange_timezone(rows: list[Any], meta: Any) -> list[dict[str, Any]]:
    """Copia cada evento con la zona horaria de su bolsa.

    Yahoo fecha los eventos con el epoch de la apertura LOCAL (10:00 en
    Sydney = 23:00 UTC del dia anterior); sin la zona, la fecha UTC cae un
    dia antes en ASX/NZX."""
    tz = meta.get("exchangeTimezoneName") if isinstance(meta, dict) else None
    tz = tz if isinstance(tz, str) and tz.strip() else None
    return [{**row, "exchangeTimezoneName": tz} for row in rows if isinstance(row, dict)]

class YahooFinanceClient:
    name = "yahoo"
    base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }

    def configured(self) -> bool:
        # La chart API de Yahoo no necesita key: siempre disponible.
        return True

    async def _chart(self, ticker: str, *, events: bool = False, extended: bool = False, recent_daily: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {"range": "max", "interval": "1d"}
        if recent_daily:
            params = {"interval": "1d", "range": "5d"}
        if extended:
            params = {"includePrePost": "true", "interval": "1m", "range": "1d"}
        if events:
            params = {
                "period1": 0,
                "period2": int(time.time()) + 86400,
                "interval": "1d",
                "events": "div|split",
            }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/{yahoo_chart_symbol(ticker)}", params=params, headers=self.headers
            )
            response.raise_for_status()
            payload = response.json()
        result = payload.get("chart", {}).get("result") if isinstance(payload, dict) else None
        if not result:
            raise RuntimeError("Yahoo returned an empty chart")
        return result[0]

    async def extended_chart(self, ticker: str) -> dict[str, Any]:
        """Intraday candles and session boundaries, including extended hours."""
        return await self._chart(ticker, extended=True)

    async def recent_daily_chart(self, ticker: str) -> dict[str, Any]:
        """Dated raw daily closes, used only to date a matching previousClose."""
        return await self._chart(ticker, recent_daily=True)

    async def quote(self, ticker: str) -> dict[str, Any]:
        """Meta de cotización (regularMarketPrice, previousClose, ...)."""
        node = await self._chart(ticker)
        meta = node.get("meta") or {}
        if not isinstance(meta, dict) or not meta.get("regularMarketPrice"):
            raise RuntimeError("Yahoo returned no market price")
        return meta

    async def dividends(self, ticker: str) -> list[dict[str, Any]]:
        """Eventos de dividendo crudos ({date: epoch, amount, dividends})."""
        node = await self._chart(ticker, events=True)
        events = node.get("events") or {}
        rows = list((events.get("dividends") or {}).values())
        return _with_exchange_timezone(rows, node.get("meta"))

    async def dividend_events(self, ticker: str) -> dict[str, Any]:
        """Dividendos crudos + divisa de cotizacion del LISTADO consultado.

        ``meta.currency`` es la divisa de cotizacion de ese simbolo (CHF para
        NOVN.SW), que es la de los eventos de dividendo del chart. No es la
        divisa de reporte de la empresa. ``currency`` es None si Yahoo no la
        informa."""
        node = await self._chart(ticker, events=True)
        events = node.get("events") or {}
        rows = list((events.get("dividends") or {}).values())
        meta = node.get("meta") or {}
        currency = meta.get("currency") if isinstance(meta, dict) else None
        return {
            "rows": _with_exchange_timezone(rows, meta),
            "currency": currency if isinstance(currency, str) and currency.strip() else None,
        }

    async def splits(self, ticker: str) -> list[dict[str, Any]]:
        """Eventos de split crudos ({date: epoch, numerator, denominator, splitRatio})."""
        node = await self._chart(ticker, events=True)
        events = node.get("events") or {}
        rows = list((events.get("splits") or {}).values())
        return _with_exchange_timezone(rows, node.get("meta"))
