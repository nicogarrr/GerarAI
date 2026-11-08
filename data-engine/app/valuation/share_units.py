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


# --- ADR / ADS: recuentos en acciones ordinarias o en ADS -------------------------------------------
#
# Caso real (auditoría de valor intrínseco, 8-nov-2026): TSM tiene 25.930 M de acciones ORDINARIAS en sus
# 20-F (SEC) y 5.186 M de ADS en el agregador del último ejercicio (1 ADS = 5 ordinarias). La serie
# mezclaba las dos unidades: un desplome del 80 % que no existe y una capitalización ×5 en la TIR.
#
# Regla general (cualquier emisor con ratio ADR conocido, ningún ticker): los recuentos de la presentación
# oficial (SEC/ESEF) están en ordinarias. Un recuento de otra fuente está en ADS si, comparado con el
# recuento oficial más cercano, cuadra dividido por el ratio (±25 %) y NO cuadra tal cual. Fuera de esa
# banda no se toca nada (otra incoherencia no se tapa con el ratio).

ADS_MATCH_BAND = (0.75, 1.33)


def count_basis(value: float | None, ordinary_reference: float | None, ratio: float | None) -> str | None:
    """«ordinary», «ads» o None (no se puede decir) para un recuento de acciones."""
    if not value or value <= 0 or not ordinary_reference or ordinary_reference <= 0 or not ratio or ratio <= 1:
        return None
    lo, hi = ADS_MATCH_BAND
    as_is = value / ordinary_reference
    as_ads = value * ratio / ordinary_reference
    if lo <= as_is <= hi:
        return "ordinary"
    if lo <= as_ads <= hi:
        return "ads"
    return None


def nearest_reference(year: int, references: dict[int, float]) -> float | None:
    """El recuento oficial del ejercicio más cercano (empate: el anterior)."""
    if not references:
        return None
    best = min(references, key=lambda y: (abs(y - year), -y if y <= year else y))
    return references[best]
