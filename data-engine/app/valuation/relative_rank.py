"""Puesto relativo del valor justo: en qué quintil cae una empresa frente al resto.

Sustituye a la etiqueta binaria «infravalorada / sobrevalorada» (valor > precio),
que no anticipa nada. Medido (backtest gerarai-dcavalor1, 7-nov-2026, réplica
point-in-time del DCF estándar, 377 empresas del S&P 500, 2015-2026):

* «Infravalorada» bate al S&P 500 a 12 meses el 49 % de las veces, igual que el
  resto (49 %): el umbral valor = precio no separa nada, sobre todo porque el
  método sale de mediana a 0,61x el precio (el 76 % salían «sobrevaloradas»).
* Ordenar sí sirve: a 24 meses, el quintil más barato según valor/precio batió
  al más caro en +4,0 (2015-20) y +12,1 (2021-26) puntos de rentabilidad mediana
  frente al SPY.

El puesto se calcula sobre el cociente valor justo / precio, así que no depende
del nivel absoluto del método: si el valor justo se recalibra (todo sube o baja
a la vez), el orden y el quintil no cambian.

Comparables: todas las empresas con una valoración del motor guardada (su
última corrida, con el precio con el que se calculó, en la divisa del listado).
Con menos de ``MIN_PEERS`` comparables no hay puesto (``None``): un quintil de
diez empresas no dice nada. Quintil 1 = el 20 % más barato; 5 = el 20 % más caro.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters

MIN_PEERS = 30
#: Cocientes valor/precio fuera de este rango son datos rotos (unidades, splits), no comparables.
RATIO_BOUNDS = (0.02, 50.0)
EVIDENCE = {
    "horizon_months": 24,
    "cheapest_vs_dearest_quintile_pts": {"2015_2020": 4.0, "2021_2026": 12.1},
    "undervalued_label_beat_spy_12m": 0.49,
    "rest_beat_spy_12m": 0.49,
}


def _ratio(value: object, price: object) -> float | None:
    try:
        v = float(value)  # type: ignore[arg-type]
        p = float(price)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(v) and math.isfinite(p)) or v <= 0 or p <= 0:
        return None
    r = v / p
    return r if RATIO_BOUNDS[0] <= r <= RATIO_BOUNDS[1] else None


def value_ratio(fair_value: object, price: object) -> float | None:
    """Valor justo / precio comparable (misma divisa), o None si no es legible."""
    return _ratio(fair_value, price)


def rank_against(ratio: float | None, peers: Iterable[float]) -> dict[str, Any] | None:
    """Quintil (1 = más barato) de ``ratio`` dentro de ``peers`` (cocientes valor/precio).

    ``cheaper_than_pct``: % de comparables con un cociente MENOR (más caros que
    esta empresa). Con empates cuenta la mitad. None sin cociente o con pocos
    comparables.
    """
    if ratio is None or not math.isfinite(ratio) or ratio <= 0:
        return None
    values = sorted(r for r in peers if r is not None and math.isfinite(r) and r > 0)
    n = len(values)
    if n < MIN_PEERS:
        return None
    below = bisect_left(values, ratio)
    ties = bisect_right(values, ratio) - below
    share_below = (below + ties / 2) / n
    # Percentil de barato: 1,0 = el más barato. Quintil 1 = el 20 % más barato.
    quintile = min(5, max(1, 5 - math.floor(share_below * 5 + 1e-9)))
    return {
        "quintile": int(quintile),
        "cheaper_than_pct": int(round(share_below * 100)),
        "peers": n,
    }


def engine_peer_ratios(db: Session) -> dict[int, float]:
    """Cociente valor/precio de la última corrida del motor de cada empresa (por lotes).

    Usa el precio que la propia corrida guardó (``current_price``) y el valor
    por acción cotizada (``listed_value``): misma fecha y misma divisa. Las
    cotizaciones en subunidad (peniques) quedan fuera: su precio y su valor
    pueden ir en unidades distintas.
    """
    from app.models import Company, ValuationModel, ValuationOutput
    from app.services.fair_value_service import listed_value
    from app.valuation.currency import normalize_currency

    ranked = select(
        ValuationModel.id,
        func.row_number().over(
            partition_by=ValuationModel.company_id, order_by=ValuationModel.version.desc()
        ).label("rank"),
    ).where(
        ValuationModel.status.in_(("final", "draft", "insufficient_data")),
        *tenant_filters(db, ValuationModel),
    ).subquery()
    rows = db.execute(
        select(ValuationModel.company_id, ValuationModel.status, ValuationOutput.output_payload, Company.currency)
        .join(ranked, ValuationModel.id == ranked.c.id)
        .join(ValuationOutput, ValuationOutput.valuation_model_id == ValuationModel.id)
        .join(Company, Company.id == ValuationModel.company_id)
        .where(ranked.c.rank == 1)
    ).all()
    out: dict[int, float] = {}
    for company_id, status, payload, currency in rows:
        if status == "insufficient_data" or not isinstance(payload, dict) or int(company_id) in out:
            continue
        if normalize_currency(currency)[1] != 1:
            continue
        ratio = _ratio(listed_value(payload, fallback=payload), payload.get("current_price"))
        if ratio is not None:
            out[int(company_id)] = ratio
    return out


def relative_ranks(
    targets: Mapping[Any, float | None], peers: Mapping[int, float]
) -> dict[Any, dict[str, Any] | None]:
    """Puesto de cada objetivo frente a los comparables (sin contarse a sí mismo dos veces)."""
    pool = list(peers.values())
    return {key: rank_against(ratio, pool) for key, ratio in targets.items()}
