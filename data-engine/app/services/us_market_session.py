"""Regla única de la sesión bursátil US (horario de Nueva York).

Una barra del día en curso solo es cierre oficial cuando la sesión US ya
terminó. La regla (zona NY, cierre 16:30, fin de semana cerrado) la usaban
``market_close_sync`` y ``propicks_price_service`` copiada a mano; aquí vive
una sola vez. ``market_close_sync`` importa de ``propicks_price_service``,
así que el módulo neutro evita el ciclo.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
#: Una barra del día en curso solo es cierre cuando la sesión US ya terminó.
SESSION_CLOSED_AFTER = (16, 30)


def session_open(now: datetime) -> bool:
    """True mientras la sesión regular US está abierta (lunes a viernes, antes del cierre)."""
    local = now.astimezone(NY_TZ)
    if local.weekday() >= 5:
        return False
    return (local.hour, local.minute) < SESSION_CLOSED_AFTER
