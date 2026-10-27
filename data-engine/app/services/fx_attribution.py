"""Reparto de la G/P latente en divisa base entre efecto precio y efecto divisa.

Para una posicion en divisa nativa (USD) vista en divisa base (EUR):

- efecto precio = G/P nativa x tipo de hoy (lo que habria cambiado el valor en
  EUR si el tipo no se hubiera movido desde la compra);
- efecto divisa = G/P en base - efecto precio = coste nativo x tipo de hoy -
  coste en base (cada compra a su tipo de su fecha).

Ambos suman exactamente la G/P en base. Con la misma divisa el efecto divisa
es 0. Sin tipo de hoy o sin coste en base no se inventa nada: None.
"""

from __future__ import annotations

from decimal import Decimal


def split_unrealized_pnl(
    *,
    unrealized_native: Decimal | float | None,
    unrealized_base: Decimal | float | None,
    fx_rate_now: Decimal | float | None,
) -> tuple[float | None, float | None]:
    """(efecto_precio_base, efecto_divisa_base) o (None, None) si falta algo."""
    if unrealized_native is None or unrealized_base is None or fx_rate_now is None:
        return None, None
    rate = Decimal(str(fx_rate_now))
    if rate <= 0:
        return None, None
    price_effect = Decimal(str(unrealized_native)) * rate
    fx_effect = Decimal(str(unrealized_base)) - price_effect
    return float(price_effect), float(fx_effect)
