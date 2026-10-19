"""Próxima fecha de resultados estimada vía Yahoo Finance (no oficial, €0).

Yahoo publica por símbolo la próxima fecha prevista de resultados
(``Ticker.calendar["Earnings Date"]``), incluso cuando está a meses vista y
el calendario confirmado de NASDAQ (ventana de 31 días) aún no la recoge —
p.ej. UNH el 19-10-2026: reportó el 13-10 y la siguiente estimada es
12-01-2027. La fecha es una ESTIMACIÓN de Yahoo hasta que la empresa
confirma: el caller la etiqueta siempre como no oficial.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any


def _estimate_from_calendar(calendar: Any, today: date) -> date | None:
    if not isinstance(calendar, dict):
        return None
    raw = calendar.get("Earnings Date")
    values = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    candidates: list[date] = []
    for item in values:
        day = item if isinstance(item, date) and not isinstance(item, bool) else None
        if day is None:
            try:
                day = date.fromisoformat(str(item)[:10])
            except ValueError:
                continue
        if day >= today:
            candidates.append(day)
    return min(candidates) if candidates else None


def fetch_next_earnings_dates(
    symbols: list[str],
    today: date | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, str]:
    """Símbolo -> fecha ISO estimada por Yahoo. Los fallos se omiten (N/D).

    ``deadline_monotonic`` frena el barrido secuencial devolviendo lo ya
    encontrado: un Yahoo lento nunca bloquea al caller más allá del presupuesto.
    """
    import yfinance as yf

    today = today or date.today()
    found: dict[str, str] = {}
    for symbol in symbols:
        if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
            break
        try:
            day = _estimate_from_calendar(yf.Ticker(symbol).calendar, today)
        except Exception:  # noqa: BLE001 - un símbolo que falla no rompe al resto
            continue
        if day is not None:
            found[symbol] = day.isoformat()
    return found
