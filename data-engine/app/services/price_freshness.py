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
# (las etiquetas reales de ``companies.exchange``: Finnhub, Yahoo y el
# ``listingExchange`` de la Flex de IBKR, p. ej. BM, IBIS, SBF, AEB). Solo
# bolsas con hora inequívoca: «TSE» (Tokio o Toronto) se resuelve por el sufijo
# del ticker (``_SUFFIX_SESSION``). Sin calendario asiático en el código, Tokio
# y Hong Kong siguen con la regla de días naturales.
_MADRID_CLOSE = (ZoneInfo("Europe/Madrid"), time(17, 30))
_LONDON_CLOSE = (ZoneInfo("Europe/London"), time(16, 30))
_XETRA_CLOSE = (ZoneInfo("Europe/Berlin"), time(17, 30))
_EURONEXT_CLOSE = (ZoneInfo("Europe/Paris"), time(17, 30))
_SIX_CLOSE = (ZoneInfo("Europe/Zurich"), time(17, 30))
_TSX_CLOSE = (ZoneInfo("America/Toronto"), time(16, 0))
SESSION_CLOSE: dict[str, tuple[ZoneInfo, time]] = {
    **dict.fromkeys(US_EXCHANGES, _US_CLOSE),
    **dict.fromkeys(("BME", "BOLSA DE MADRID", "XMAD", "MC", "MCE", "BM"), _MADRID_CLOSE),
    **dict.fromkeys(("LSE", "LONDON STOCK EXCHANGE", "XLON", "L", "LSEETF"), _LONDON_CLOSE),
    **dict.fromkeys(("XETRA", "XETR", "GER", "DE", "IBIS", "IBIS2"), _XETRA_CLOSE),
    **dict.fromkeys(
        (
            "EURONEXT", "EURONEXT PARIS", "EPA", "PAR", "XPAR", "SBF",
            "EURONEXT AMSTERDAM", "AMS", "XAMS", "AEB",
            "EURONEXT BRUSSELS", "EBR", "ENEXT.BE",
        ),
        _EURONEXT_CLOSE,
    ),
    **dict.fromkeys(("SWISS EXCHANGE", "SIX", "XSWX", "EBS"), _SIX_CLOSE),
    **dict.fromkeys(("TORONTO STOCK EXCHANGE", "TSX", "XTSE"), _TSX_CLOSE),
}

# Sufijo Yahoo del ticker -> cierre. Desempata etiquetas ambiguas («TSE») y cubre
# etiquetas que no están en la tabla. Sin sufijo no se deduce nada.
_SUFFIX_SESSION: dict[str, tuple[ZoneInfo, time]] = {
    "MC": _MADRID_CLOSE,
    "L": _LONDON_CLOSE,
    "IL": _LONDON_CLOSE,
    "DE": _XETRA_CLOSE,
    "PA": _EURONEXT_CLOSE,
    "AS": _EURONEXT_CLOSE,
    "BR": _EURONEXT_CLOSE,
    "SW": _SIX_CLOSE,
    "TO": _TSX_CLOSE,
}


def _session_for(exchange: str | None, ticker: str | None) -> tuple[ZoneInfo, time] | None:
    head, dot, suffix = (ticker or "").strip().upper().rpartition(".")
    by_suffix = _SUFFIX_SESSION.get(suffix) if dot and head else None
    if by_suffix is not None:
        return by_suffix
    return SESSION_CLOSE.get((exchange or "").strip().upper())

_STRICT_CEILING = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(UTC)


def market_price_is_stale(age_days: int, max_age_days: int) -> bool:
    """True si un precio de hace ``age_days`` días naturales ya no es actual."""
    window = min(max(max_age_days, 0), 1)  # techo #2884: como mucho 1 día natural
    # 0 y 1 significan «solo hoy»: un precio de hoy (age_days == 0) es actual.
    return age_days >= max(window, 1)


def session_close_at(price_date: date, exchange: str | None, ticker: str | None = None) -> datetime | None:
    """Instante (UTC) del cierre de la sesión ``price_date`` en su bolsa, o None.

    El sufijo del ticker (``.TO``, ``.MC``…) manda sobre la etiqueta de bolsa:
    «TSE» es Toronto en la Flex de IBKR y Tokio en otros proveedores.
    """
    close = _session_for(exchange, ticker)
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
    ticker: str | None = None,
) -> bool:
    """True si el cierre de la sesión ``price_date`` ya no es actual en ``now``.

    Techo #2884 (24 h) contado desde el cierre de la bolsa. Sin hora de cierre
    conocida para la bolsa, días naturales como antes.
    """
    moment = (now or _now()).astimezone(UTC)
    closed_at = session_close_at(price_date, exchange, ticker)
    if closed_at is None:
        return market_price_is_stale((moment.date() - price_date).days, max_age_days)
    return moment - closed_at >= _STRICT_CEILING
