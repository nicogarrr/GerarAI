"""Frescura del último cierre guardado (MarketPrice / Position.as_of).

Política del dueño (#2884): techo estricto de 24 h, sin excepción de fin de
semana. Con precios fechados por día (sin hora), eso equivale a «solo hoy»: el
cierre de hoy es actual y el de ayer ya no.

``MARKET_PRICE_MAX_AGE_DAYS`` sigue aceptándose por compatibilidad, pero no
puede ampliar el techo (un 3 heredado no vuelve «actual» el cierre de ayer).
El valor 0 significa «solo hoy», como antes de #2884; ``min(valor, 1)`` lo había
convertido en «ningún precio es actual, ni el de hoy».
"""

from __future__ import annotations


def market_price_is_stale(age_days: int, max_age_days: int) -> bool:
    """True si un precio de hace ``age_days`` días naturales ya no es actual."""
    window = min(max(max_age_days, 0), 1)  # techo #2884: como mucho 1 día natural
    # 0 y 1 significan «solo hoy»: un precio de hoy (age_days == 0) es actual.
    return age_days >= max(window, 1)
