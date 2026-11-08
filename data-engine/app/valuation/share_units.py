"""Escala de las acciones: emisores que etiquetan el número de acciones en miles sin decirlo.

Caso real (backtest PIT, 8-nov-2026): FRP Holdings (FRPH) etiqueta
``WeightedAverageNumberOfDilutedSharesOutstanding`` = 9.609 (son 9,6 millones, en miles), mientras la
portada (``dei:EntityCommonStockSharesOutstanding``) dice 9,5 millones y beneficio / BPA diluido también da
~9,6 millones. Con 9.609 acciones la capitalización salía 1.000 veces pequeña y no había TIR.

Regla general: si una referencia independiente (las acciones de la portada, o beneficio / BPA diluido del
mismo ejercicio) es entre 500 y 2.000 veces la cifra etiquetada, la cifra está en miles: se multiplica por
1.000 y se avisa. Fuera de esa banda no se toca (otras incoherencias se resuelven como hasta ahora).
"""
from __future__ import annotations

THOUSANDS_BAND = (500.0, 2000.0)


def rescale_shares(tagged: float | None, *references: float | None) -> tuple[float | None, str | None]:
    """(acciones, motivo) — motivo None si no se reescala."""
    if tagged is None or tagged <= 0:
        return tagged, None
    lo, hi = THOUSANDS_BAND
    for ref in references:
        if ref is not None and ref > 0 and lo <= ref / tagged <= hi:
            return tagged * 1000.0, (f"acciones etiquetadas en miles sin declararlo ({tagged:,.0f}): "
                                     f"la referencia independiente da {ref:,.0f}; se usa × 1.000")
    return tagged, None
