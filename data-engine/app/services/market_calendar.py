"""¿Abre la bolsa ese día? Calendarios oficiales de Madrid, Nueva York y Londres.

Solo un helper: NO está cableado en el scheduler ni en ningún job (cuándo se
evalúan DCA y alertas es decisión de Nico). Usa ``exchange_calendars``
(Apache-2.0, Python puro), que publica los festivos y sesiones de cada bolsa:
Viernes Santo, Lunes de Pascua y 26 de diciembre en Madrid y Londres, los bank
holidays británicos, Acción de Gracias o el 4 de julio en Nueva York, etc.

Rango cubierto: desde 2000 hasta dos años después del año en curso. Fuera de
él, o con una bolsa desconocida, se lanza ``ValueError`` en vez de adivinar.
"""

from __future__ import annotations

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
