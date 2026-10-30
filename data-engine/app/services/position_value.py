"""Valor de una posicion en su moneda base, o None si no se conoce.

``market_value`` es el valor en la moneda NATIVA de la posicion. Solo se puede
sumar o etiquetar en la moneda base cuando existe ``market_value_base`` o
cuando la posicion ya esta en la base (nativa == base). Un nativo en otra
divisa sin tipo de cambio, o una valoracion suspendida, es desconocido: nunca
se mezcla con valores en base ni se rotula con la moneda base.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def position_base_value(position: Any) -> Decimal | None:
    if getattr(position, "valuation_hold_reason", None):
        return None
    if position.market_value_base is not None:
        return Decimal(position.market_value_base)
    base = position.base_currency or "EUR"
    if (position.currency or base) == base and position.market_value is not None:
        return Decimal(position.market_value)
    return None
