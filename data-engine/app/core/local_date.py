"""Fecha local del usuario (Europe/Madrid) en un servidor que corre en UTC.

Produccion corre con TZ=UTC (docker-compose.prod.yml). ``date.today()`` es la
fecha UTC: entre las 00:00 y la 01:00 (invierno) o las 02:00 (verano) de Madrid
todavia es «ayer», y una operacion o una fecha de hoy se rechazaba como
«futura». Las validaciones de «no futura» sobre fechas que escribe el usuario
usan esta fecha local.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

USER_TIMEZONE = ZoneInfo("Europe/Madrid")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def local_today(now: datetime | None = None) -> date:
    """Hoy en Europe/Madrid (no el dia UTC del servidor)."""
    instant = now if now is not None else _utc_now()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(USER_TIMEZONE).date()


def as_date(value: object) -> date | None:
    """Coerce datetime/date a date; cualquier otra cosa es «sin fecha» (None)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None
