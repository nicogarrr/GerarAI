"""Tipos de cambio oficiales que el BCE no publica (GEL, TWD).

La tabla diaria del BCE (``eurofxref-daily``) no trae el lari georgiano ni el
nuevo dólar taiwanés. Sin esos tipos, una empresa que reporta en GEL (Georgia
Capital, CGEO.L) o en TWD (TSMC) no se puede valorar: la conversión precio →
divisa de reporte falla y el DCF y la TIR quedan bloqueados («fx_rate:GEL/GBP»,
«sin tipo de cambio USD→TWD»).

Fuentes, ambas oficiales, gratuitas y públicas, del banco central emisor de
cada divisa:

- GEL: Banco Nacional de Georgia (NBG), tipo oficial diario en JSON,
  ``https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/?date=YYYY-MM-DD``.
  Publica «lari por ``quantity`` unidades» de cada divisa (USD y EUR incluidos).
- TWD: Banco Central de la República de China (Taiwán, CBC), cierre diario
  NT$/US$ de su web, ``https://www.cbc.gov.tw/en/lp-700-2.html``; de respaldo,
  su API estadística (``BP01D01``, serie «新台幣NTD/USD»), que se actualiza
  semanalmente.

Nada se inventa: si la fuente no responde o cambia de formato, la divisa queda
sin tipo y el motivo se devuelve (y la etapa FX del refresco lo muestra).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.services.public_fetch import fetch_public_url_async

NBG_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/?date={day}"
CBC_DAILY_URL = "https://www.cbc.gov.tw/en/lp-700-2.html"
CBC_API_URL = "https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01"
USER_AGENT = "GerarAI/1.0 (tipos de cambio oficiales; contacto tab@tab.bot)"
TIMEOUT_SECONDS = 20

NBG_SOURCE = "NBG (Banco Nacional de Georgia), tipo oficial diario"
CBC_SOURCE = "CBC (Banco Central de Taiwán), cierre NT$/US$"

# Divisa -> feed oficial. Solo divisas que el BCE NO publica.
OFFICIAL_FEEDS: dict[str, str] = {"GEL": "nbg", "TWD": "cbc"}


@dataclass(frozen=True)
class OfficialQuote:
    """``units`` de ``currency`` por 1 ``per``, publicado por ``source``."""

    currency: str
    per: str
    units: Decimal
    rate_date: date
    source: str
    url: str


def _positive(raw: object) -> Decimal | None:
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def parse_nbg(payload: str | bytes, *, url: str = "") -> list[OfficialQuote]:
    """Lari por 1 USD y por 1 EUR del JSON del NBG (``rate`` / ``quantity``)."""
    data = json.loads(payload)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("NBG: respuesta sin la lista de tipos")
    quotes: list[OfficialQuote] = []
    for row in data[0].get("currencies") or []:
        code = str(row.get("code") or "").upper()
        if code not in {"USD", "EUR"}:
            continue
        rate = _positive(row.get("rate"))
        quantity = _positive(row.get("quantity"))
        stamp = str(row.get("validFromDate") or data[0].get("date") or "")[:10]
        if rate is None or quantity is None or not stamp:
            raise ValueError(f"NBG: tipo o fecha inválidos para {code}")
        quotes.append(
            OfficialQuote(
                currency="GEL",
                per=code,
                units=rate / quantity,
                rate_date=date.fromisoformat(stamp),
                source=NBG_SOURCE,
                url=url,
            )
        )
    if not quotes:
        raise ValueError("NBG: sin USD ni EUR en la respuesta")
    return quotes


_CBC_ROW = re.compile(
    r"<span>\s*(\d{4})/(\d{2})/(\d{2})\s*</span>\s*</td>\s*<td[^>]*NTD/USD[^>]*>\s*<span>\s*([0-9.,]+)\s*</span>",
    re.IGNORECASE,
)


def parse_cbc_daily(html: str, *, url: str = CBC_DAILY_URL) -> list[OfficialQuote]:
    """Cierres NT$/US$ de la tabla diaria del CBC, del más reciente al más antiguo."""
    quotes = []
    for year, month, day, raw in _CBC_ROW.findall(html):
        units = _positive(raw)
        if units is None:
            continue
        quotes.append(
            OfficialQuote("TWD", "USD", units, date(int(year), int(month), int(day)), CBC_SOURCE, url)
        )
    if not quotes:
        raise ValueError("CBC: la tabla NT$/US$ no está en la página (posible cambio de formato)")
    return sorted(quotes, key=lambda q: q.rate_date, reverse=True)


def parse_cbc_api(payload: str | bytes, *, url: str = CBC_API_URL) -> list[OfficialQuote]:
    """Serie NTD/USD de la API estadística del CBC (``BP01D01``)."""
    data = json.loads(payload)
    columns = [str(c.get("data") or "") for c in data["data"]["structure"]["Table1"]]
    try:
        col = next(i for i, name in enumerate(columns) if "NTD/USD" in name.upper()) + 1
    except StopIteration as exc:
        raise ValueError("CBC API: sin columna NTD/USD") from exc
    quotes = []
    for row in data["data"]["dataSets"]:
        units = _positive(row[col]) if len(row) > col else None
        stamp = str(row[0])
        if units is None or not re.fullmatch(r"\d{8}", stamp):
            continue
        day = datetime.strptime(stamp, "%Y%m%d").date()
        quotes.append(OfficialQuote("TWD", "USD", units, day, CBC_SOURCE + " (API estadística)", url))
    if not quotes:
        raise ValueError("CBC API: serie NTD/USD vacía")
    return sorted(quotes, key=lambda q: q.rate_date, reverse=True)


Fetcher = Callable[[str], Awaitable[str]]


async def _http_get(url: str) -> str:
    # Aunque los hosts son fijos, la descarga pasa por public_fetch: bloquea
    # IPs privadas, fija la IP resuelta y revalida cada redireccion.
    content, _content_type, _final_url = await fetch_public_url_async(
        url, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
    )
    return content.decode("utf-8", errors="replace")


async def fetch_official_quotes(
    currencies: Iterable[str],
    *,
    on: date,
    fetcher: Fetcher = _http_get,
) -> tuple[list[OfficialQuote], list[dict]]:
    """Cotizaciones oficiales (fecha <= ``on``) de las divisas pedidas que tienen feed.

    Devuelve las cotizaciones y los errores por divisa (nunca se descarta una
    divisa en silencio: la que no se obtiene sale con su motivo).
    """
    quotes: list[OfficialQuote] = []
    errors: list[dict] = []
    for currency in sorted({c.upper() for c in currencies}):
        feed = OFFICIAL_FEEDS.get(currency)
        if feed is None:
            continue
        found: list[OfficialQuote] = []
        reasons: list[str] = []
        attempts: list[tuple[str, Callable[[str, str], list[OfficialQuote]]]]
        if feed == "nbg":
            attempts = [(NBG_URL.format(day=on.isoformat()), lambda text, u: parse_nbg(text, url=u))]
        else:
            attempts = [
                (CBC_DAILY_URL, lambda text, u: parse_cbc_daily(text, url=u)),
                (CBC_API_URL, lambda text, u: parse_cbc_api(text, url=u)),
            ]
        for url, parse in attempts:
            try:
                parsed = [q for q in parse(await fetcher(url), url) if q.rate_date <= on]
            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
                reasons.append(f"{url}: {type(exc).__name__}: {str(exc)[:160]}")
                continue
            if parsed:
                found = parsed
                break
            reasons.append(f"{url}: sin tipo con fecha <= {on.isoformat()}")
        if not found:
            errors.append({"currency": currency, "provider": feed.upper(), "reason": "; ".join(reasons)})
            continue
        # Un tipo por divisa de referencia: el más reciente.
        latest: dict[str, OfficialQuote] = {}
        for quote in found:
            if quote.per not in latest or quote.rate_date > latest[quote.per].rate_date:
                latest[quote.per] = quote
        quotes.extend(latest.values())
    return quotes, errors


@dataclass(frozen=True)
class BaseRate:
    """``rate`` = unidades de la divisa base por 1 ``currency`` (como las filas BCE)."""

    currency: str
    rate: Decimal
    rate_date: date
    source: str


def to_base_rates(
    quotes: Iterable[OfficialQuote],
    *,
    base_currency: str,
    base_per: dict[str, Decimal],
    base_per_date: date | None,
    base_per_source: str = "ECB",
) -> dict[str, BaseRate]:
    """Pasa cada cotizacion oficial a «base por 1 divisa».

    Directo si la fuente cotiza contra la base (lari por EUR con base EUR).
    Si no, cruzado con el tipo BCE de la divisa de referencia
    (``base_per[per]`` = base por 1 ``per``): TWD→EUR = (EUR/USD BCE) / (TWD/USD CBC).
    La fecha del cruce es la más antigua de las dos patas.
    """
    base = base_currency.upper()
    out: dict[str, BaseRate] = {}
    for quote in sorted(quotes, key=lambda q: q.per != base):
        if quote.currency in out:
            continue
        if quote.per == base:
            out[quote.currency] = BaseRate(
                quote.currency, Decimal("1") / quote.units, quote.rate_date, quote.source
            )
            continue
        leg = base_per.get(quote.per)
        if leg is None or leg <= 0 or base_per_date is None:
            continue
        out[quote.currency] = BaseRate(
            quote.currency,
            leg / quote.units,
            min(quote.rate_date, base_per_date),
            f"{quote.source} + {base_per_source} {quote.per}/{base}",
        )
    return out
