"""Tasas base de crecimiento de ingresos y de variación del margen operativo, medidas en SEC.

Los datos (``app/data/estimate_base_rates.json``) los genera ``scripts/estimate_base_rates.py``
desde los «frames» XBRL gratuitos de la SEC; la regla y la muestra van dentro del JSON.
Se usan como ancla de las estimaciones sin cobertura (:mod:`own_consensus`) y de los
escenarios de la tesis: el grupo es (tamaño, crecimiento previo a 3 años, sector SIC) y,
si no llega a ``MIN_N`` observaciones, se relaja en este orden fijo: sin sector, solo
crecimiento previo, todas. Puro salvo la lectura del JSON (una vez por proceso).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "estimate_base_rates.json"
MIN_N = 30
SIZE = (("<100M", 0.0, 1e8), ("100M-1B", 1e8, 1e9), ("1B-10B", 1e9, 1e10), (">10B", 1e10, float("inf")))
PRIOR = (("decrece", float("-inf"), 0.0), ("0-5 %", 0.0, 0.05), ("5-10 %", 0.05, 0.10),
         ("10-20 %", 0.10, 0.20), ("> 20 %", 0.20, float("inf")))


@dataclass(frozen=True)
class BaseRate:
    p25: float
    p50: float
    p75: float
    n: int
    group: str
    source: str
    p10: float | None = None
    p90: float | None = None
    metric: str = "growth"
    horizon: int = 1


@lru_cache(maxsize=1)
def table() -> dict[str, Any]:
    with DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _bucket(edges: tuple[tuple[str, float, float], ...], x: float | None) -> str | None:
    if x is None:
        return None
    for name, lo, hi in edges:
        if lo <= x < hi:
            return name
    return None


def sector_of_cik(cik: str | int | None) -> str | None:
    if cik in (None, ""):
        return None
    try:
        idx = table().get("sector_by_cik", {}).get(str(int(str(cik))))
    except ValueError:
        return None
    sectors = table()["buckets"]["sector"]
    return sectors[idx] if isinstance(idx, int) and 0 <= idx < len(sectors) else None


def lookup(*, metric: str = "growth", horizon: int = 1, revenue: float | None = None,
           prior_growth: float | None = None, sector: str | None = None,
           data: dict[str, Any] | None = None) -> BaseRate | None:
    """La tasa base del grupo más fino con al menos ``MIN_N`` observaciones."""
    data = data or table()
    size, prior = _bucket(SIZE, revenue), _bucket(PRIOR, prior_growth)
    chain = [(size, prior, sector), (size, prior, "*"), ("*", prior, "*"), ("*", "*", "*")]
    for s, p, sec in chain:
        if s is None or p is None or sec is None:
            continue
        key = f"h{horizon}|{s}|{p}|{sec}"
        item = (data.get("groups") or {}).get(key, {}).get(metric)
        if item and int(item.get("n", 0)) >= MIN_N:
            label = ", ".join(x for x in (f"tamaño {s}" if s != "*" else "", f"crecimiento previo {p}" if p != "*"
                                          else "", f"sector {sec}" if sec != "*" else "") if x) or "todas"
            return BaseRate(p25=float(item["p25"]), p50=float(item["p50"]), p75=float(item["p75"]),
                            n=int(item["n"]), group=f"{label} · {horizon} año(s)",
                            source=f"{data.get('version')}: {data.get('source')}",
                            p10=float(item["p10"]), p90=float(item["p90"]), metric=metric, horizon=horizon)
    return None


def for_annual_revenue(revenue_by_year: dict[int, float], *, sector: str | None = None, horizon: int = 1,
                       metric: str = "growth", data: dict[str, Any] | None = None) -> BaseRate | None:
    """Grupo de una empresa con sus ingresos anuales: el último año y su TCAC a 3 años."""
    years = sorted(y for y, v in revenue_by_year.items() if v and v > 0)
    if not years:
        return lookup(metric=metric, horizon=horizon, revenue=None, prior_growth=None, sector=None, data=data) \
            or None
    last = years[-1]
    past = revenue_by_year.get(last - 3)
    prior = (revenue_by_year[last] / past) ** (1 / 3) - 1 if past and past > 0 else None
    found = lookup(metric=metric, horizon=horizon, revenue=revenue_by_year[last], prior_growth=prior,
                   sector=sector, data=data)
    if found is None:
        data = data or table()
        item = (data.get("groups") or {}).get(f"h{horizon}|*|*|*", {}).get(metric)
        if item:
            return BaseRate(float(item["p25"]), float(item["p50"]), float(item["p75"]), int(item["n"]),
                            f"todas · {horizon} año(s)", f"{data.get('version')}: {data.get('source')}",
                            float(item["p10"]), float(item["p90"]), metric, horizon)
    return found
