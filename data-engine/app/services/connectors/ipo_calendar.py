"""Calendario publico de salidas a bolsa (IPOs) de NASDAQ.

Mismo patron que ``earnings_calendar``: lectura del calendario publico
(``api.nasdaq.com/api/ipo/calendar``, mensual) sin API key, con cabeceras de
navegador, cliente asincrono inyectable en tests y degradacion a
``status="unavailable"`` en lugar de excepcion. La respuesta declara su
origen: "Source: EDGAR(R) Online".

Cobertura declarada: solo salidas a bolsa en mercados de EE. UU. (NASDAQ,
NYSE...) que NASDAQ publica; el resto de mercados no aparece y la pagina lo
dice. Las fechas de las salidas proximas son las PREVISTAS por la fuente
(``expectedPriceDate``): pueden moverse y aqui no se corrige ni se estima
nada. ``filed`` (solicitudes sin fecha) y ``withdrawn`` (retiradas) no son
eventos de calendario y no se muestran.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from app.services.connectors.earnings_calendar import _get_json

IPO_URL = "https://api.nasdaq.com/api/ipo/calendar"

# Meses consultados por defecto: el actual y el siguiente (las salidas
# proximas del mes en curso ya pueden haber pasado a mitad de mes).
DEFAULT_MONTHS = 2
MAX_MONTHS = 3

SOURCE_NASDAQ_IPO = "Calendario de IPOs de NASDAQ"


def first_of_month(day: date) -> date:
    return date(day.year, day.month, 1)


def add_months(day: date, months: int) -> date:
    """Primer dia del mes `months` meses despues del mes de `day`."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def _parse_us_date(value: Any) -> date | None:
    """NASDAQ entrega las fechas del calendario de IPOs como ``MM/DD/YYYY``."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        month, day, year = text.split("/")
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def normalize_ipo_row(row: dict[str, Any], status: str) -> dict[str, Any]:
    """Normaliza una fila de salida a bolsa (``upcoming`` o ``priced``).

    Todo va tal cual lo trae la fuente: el precio puede ser un rango
    ("15.00-17.00") en las proximas o el precio final en las fijadas; sin
    ticker propuesto o sin fecha el evento se conserva con None (la fuente
    aun no lo publica) y la pagina lo dice.
    """
    symbol = str(row.get("proposedTickerSymbol") or "").strip().upper()
    day = _parse_us_date(row.get("pricedDate") or row.get("expectedPriceDate"))
    return {
        "deal_id": row.get("dealID"),
        "symbol": symbol or None,
        "company": row.get("companyName") or None,
        "exchange": row.get("proposedExchange") or None,
        "date": day.isoformat() if day else None,
        "price": str(row.get("proposedSharePrice") or "").strip() or None,
        "shares": row.get("sharesOffered") or None,
        "offer_amount": row.get("dollarValueOfSharesOffered") or None,
        "status": status,
        "source": SOURCE_NASDAQ_IPO,
    }


def _payload_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Filas ``priced`` + ``upcoming`` del mes. ``rows: null`` es "sin
    registros" (la API lo declara con codigo 1002), NO un fallo."""
    data = payload.get("data") or {}
    events = [
        normalize_ipo_row(row, "priced")
        for row in (data.get("priced") or {}).get("rows") or []
        if isinstance(row, dict)
    ]
    upcoming = (data.get("upcoming") or {}).get("upcomingTable") or {}
    events.extend(
        normalize_ipo_row(row, "upcoming")
        for row in upcoming.get("rows") or []
        if isinstance(row, dict)
    )
    # Una operacion en transicion puede salir en las dos listas del mismo
    # mes: gana ``priced`` (fecha y precio reales).
    seen: dict[Any, dict[str, Any]] = {}
    for event in sorted(events, key=lambda e: 0 if e["status"] == "priced" else 1):
        key = event["deal_id"] or (event["symbol"], event["company"], event["date"])
        seen.setdefault(key, event)
    return list(seen.values())


async def fetch_ipo_month(
    month: date,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Salidas a bolsa de un mes, o ``status="unavailable"`` si NASDAQ no responde."""
    first = first_of_month(month)
    payload = await _get_json(IPO_URL, {"date": f"{first.year:04d}-{first.month:02d}"}, client)
    if not payload:
        return {
            "status": "unavailable",
            "month": f"{first.year:04d}-{first.month:02d}",
            "events": [],
            "errors": [f"{first.year:04d}-{first.month:02d}: calendario de IPOs no disponible"],
        }
    events = _payload_events(payload)
    return {
        "status": "ok",
        "month": f"{first.year:04d}-{first.month:02d}",
        "events": events,
        "errors": [],
    }


async def fetch_ipo_calendar(
    months: list[date],
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Agrega varios meses en paralelo; los meses que fallan van a ``errors``.

    Misma semantica que el resto del conector: ``unavailable`` solo si
    ningun mes respondio, ``partial`` si fallaron algunos. Los eventos van
    ordenados por fecha (las filas sin fecha de la fuente, al final).
    """
    unique = sorted({first_of_month(m) for m in months})[:MAX_MONTHS]
    if not unique:
        return {"status": "ok", "months": [], "count": 0, "events": [], "errors": []}
    per_month = await asyncio.gather(*(fetch_ipo_month(m, client) for m in unique))
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for result in per_month:
        events.extend(result["events"])
        errors.extend(result["errors"])
    events.sort(key=lambda e: (e["date"] is None, e["date"] or "", e["company"] or ""))
    answered = sum(1 for r in per_month if r["status"] == "ok")
    if answered == 0:
        status = "unavailable"
    elif answered < len(per_month):
        status = "partial"
    else:
        status = "ok"
    return {
        "status": status,
        "months": [r["month"] for r in per_month],
        "count": len(events),
        "events": events,
        "errors": errors,
    }
