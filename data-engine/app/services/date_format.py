"""Fechas visibles para el usuario en español (es-ES).

Réplica backend de ``formatDate``/``formatMarketDate`` de ``lib/format.ts``:
«30 sept 2026». Estos textos se persisten en títulos y descripciones de
documentos y eventos: deben nacer ya legibles, no depender de que cada
consumidor formatee. Una fecha ISO cruda («2026-09-30») en UI es un bug de
contenido (auditoría F1).
"""

from __future__ import annotations

from datetime import date, datetime

# Meses abreviados igual que Intl.DateTimeFormat('es-ES', {month: 'short'}).
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTHS_ES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sept", "oct", "nov", "dic",
)


def _as_day(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def format_date_en(value: date | datetime | str | None) -> str | None:
    """Fecha corta en-US («Sep 30, 2026»), como ``formatDate`` en inglés. None si no es fecha."""
    parsed = _as_day(value)
    if parsed is None:
        return None
    return f"{MONTHS_EN[parsed.month - 1]} {parsed.day}, {parsed.year}"


def readable_date(value: date | datetime | str | None, language: str = "es") -> str:
    """Fecha visible en el idioma pedido; si no es fecha reconocible, el texto tal cual."""
    formatted = format_date_en(value) if language == "en" else format_date_es(value)
    return formatted if formatted is not None else ("" if value is None else str(value))


def format_date_es(value: date | datetime | str | None) -> str | None:
    """Fecha corta es-ES («30 sept 2026»). None si no es fecha reconocible.

    Acepta ``date``/``datetime`` o cadena ISO (``YYYY-MM-DD`` o datetime ISO);
    la cadena se interpreta como día de calendario, sin zonas horarias.
    """
    if value is None:
        return None
    parsed: date | None = None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Solo la parte de fecha: un datetime ISO («2026-09-30T12:00:00…»)
        # se trunca a su día de calendario declarado.
        day = text[:10]
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            return None
    if parsed is None:
        return None
    return f"{parsed.day} {MONTHS_ES[parsed.month - 1]} {parsed.year}"
