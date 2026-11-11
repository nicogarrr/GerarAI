"""Tasas base de crecimiento de ingresos y de variación del margen operativo, medidas en SEC.

Los datos (``app/data/estimate_base_rates.json``) los genera ``scripts/estimate_base_rates.py``
desde el companyfacts XBRL masivo y gratuito de la SEC con la PRIMERA cifra publicada de cada
ejercicio (point-in-time: sin reexpresiones posteriores); la regla y la muestra van dentro del JSON.
:func:`share_reaching` responde «¿con qué frecuencia lo consiguieron?»: el % del grupo que creció al
menos una tasa dada (la que implica una estimación o la que exige el precio).
Se usan como ancla de las estimaciones sin cobertura (:mod:`own_consensus`) y de los
escenarios de la tesis: el grupo es (tamaño, crecimiento previo a 3 años, sector SIC) y,
si no llega a ``MIN_N`` observaciones, se relaja en este orden fijo: sin sector, solo
crecimiento previo, todas. Puro salvo la lectura del JSON (una vez por proceso).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
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
    # p5 … p95 cada 5 puntos (``grid`` del JSON): la distribución para medir frecuencias.
    quantiles: tuple[float, ...] | None = None
    grid: tuple[float, ...] | None = None


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


def table_horizons(data: dict[str, Any] | None = None) -> tuple[int, ...]:
    """Plazos (años) que mide la tabla, de las claves ``h<N>|…`` de sus grupos."""
    data = data or table()
    found: set[int] = set()
    for key in data.get("groups") or {}:
        head = str(key).split("|", 1)[0]
        if head.startswith("h") and head[1:].isdigit():
            found.add(int(head[1:]))
    return tuple(sorted(found))


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
            return _rate(item, f"{label} · {horizon} año(s)", data, metric, horizon)
    return None


def _rate(item: dict[str, Any], group: str, data: dict[str, Any], metric: str, horizon: int) -> BaseRate:
    q, grid = item.get("q"), data.get("grid")
    ok = isinstance(q, list) and isinstance(grid, list) and len(q) == len(grid) > 1
    return BaseRate(p25=float(item["p25"]), p50=float(item["p50"]), p75=float(item["p75"]), n=int(item["n"]),
                    group=group, source=f"{data.get('version')}: {data.get('source')}",
                    p10=float(item["p10"]), p90=float(item["p90"]), metric=metric, horizon=horizon,
                    quantiles=tuple(float(x) for x in q) if ok else None,  # type: ignore[union-attr]
                    grid=tuple(float(x) for x in grid) if ok else None)  # type: ignore[union-attr]


@dataclass(frozen=True)
class Reach:
    """Qué parte del grupo creció al menos ``growth`` (TCAC a ``horizon`` años)."""
    growth: float
    share: float  # 0–1
    bound: str  # "=" (interpolado), "<" (menos de share) o ">" (más de share)
    rate: BaseRate

    def text(self) -> str:
        pct = f"{self.share:.0%}"
        return {"<": f"menos del {pct}", ">": f"más del {pct}"}.get(self.bound, f"el {pct}")

    def as_dict(self, *, implied_formula: str = "") -> dict[str, Any]:
        r = self.rate
        what = (f"mejoró su margen operativo al menos {self.growth * 100:+.1f} puntos" if r.metric == "margin"
                else f"creció al menos {self.growth:+.1%}/año")
        formula = ((implied_formula + "; ") if implied_formula else "") + (
            f"{self.text()} de las empresas del grupo «{r.group}» (n={r.n}) {what} en {r.horizon} año(s) "
            f"(interpolado en sus percentiles p5–p95, primera cifra publicada)")
        return {"metric": r.metric, "growth": self.growth, "horizon_years": r.horizon, "share": self.share,
                "bound": self.bound, "group": r.group, "n": r.n, "p50": r.p50, "formula": formula,
                "source": r.source}


def share_reaching(rate: BaseRate | None, growth: float | None) -> Reach | None:
    """% del grupo con TCAC (o variación del margen, ``metric='margin'``) ≥ ``growth``: 1 − F(growth),
    F interpolada linealmente en p5…p95.

    Fuera de la rejilla no se extrapola: por encima de p95 es «menos del 5 %», por debajo de p5
    «más del 95 %». Sin rejilla (tabla antigua) o sin tasa: ``None`` (N/D)."""
    if rate is None or growth is None or rate.quantiles is None or rate.grid is None or rate.metric not in {"growth", "margin"}:
        return None
    q, grid = rate.quantiles, rate.grid
    if growth > q[-1]:
        return Reach(growth, round(1 - grid[-1], 4), "<", rate)
    if growth < q[0]:
        return Reach(growth, round(1 - grid[0], 4), ">", rate)
    for i in range(len(q) - 1):
        lo, hi = q[i], q[i + 1]
        if lo <= growth <= hi:
            f = grid[i] if hi == lo else grid[i] + (grid[i + 1] - grid[i]) * (growth - lo) / (hi - lo)
            return Reach(growth, round(1 - f, 4), "=", rate)
    return None


def for_annual_revenue(revenue_by_year: dict[int, float], *, sector: str | None = None, horizon: int = 1,
                       metric: str = "growth", data: dict[str, Any] | None = None,
                       usd_rate: float | None = 1.0, size_note: str = "") -> BaseRate | None:
    """Grupo de una empresa con sus ingresos anuales: el último año y su TCAC a 3 años.

    Los tramos de tamaño están en dólares: ``usd_rate`` convierte los ingresos (de su divisa de
    reporte) a USD solo para elegir el tramo; el crecimiento previo es un cociente y no cambia.
    ``usd_rate=None`` (otra divisa sin tipo oficial): tamaño desconocido, el grupo se relaja sin él.
    ``size_note`` (de dónde sale el tipo) se añade a la etiqueta del grupo cuando el tamaño cuenta."""
    years = sorted(y for y, v in revenue_by_year.items() if v and v > 0)
    if not years:
        return lookup(metric=metric, horizon=horizon, revenue=None, prior_growth=None, sector=None, data=data) \
            or None
    last = years[-1]
    past = revenue_by_year.get(last - 3)
    prior = (revenue_by_year[last] / past) ** (1 / 3) - 1 if past and past > 0 else None
    size = revenue_by_year[last] * usd_rate if usd_rate is not None else None
    found = lookup(metric=metric, horizon=horizon, revenue=size, prior_growth=prior,
                   sector=sector, data=data)
    if found is None:
        data = data or table()
        item = (data.get("groups") or {}).get(f"h{horizon}|*|*|*", {}).get(metric)
        if item:
            return _rate(item, f"todas · {horizon} año(s)", data, metric, horizon)
    if found is not None and size_note and "tamaño " in found.group:
        found = replace(found, group=f"{found.group} · {size_note}")
    return found


# Tipo de cambio para el TRAMO de tamaño (órdenes de magnitud: <100M, 100M-1B, 1B-10B, >10B).
SIZE_FX_MAX_AGE_DAYS = 7  # el oficial del cierre del ejercicio (BCE: días hábiles; puente largo 4-5 días)
SIZE_FX_FALLBACK_MAX_DAYS = 400  # sin el del cierre: el último oficial, si el cierre no tiene más de 400 días
SIZE_FX_RECENT_MAX_AGE_DAYS = 10


@dataclass(frozen=True)
class SizeFx:
    """Divisa de reporte → USD para clasificar el tamaño; ``rate=None`` lleva el motivo (N/D)."""
    currency: str
    rate: float | None
    rate_date: date | None = None
    source: str | None = None
    at_close: bool = True
    reason: str = ""

    @property
    def note(self) -> str:
        if self.rate is None or self.currency == "USD":
            return ""
        when = self.rate_date.strftime("%d-%m-%Y") if self.rate_date else "s. f."
        rate = f"{self.rate:.6g}".replace(".", ",")
        return (f"tamaño en USD con {self.currency}→USD {rate} del {when}"
                f"{'' if self.at_close else ' (último oficial publicado: no había del cierre)'}")


def usd_size_fx(db: Any, currency: str | None, close: date | None, *, today: date) -> SizeFx:
    """Tipo oficial ``currency``→USD de ``fx_rates`` (point-in-time, nunca inventado) para el tramo.

    Primero el del cierre del ejercicio (≤ ``SIZE_FX_MAX_AGE_DAYS`` días antes); si la tabla no lo
    tiene, el último publicado (≤ 10 días antes de hoy) siempre que el cierre no tenga más de
    ``SIZE_FX_FALLBACK_MAX_DAYS`` días, con su fecha a la vista. Si no, N/D con el motivo."""
    code = (currency or "").strip().upper()
    if code == "USD":
        return SizeFx("USD", 1.0)
    if not code or close is None:
        return SizeFx(code or "?", None, reason="ingresos sin divisa o sin fecha de cierre: no se clasifica el tamaño")
    from app.valuation.currency import resolve_fx

    quote = resolve_fx(db, code, "USD", close, max_age_days=SIZE_FX_MAX_AGE_DAYS)
    if quote is not None:
        return SizeFx(code, quote.rate, quote.rate_date, quote.source, True)
    if 0 <= (today - close).days <= SIZE_FX_FALLBACK_MAX_DAYS:
        quote = resolve_fx(db, code, "USD", today, max_age_days=SIZE_FX_RECENT_MAX_AGE_DAYS)
        if quote is not None:
            return SizeFx(code, quote.rate, quote.rate_date, quote.source, False)
    return SizeFx(code, None, reason=(f"ingresos en otra divisa ({code}): sin tipo oficial {code}→USD al cierre "
                                      f"del {close.strftime('%d-%m-%Y')}; los tramos de tamaño de la tasa base "
                                      f"están en dólares"))
