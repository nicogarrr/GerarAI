"""Frescura del último cierre guardado (MarketPrice / Position.as_of).

Política del dueño (#2884): techo estricto de 24 h, sin excepción de fin de
semana. Con precios fechados por día (sin hora), eso equivale a «solo hoy»: el
cierre de hoy es actual y el de ayer ya no.

``MARKET_PRICE_MAX_AGE_DAYS`` sigue aceptándose por compatibilidad, pero no
puede ampliar el techo (un 3 heredado no vuelve «actual» el cierre de ayer).
El valor 0 significa «solo hoy», como antes de #2884; ``min(valor, 1)`` lo había
convertido en «ningún precio es actual, ni el de hoy».

A8 — el techo de 24 h se cuenta desde el CIERRE de la sesión, no desde la
medianoche UTC. Los cierres van fechados por la sesión de su bolsa (sin hora):
contar días naturales en UTC dejaba el cierre de ayer de Nueva York «sin
cotización vigente» desde las 00:00 UTC, horas antes de que abra la siguiente
sesión. Con la hora de cierre de la bolsa (``SESSION_CLOSE``), el cierre de la
sesión D es actual hasta 24 h después de ese cierre: vale toda la mañana antes
de la apertura y caduca en cuanto debería existir el de la sesión siguiente.
Sigue sin haber excepción de fin de semana (el cierre del viernes caduca el
sábado). Bolsa desconocida: regla anterior por días naturales.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.trading_sessions import US_EXCHANGES

_NY = ZoneInfo("America/New_York")
_US_CLOSE = (_NY, time(16, 0))

# Hora oficial de cierre de la subasta/sesión regular por etiqueta de bolsa
# (las etiquetas reales de ``companies.exchange``). Solo bolsas con hora
# inequívoca: «TSE» (Tokio o Toronto) queda fuera a propósito.
SESSION_CLOSE: dict[str, tuple[ZoneInfo, time]] = {
    **dict.fromkeys(US_EXCHANGES, _US_CLOSE),
    **{label: (ZoneInfo("Europe/Madrid"), time(17, 30)) for label in ("BME", "BOLSA DE MADRID", "XMAD", "MC", "MCE")},
    **{label: (ZoneInfo("Europe/London"), time(16, 30)) for label in ("LSE", "LONDON STOCK EXCHANGE", "XLON", "L")},
    **{label: (ZoneInfo("Europe/Berlin"), time(17, 30)) for label in ("XETRA", "XETR", "GER", "DE")},
    **{
        label: (ZoneInfo("Europe/Paris"), time(17, 30))
        for label in ("EURONEXT", "EURONEXT PARIS", "EPA", "PAR", "XPAR", "EURONEXT AMSTERDAM", "AMS", "XAMS", "EURONEXT BRUSSELS", "EBR")
    },
    **{label: (ZoneInfo("Europe/Zurich"), time(17, 30)) for label in ("SWISS EXCHANGE", "SIX", "XSWX", "EBS")},
    **{label: (ZoneInfo("America/Toronto"), time(16, 0)) for label in ("TORONTO STOCK EXCHANGE", "TSX", "XTSE")},
}

_STRICT_CEILING = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(UTC)


def market_price_is_stale(age_days: int, max_age_days: int) -> bool:
    """True si un precio de hace ``age_days`` días naturales ya no es actual."""
    window = min(max(max_age_days, 0), 1)  # techo #2884: como mucho 1 día natural
    # 0 y 1 significan «solo hoy»: un precio de hoy (age_days == 0) es actual.
    return age_days >= max(window, 1)


def session_close_at(price_date: date, exchange: str | None) -> datetime | None:
    """Instante (UTC) del cierre de la sesión ``price_date`` en su bolsa, o None."""
    close = SESSION_CLOSE.get((exchange or "").strip().upper())
    if close is None:
        return None
    zone, at = close
    return datetime.combine(price_date, at, tzinfo=zone).astimezone(UTC)


def close_is_stale(
    price_date: date,
    exchange: str | None,
    max_age_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    """True si el cierre de la sesión ``price_date`` ya no es actual en ``now``.

    Techo #2884 (24 h) contado desde el cierre de la bolsa. Sin hora de cierre
    conocida para la bolsa, días naturales como antes.
    """
    moment = (now or _now()).astimezone(UTC)
    closed_at = session_close_at(price_date, exchange)
    if closed_at is None:
        return market_price_is_stale((moment.date() - price_date).days, max_age_days)
    return moment - closed_at >= _STRICT_CEILING
