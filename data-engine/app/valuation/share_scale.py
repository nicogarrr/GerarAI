"""Escala de recuentos de acciones y magnitudes por accion (hechos SEC).

Algunos emisores etiquetan en XBRL la media ponderada de acciones en MILES
(el ``decimals`` dice -3 pero el valor no esta multiplicado): ONDS declara
221.769 acciones diluidas en el 10-K de FY2025 y 461.706 en el 10-Q de 1T26,
cuando su portada (dei:EntityCommonStockSharesOutstanding) dice 380,8 M.
companyfacts no trae ``decimals``, asi que la escala se detecta contrastando
con otro recuento de la MISMA empresa en un cierre cercano (portada / acciones
en circulacion primero, luego el resto de recuentos). Un recuento entre ~333 y
~3.000 veces menor que la referencia esta en miles; entre ~333.000 y ~3 M de
veces, en millones. Ningun emisor real cambia su numero de acciones x1.000
entre dos cierres cercanos: lo que cae ahi es escala, no historia.

El mismo error en un importe POR ACCION (BPA de 17,6 M $ en un 10-Q de la
SPAC de ASTS, 2020) se detecta contra beneficio neto / acciones: un BPA cuyo
beneficio implicito es cientos de veces el beneficio declarado no es usable.

Todo es general (sin tickers) y deja la referencia en la traza.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

#: Escalas que un emisor confunde al etiquetar (miles, millones).
SHARE_SCALE_FACTORS: tuple[float, ...] = (1_000.0, 1_000_000.0)
#: Banda multiplicativa alrededor de cada escala: referencia / valor dentro de
#: [escala / 3, escala x 3] => escala. Deja sitio a ampliaciones reales de
#: capital de hasta x3 entre la referencia y el valor (ONDS 2025: x1,7).
SHARE_SCALE_BAND = 3.0
#: Distancia maxima entre el cierre del recuento y el de la referencia.
SHARE_SCALE_REFERENCE_MAX_DAYS = 400
#: Para un BPA la referencia (beneficio neto y acciones) puede estar mas lejos:
#: el error es de cientos de veces, no de un ejercicio.
PER_SHARE_REFERENCE_MAX_DAYS = 3 * 366
#: Beneficio implicito (BPA x acciones) / beneficio declarado a partir del cual
#: el BPA no es usable (escala erronea).
PER_SHARE_MAX_IMPLIED_RATIO = SHARE_SCALE_FACTORS[0] / SHARE_SCALE_BAND


def period_end(period: str | None) -> date | None:
    """Fecha de cierre de un ``period`` (``2025-12-31:FY``, ``2025-12-31:DEI``)."""
    if not period:
        return None
    try:
        return date.fromisoformat(str(period)[:10])
    except ValueError:
        return None


def share_scale_factor(value: float | None, reference: float | None) -> float:
    """Factor por el que hay que multiplicar ``value`` (1.0 = escala correcta).

    Solo corrige hacia arriba: un recuento en miles siempre es MENOR que el
    real. Si la referencia es la erronea (menor que el valor), no se toca.
    """
    if value is None or reference is None:
        return 1.0
    if not (math.isfinite(value) and math.isfinite(reference)) or value <= 0 or reference <= 0:
        return 1.0
    ratio = reference / value
    for factor in SHARE_SCALE_FACTORS:
        if factor / SHARE_SCALE_BAND <= ratio <= factor * SHARE_SCALE_BAND:
            return factor
    return 1.0


def per_share_scale_is_wrong(
    per_share: float | None, net_income: float | None, shares: float | None
) -> bool:
    """True si ``per_share`` x ``shares`` es cientos de veces ``net_income``."""
    if per_share is None or net_income is None or shares is None:
        return False
    if not all(math.isfinite(x) for x in (per_share, net_income, shares)):
        return False
    if shares <= 0 or net_income == 0 or per_share == 0:
        return False
    implied = abs(per_share) * shares
    return implied / abs(net_income) >= PER_SHARE_MAX_IMPLIED_RATIO


@dataclass(frozen=True)
class ShareScale:
    """Correccion de escala aplicada a un recuento, con su referencia."""

    factor: float
    reference_metric: str
    reference_value: float
    reference_period: str | None
    reference_fact_id: int | None

    def as_trace(self) -> dict:
        return {
            "factor": self.factor,
            "method": (
                f"escala corregida x{self.factor:g}: recuento declarado en "
                f"{'miles' if self.factor == 1_000.0 else 'millones'} "
                f"(contraste con {self.reference_metric} {self.reference_period})"
            ),
            "reference_metric": self.reference_metric,
            "reference_value": self.reference_value,
            "reference_period": self.reference_period,
            "reference_fact_id": self.reference_fact_id,
        }
