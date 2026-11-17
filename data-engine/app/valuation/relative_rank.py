"""Puesto relativo del valor justo: en qué quintil cae una empresa frente al resto.

Sustituye a la etiqueta binaria «infravalorada / sobrevalorada» (valor > precio),
que no anticipa nada. Lo medido (cuánto separa el quintil más barato del más
caro, y si «infravalorada» batía al SPY) vive en ``app/data/value_rank_evidence.json``
con su fuente y el método de descuento con el que se midió; la watchlist lee las
cifras de ahí (``rank_evidence``), nunca de un texto fijo. Si el DCF estándar
cambia de método de descuento, un test obliga a volver a medir.

El puesto se calcula sobre el cociente valor justo / precio, así que no depende
del nivel absoluto del método: si el valor justo se recalibra (todo sube o baja
a la vez), el orden y el quintil no cambian.

Comparables: todas las empresas con una valoración del motor guardada (su
última corrida, con el precio con el que se calculó, en la divisa del listado).
Con menos de ``MIN_PEERS`` comparables no hay puesto (``None``): un quintil de
diez empresas no dice nada. Quintil 1 = el 20 % más barato; 5 = el 20 % más caro.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, func, literal_column, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters

MIN_PEERS = 30
#: Cocientes valor/precio fuera de este rango son datos rotos (unidades, splits), no comparables.
RATIO_BOUNDS = (0.02, 50.0)
EVIDENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "value_rank_evidence.json"


@lru_cache(maxsize=1)
def _evidence_file() -> dict[str, Any]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def rank_evidence() -> dict[str, Any] | None:
    """Lo medido del puesto, para el texto de la watchlist (o None si el fichero no se lee).

    Sin cifras inventadas: cada valor sale del artefacto medido, con el método
    de descuento con el que se midió (``wacc_policy``).
    """
    try:
        raw = _evidence_file()
        spreads = [
            {"period": str(row["period"]), "pts": float(row["pts"])}
            for row in raw["cheapest_vs_dearest_quintile_pts"]
        ]
        return {
            "wacc_policy": str(raw["wacc_policy"]),
            "measured_on": str(raw["measured_on"]),
            "universe": str(raw["universe"]),
            "companies": int(raw["companies"]),
            "sample_years": str(raw["sample_years"]),
            "horizon_months": int(raw["horizon_months"]),
            "cheapest_vs_dearest_quintile_pts": spreads,
            "undervalued_beat_spy_12m": float(raw["undervalued_beat_spy_12m"]),
            "rest_beat_spy_12m": float(raw["rest_beat_spy_12m"]),
            "source": str(raw["source"]),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


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
    payload = ValuationOutput.output_payload
    # Keep JSON types and the same Python value/ADR rules, but never transfer
    # the unrelated valuation trace for every company in the peer universe.
    if db.get_bind().dialect.name == "postgresql":
        # Online 0136 fills this array on writes and in resumable batches.
        # A missing backfill row falls back to the identical live projection.
        # Select one array, not six copies of the fallback expression.
        from app.valuation.peer_rank_projection import COLUMN

        inputs = literal_column(f"valuation_outputs.{COLUMN}", type_=JSON)
        projected = (func.coalesce(inputs, func.valuation_peer_rank_inputs_v1(payload, type_=JSON)),)
    else:
        projected = (
            payload["listed_share_values"]["expected"], payload["listed_share_values"]["base"],
            payload["adr_ratio"], payload["expected_value"], payload["base_value"],
            payload["current_price"],
        )
    statement = (
        select(ValuationModel.company_id, ValuationModel.status, *projected, Company.currency)
        .join(ranked, ValuationModel.id == ranked.c.id)
        .join(ValuationOutput, ValuationOutput.valuation_model_id == ValuationModel.id)
        .join(Company, Company.id == ValuationModel.company_id)
        .where(ranked.c.rank == 1, ValuationModel.status != "insufficient_data")
    )
    # PG returns four fields (one JSON array); SQLite returns nine scalars.
    # Normalize the typed Result rows before flattening the PG-only array.
    rows: Sequence[tuple[Any, ...]] = db.execute(statement).tuples().all()
    if db.get_bind().dialect.name == "postgresql":
        rows = [(company_id, status, *inputs, currency)
                for company_id, status, inputs, currency in rows]
    out: dict[int, float] = {}
    for company_id, status, listed_expected, listed_base, adr_ratio, expected, base, price, currency in rows:
        if status == "insufficient_data" or int(company_id) in out:
            continue
        if normalize_currency(currency)[1] != 1:
            continue
        payload = {
            "listed_share_values": {"expected": listed_expected, "base": listed_base},
            "adr_ratio": adr_ratio,
            "expected_value": expected,
            "base_value": base,
        }
        ratio = _ratio(listed_value(payload, fallback=payload), price)
        if ratio is not None:
            out[int(company_id)] = ratio
    return out


def relative_ranks(
    targets: Mapping[Any, float | None], peers: Mapping[int, float]
) -> dict[Any, dict[str, Any] | None]:
    """Puesto de cada objetivo frente a los comparables (sin contarse a sí mismo dos veces)."""
    pool = list(peers.values())
    evidence = rank_evidence()
    out: dict[Any, dict[str, Any] | None] = {}
    for key, ratio in targets.items():
        rank = rank_against(ratio, pool)
        out[key] = {**rank, "evidence": evidence} if rank is not None else None
    return out
