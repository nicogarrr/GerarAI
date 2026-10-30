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
MONTHS_ES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sept", "oct", "nov", "dic",
)


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
