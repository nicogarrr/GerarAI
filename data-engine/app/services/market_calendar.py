"""¿Abre la bolsa ese día? Calendarios oficiales de Madrid, Nueva York y Londres.

No cambia el scheduler ni la cadencia de ningún job: solo responde, por ticker,
si su bolsa abre ese día (lo usan la pasada diaria de DCA y las alertas de
precio para no evaluar en días sin sesión). Usa ``exchange_calendars``
(Apache-2.0, Python puro), que publica los festivos y sesiones de cada bolsa:
Viernes Santo, Lunes de Pascua y 26 de diciembre en Madrid y Londres, los bank
holidays británicos, Acción de Gracias o el 4 de julio en Nueva York, etc.

Rango cubierto: desde 2000 hasta dos años después del año en curso. Fuera de
él, o con una bolsa desconocida, se lanza ``ValueError`` en vez de adivinar.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Any

import exchange_calendars

# Códigos ISO 10383 (MIC) admitidos: Bolsa de Madrid, NYSE y London Stock Exchange.
SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"XMAD", "XNYS", "XLON"})
CALENDAR_START = date(2000, 1, 1)


@lru_cache(maxsize=len(SUPPORTED_EXCHANGES))
def _calendar(code: str) -> Any:
    end = date(date.today().year + 2, 12, 31)
    return exchange_calendars.get_calendar(code, start=CALENDAR_START.isoformat(), end=end.isoformat())


def is_market_open_day(exchange: str, day: date) -> bool:
    """True si ``exchange`` (XMAD, XNYS o XLON) tiene sesión el día ``day``.

    Fines de semana y festivos de esa bolsa dan False. Un ``datetime`` cuenta
    por su fecha (sin conversión de zona: la fecha ya es la del mercado).
    """
    code = (exchange or "").strip().upper()
    if code not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Bolsa no soportada: {exchange!r} (admitidas: {', '.join(sorted(SUPPORTED_EXCHANGES))})"
        )
    session = date(day.year, day.month, day.day)
    calendar = _calendar(code)
    first = calendar.first_session.date()
    last = calendar.last_session.date()
    if session < CALENDAR_START or session > date(last.year, 12, 31) or session < date(first.year, 1, 1):
        raise ValueError(f"Fecha fuera del calendario de {code}: {session.isoformat()}")
    return bool(calendar.is_session(session.isoformat()))


# Sufijo del ticker (estilo Yahoo) -> bolsa. Sin sufijo, un ticker de EE. UU.
# (AAPL, BRK-B) va con el calendario de la NYSE (mismo que NASDAQ).
_SUFFIX_EXCHANGES: dict[str, str] = {"MC": "XMAD", "L": "XLON"}
_US_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


def exchange_for_ticker(ticker: str | None) -> str | None:
    """MIC de la bolsa del ticker (.MC -> XMAD, .L -> XLON, sin sufijo -> XNYS).

    ``None`` cuando no se sabe (otro sufijo, índices ``^``, divisas ``=X``,
    cripto ``BTC-USD``...): quien llama se comporta como siempre.
    """
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return None
    if "." in symbol:
        return _SUFFIX_EXCHANGES.get(symbol.rsplit(".", 1)[1])
    return "XNYS" if _US_TICKER.match(symbol) else None


def ticker_market_closed(ticker: str | None, day: date) -> bool:
    """True solo si la bolsa del ticker es conocida y ese día no tiene sesión.

    Bolsa desconocida o fecha fuera del calendario: False (se evalúa como hoy).
    """
    exchange = exchange_for_ticker(ticker)
    if exchange is None:
        return False
    try:
        return not is_market_open_day(exchange, day)
    except ValueError:
        return False
