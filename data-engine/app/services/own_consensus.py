"""Consenso propio por celda (métrica × periodo), determinista y sin modelo.

Equivalente gratuito del «consenso agéntico» de fiscal.ai, pero sin que ningún modelo
ponga una cifra: cada celda sale de la primera fuente disponible en un orden FIJO y
lleva bajo / medio / alto, la fuente, la fórmula visible, la cita y una confianza.

Orden de fuentes (``SOURCE_ORDER``); se publica la primera que pasa las puertas y las
demás quedan como contraste:

1. ``guia``: la previsión de la empresa (``guidance.<métrica>.<periodo>``, #4749).
2. ``guia_trimestre_calculado``: un trimestre sin guía propia = (guía anual − trimestres
   ya presentados) × peso del trimestre en lo que falta del año (mediana de los 3
   ejercicios anteriores). Solo métricas sumables.
3. ``guia_ajustada``: la guía × (1 + su desvío histórico medido), si la empresa tiene
   al menos ``MIN_BEAT_SAMPLES`` guías congeladas antes del cierre con su dato real.
   Va como contraste de la 1 y la 2 (que mandan, porque son la cifra oficial) y
   publica solo cuando la guía no tiene rango propio que la contradiga.
4. ``analista_citado``: la mediana de las firmas citadas en prensa (``analyst_consensus``).
5. ``modelo``: tendencia log-lineal de hasta 12 trimestres desestacionalizados,
   encogida hacia la tasa base con peso n/(n + ``SHRINK_K``) y desvanecida a la mitad
   cada año de horizonte. El beneficio operativo = ingresos estimados × margen TTM.
   El BPA = BPA del mismo periodo anterior × (beneficio operativo estimado / el del
   periodo anterior), con acciones, intereses e impuestos constantes (``_eps_candidate``).
6. ``tasa_base``: el último dato × (1 + mediana del crecimiento de su grupo), con
   p25/p75 como rango.

Puertas (de los filtros de cordura que fiscal.ai publica, aplicados por nosotros):

- ``año_bajo_lo_contabilizado`` (rechaza): el alto del año queda por debajo de lo ya
  presentado en sus trimestres.
- ``signo_contra_racha``: 4 o más trimestres seguidos creciendo (o cayendo) y la
  estimación con el signo contrario. Rechaza ``modelo`` y ``tasa_base``; en la guía y
  los analistas solo marca la celda (la empresa puede anunciar un giro).
- ``suma_trimestres≠año``: los trimestres (presentados + estimados) no cuadran con el
  año a ±2 %: se marca el año.
- ``periodo_vencido``: el periodo cerró hace más de 120 días (trimestre) o 180 (año)
  y no hay dato: la celda queda sin estimación y lo dice.

La confianza es medida (``measured_errors``: error absoluto mediano por fuente y
horizonte, de :mod:`estimate_accuracy`) o «bajo · muestra pequeña» con menos de
``MIN_CONFIDENCE_SAMPLES`` casos. Puro salvo ``build_company_consensus``.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.services.estimate_base_rates import BaseRate

CONSENSUS_VERSION = "consenso_propio v1"
SOURCE_ORDER = ("guia", "guia_trimestre_calculado", "guia_ajustada", "analista_citado", "modelo", "tasa_base")
METRICS = ("revenue", "operating_income", "eps")
ADDITIVE = frozenset({"revenue", "operating_income"})
FACT_METRIC = {"revenue": "revenue", "operating_income": "operating_income", "eps": "eps_diluted"}
MIN_BEAT_SAMPLES = 4
MIN_CONFIDENCE_SAMPLES = 8
SHRINK_K = 8
MIN_MODEL_QUARTERS = 8
STREAK = 4
SUM_TOLERANCE = 0.02
STALE_DAYS = {"q": 120, "fy": 180}


# ---------------------------------------------------------------------- datos de entrada
@dataclass(frozen=True)
class Actual:
    period: str  # fy2025 | q3_2026
    end: date
    value: float
    filed: date | None = None
    url: str | None = None
    derived: bool = False
    formula: str = ""


@dataclass(frozen=True)
class GuidanceRow:
    metric: str
    period: str
    low: float | None
    base: float
    high: float | None
    as_of: date
    url: str | None = None
    quote: str = ""


@dataclass
class Candidate:
    source: str
    low: float | None
    mid: float
    high: float | None
    formula: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    rejected: str | None = None
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "low": self.low, "mid": self.mid, "high": self.high,
                "formula": self.formula, "citations": self.citations, "rejected": self.rejected,
                "flags": list(self.flags)}


@dataclass
class Cell:
    metric: str
    period: str
    end: date
    status: str  # estimado | vencido | sin_estimacion
    published: Candidate | None
    alternatives: list[Candidate]
    flags: list[str]
    confidence: dict[str, Any]
    reason: str = ""

    @property
    def key(self) -> str:
        return f"estimate.{self.metric}.{self.period}"

    def as_dict(self) -> dict[str, Any]:
        pub = self.published
        return {"key": self.key, "metric": self.metric, "period": self.period, "period_end": self.end.isoformat(),
                "status": self.status, "source": pub.source if pub else None,
                "low": pub.low if pub else None, "mid": pub.mid if pub else None, "high": pub.high if pub else None,
                "formula": pub.formula if pub else "", "citations": pub.citations if pub else [],
                "flags": list(self.flags) + (list(pub.flags) if pub else []), "confidence": self.confidence,
                "reason": self.reason, "alternatives": [c.as_dict() for c in self.alternatives],
                "version": CONSENSUS_VERSION}


# ---------------------------------------------------------------------- periodos
# Calendarios de 52/53 semanas (AAPL, retail, semis): el periodo cierra un sábado o domingo a ±7 días
# del fin de mes, así que un cierre el 3 de enero es el ejercicio de diciembre, no uno nuevo.
WEEKLY_CALENDAR_DAYS = 7


def nominal_month(end: date) -> tuple[int, int]:
    """(año, mes) al que pertenece un cierre: el mismo mes, o el anterior si cae en sus primeros 7 días."""
    if end.day <= WEEKLY_CALENDAR_DAYS:
        prev = end.replace(day=1) - timedelta(days=1)
        return prev.year, prev.month
    return end.year, end.month


def fy_end_month(fy_ends: Sequence[date]) -> int:
    """Mes de cierre del ejercicio (el del último año presentado; diciembre si no hay), por su mes nominal."""
    return nominal_month(max(fy_ends))[1] if fy_ends else 12


def fiscal_year_of(end: date) -> int:
    """Ejercicio de un cierre anual: el año de su mes nominal (FY que cierra el 03-01-2026 → 2025)."""
    return nominal_month(end)[0]


def quarter_of(end: date, fy_month: int) -> tuple[int, int]:
    """(número de trimestre fiscal, ejercicio) de un trimestre que cierra en ``end`` (mes nominal)."""
    year, month = nominal_month(end)
    fy = year if month <= fy_month else year + 1
    q = ((month - fy_month - 1) % 12) // 3 + 1
    return q, fy


def _month_end(year: int, month: int) -> date:
    nxt = date(year + (month // 12), month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def period_end(period: str, fy_month: int) -> date:
    if period.startswith("fy"):
        return _month_end(int(period[2:]), fy_month)
    if period.startswith("h"):
        half, year = int(period[1]), int(period[3:])
        months = fy_month - (6 if half == 1 else 0)
        y = year if months > 0 else year - 1
        return _month_end(y, months if months > 0 else months + 12)
    q, year = int(period[1]), int(period[3:])
    month = fy_month - 3 * (4 - q)
    y = year if month > 0 else year - 1
    return _month_end(y, month if month > 0 else month + 12)


def actuals_from_facts(rows: Sequence[tuple[str, float, date | None, str | None]], *, metric: str
                       ) -> dict[str, Actual]:
    """Hechos ``(period "YYYY-MM-DD:Q3|FY", valor, filed, url)`` → datos por clave fy/q.

    Si falta el 4T y están el año y los otros tres, se deriva (4T = año − 9M) y se marca
    ``derived`` con su fórmula (solo métricas sumables)."""
    parsed: list[tuple[date, str, float, date | None, str | None]] = []
    for period, value, filed, url in rows:
        try:
            end_s, kind = str(period).split(":", 1)
            end = date.fromisoformat(end_s)
        except ValueError:
            continue
        if value is None or not math.isfinite(float(value)):
            continue
        parsed.append((end, kind.upper(), float(value), filed, url))
    fy_month = fy_end_month([p[0] for p in parsed if p[1] == "FY"])
    out: dict[str, Actual] = {}
    for end, kind, value, filed, url in sorted(parsed, key=lambda p: (p[0], p[3] or date.min)):
        if kind == "FY":
            key = f"fy{fiscal_year_of(end)}"
        elif kind in {"Q1", "Q2", "Q3", "Q4"}:
            # El trimestre ya viene declarado por la fuente. En ejercicios de
            # 52/53 semanas su cierre puede caer en el mes del trimestre siguiente.
            _, fy = quarter_of(end, fy_month)
            key = f"q{kind[1:]}_{fy}"
        else:
            continue
        out[key] = Actual(key, end, value, filed, url)
    if metric in ADDITIVE:
        for key, fy in list(out.items()):
            if not key.startswith("fy"):
                continue
            year = key[2:]
            q4 = f"q4_{year}"
            parts = [out.get(f"q{i}_{year}") for i in (1, 2, 3)]
            if q4 not in out and all(parts):
                value = fy.value - sum(p.value for p in parts if p)
                out[q4] = Actual(q4, fy.end, value, fy.filed, fy.url, derived=True,
                                 formula=f"4T = año ({fy.value:,.0f}) − 9M ({sum(p.value for p in parts if p):,.0f})")
    return out


def quarterly_series(actuals: Mapping[str, Actual]) -> list[Actual]:
    return sorted((a for k, a in actuals.items() if k.startswith("q")), key=lambda a: a.end)


# ---------------------------------------------------------------------- piezas puras
def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def seasonal_shares(actuals: Mapping[str, Actual], fy: int, quarters: Sequence[int], *, years: int = 3
                    ) -> dict[int, float] | None:
    """Peso de cada trimestre de ``quarters`` dentro de su suma, mediana de los ``years``
    ejercicios anteriores con todos ellos presentados."""
    samples: dict[int, list[float]] = {q: [] for q in quarters}
    for y in range(fy - 1, fy - 1 - 6, -1):
        vals = [actuals.get(f"q{q}_{y}") for q in quarters]
        if not all(vals):
            continue
        total = sum(v.value for v in vals if v)
        if total <= 0:
            continue
        for q, v in zip(quarters, vals, strict=True):
            if v:
                samples[q].append(v.value / total)
        if len(samples[quarters[0]]) >= years:
            break
    if not samples[quarters[0]]:
        return None
    raw = {q: float(statistics.median(s)) for q, s in samples.items()}
    total = sum(raw.values())
    return {q: v / total for q, v in raw.items()} if total > 0 else None


def guidance_beat(history: Sequence[GuidanceRow], actuals: Mapping[str, Actual], fy_month: int
                  ) -> tuple[float | None, list[dict[str, Any]]]:
    """Desvío histórico de la guía: mediana de (real ÷ punto medio − 1), con la última
    guía de cada periodo emitida ANTES de su cierre (congelada antes del resultado)."""
    last: dict[str, GuidanceRow] = {}
    for row in sorted(history, key=lambda r: r.as_of):
        end = period_end(row.period, fy_month)
        if row.as_of < end:
            last[row.period] = row
    cases: list[dict[str, Any]] = []
    for period, row in sorted(last.items()):
        real = actuals.get(period)
        if real is None or not row.base or not (1 / 3 <= real.value / row.base <= 3):
            continue  # sin dato o lectura inverosímil (escala u otra métrica)
        cases.append({"period": period, "guidance": row.base, "actual": real.value, "as_of": row.as_of.isoformat(),
                      "error": real.value / row.base - 1.0, "url": row.url})
    if len(cases) < MIN_BEAT_SAMPLES:
        return None, cases
    return float(statistics.median(c["error"] for c in cases)), cases


def trend_growth(series: Sequence[Actual], *, window: int = 12) -> tuple[float | None, int, dict[int, float]]:
    """Crecimiento anual de la tendencia log-lineal de los últimos ``window`` trimestres,
    desestacionalizados con el índice multiplicativo de cada trimestre (mediana de su
    peso frente a la media de su ejercicio). Devuelve (g, n trimestres, índices)."""
    pts = [a for a in series if a.value > 0][-window:]
    if len(pts) < MIN_MODEL_QUARTERS:
        return None, len(pts), {}
    by_q: dict[int, list[float]] = {}
    years: dict[str, list[Actual]] = {}
    for a in series:
        years.setdefault(a.period.split("_")[1], []).append(a)
    for items in years.values():
        if len(items) == 4 and all(i.value > 0 for i in items):
            mean = sum(i.value for i in items) / 4
            for i in items:
                by_q.setdefault(int(i.period[1]), []).append(i.value / mean)
    index = {q: float(statistics.median(v)) for q, v in by_q.items()} if len(by_q) == 4 else {1: 1., 2: 1., 3: 1., 4: 1.}
    ys = [math.log(a.value / index[int(a.period[1])]) for a in pts]
    xs = list(range(len(ys)))
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    return math.exp(4 * slope) - 1, len(pts), index


def shrunk_growth(g_trend: float, n: int, base: float, horizon_years: int) -> tuple[float, float]:
    """(crecimiento, peso de la tendencia): w = n/(n+K) el primer año y la mitad cada año más."""
    w = n / (n + SHRINK_K) * 0.5 ** max(0, horizon_years - 1)
    return w * g_trend + (1 - w) * base, w


def streak_sign(series: Sequence[Actual]) -> int:
    """+1 / −1 si los últimos ``STREAK`` trimestres comparables crecen (caen) todos frente
    al mismo trimestre del año anterior; 0 si no hay racha."""
    by_key = {a.period: a for a in series}
    signs: list[int] = []
    for a in series:
        q, y = a.period.split("_")
        prev = by_key.get(f"{q}_{int(y) - 1}")
        if prev is not None and prev.value:
            signs.append(1 if a.value > prev.value else -1)
    signs = signs[-STREAK:]
    if len(signs) < STREAK or len(set(signs)) != 1:
        return 0
    return signs[0]


def confidence_for(source: str, horizon: str, measured: Mapping[tuple[str, str], Sequence[float]]) -> dict[str, Any]:
    errs = list(measured.get((source, horizon), ()))
    if len(errs) < MIN_CONFIDENCE_SAMPLES:
        return {"level": "bajo", "reason": f"muestra pequeña ({len(errs)} casos medidos de {source} a {horizon})",
                "n": len(errs)}
    mae = float(statistics.median(abs(e) for e in errs))
    level = "alto" if mae < 0.03 else "medio" if mae < 0.08 else "bajo"
    return {"level": level, "median_abs_error": mae, "n": len(errs),
            "reason": f"error absoluto mediano {mae:.1%} en {len(errs)} casos de {source} a {horizon}"}


def horizon_of(end: date, today: date) -> str:
    days = (end - today).days
    return "≤1T" if days <= 100 else "≤1A" if days <= 400 else ">1A"


# ---------------------------------------------------------------------- la celda
def _cite_guidance(g: GuidanceRow) -> dict[str, Any]:
    return {"kind": "guia", "url": g.url, "date": g.as_of.isoformat(), "quote": g.quote[:300]}


def _cite_actual(a: Actual) -> dict[str, Any]:
    return {"kind": "dato_presentado" if not a.derived else "dato_derivado", "period": a.period, "value": a.value,
            "url": a.url, "date": a.filed.isoformat() if a.filed else None, "formula": a.formula}


def build_cells(metric: str, actuals: Mapping[str, Actual], *, today: date,
                guidance: Sequence[GuidanceRow] = (), guidance_history: Sequence[GuidanceRow] = (),
                analyst: Sequence[Mapping[str, Any]] = (), base_rate: BaseRate | None = None,
                revenue_cells: Mapping[str, Cell] | None = None, revenue_actuals: Mapping[str, Actual] | None = None,
                measured_errors: Mapping[tuple[str, str], Sequence[float]] | None = None,
                operating_cells: Mapping[str, Cell] | None = None,
                operating_actuals: Mapping[str, Actual] | None = None) -> dict[str, Cell]:
    """Todas las celdas de una métrica: trimestres sin presentar del ejercicio en curso,
    el ejercicio en curso, el siguiente y cualquier periodo con guía futura."""
    measured = measured_errors or {}
    fy_ends = [a.end for k, a in actuals.items() if k.startswith("fy")]
    fy_month = fy_end_month(fy_ends)
    last_fy = max((int(k[2:]) for k in actuals if k.startswith("fy")), default=today.year - 1)
    targets: set[str] = {f"fy{last_fy + 1}", f"fy{last_fy + 2}"}
    targets |= {f"q{q}_{last_fy + 1}" for q in (1, 2, 3, 4) if f"q{q}_{last_fy + 1}" not in actuals}
    current_g = {g.period: g for g in sorted(guidance, key=lambda g: g.as_of) if g.metric == metric}
    targets |= {p for p in current_g if p.startswith(("fy", "q")) and p not in actuals}
    targets = {t for t in targets if t not in actuals}
    series = quarterly_series(actuals)
    streak = streak_sign(series)
    beat, beat_cases = guidance_beat([g for g in guidance_history if g.metric == metric], actuals, fy_month)
    analyst_by_year = {int(a["year"]): a for a in analyst if a.get("metric") == metric and a.get("median") is not None}

    def prior(period: str) -> Actual | None:
        if period.startswith("fy"):
            return actuals.get(f"fy{int(period[2:]) - 1}")
        q, y = period.split("_")
        return actuals.get(f"{q}_{int(y) - 1}")

    cells: dict[str, Cell] = {}
    order = sorted(targets, key=lambda p: (period_end(p, fy_month), p.startswith("fy")))
    for period in order:
        end = period_end(period, fy_month)
        is_fy = period.startswith("fy")
        cands: list[Candidate] = []
        fy_key = period if is_fy else f"fy{period.split('_')[1]}"
        year = int(fy_key[2:])
        reported_q = [actuals[f"q{q}_{year}"] for q in (1, 2, 3, 4) if f"q{q}_{year}" in actuals]
        ytd = sum(a.value for a in reported_q)
        # 1. guía
        g = current_g.get(period)
        if g is not None:
            cands.append(Candidate("guia", g.low, g.base, g.high,
                                   f"guía de la empresa ({g.as_of.isoformat()})", [_cite_guidance(g)]))
        # 2. trimestre calculado desde la guía anual
        gfy = current_g.get(fy_key)
        if gfy is not None and reported_q and metric in ADDITIVE and \
                (gfy.high if gfy.high is not None else gfy.base) < ytd * (1 - 1e-9):
            gfy = None  # una guía anual por debajo de lo ya presentado no reparte trimestres
        if not is_fy and gfy is not None and metric in ADDITIVE:
            missing = [q for q in (1, 2, 3, 4) if f"q{q}_{year}" not in actuals]
            shares = seasonal_shares(actuals, year, missing) if len(missing) > 1 else {missing[0]: 1.0}
            qn = int(period[1])
            if shares and qn in shares:
                share = shares[qn]

                def calc(v: float | None, _share: float = share) -> float | None:
                    return None if v is None else (v - ytd) * _share
                mid = calc(gfy.base)
                if mid is not None:
                    cands.append(Candidate(
                        "guia_trimestre_calculado", calc(gfy.low), mid, calc(gfy.high),
                        f"(guía {fy_key} {gfy.base:,.0f} − presentado {ytd:,.0f}) × peso del {qn}T {share:.3f}",
                        [_cite_guidance(gfy)] + [_cite_actual(a) for a in reported_q]))
        # 3. guía ajustada por su desvío histórico
        if beat is not None and cands and cands[0].source.startswith("guia"):
            base_c = cands[0]
            cands.append(Candidate(
                "guia_ajustada", None if base_c.low is None else base_c.low * (1 + beat), base_c.mid * (1 + beat),
                None if base_c.high is None else base_c.high * (1 + beat),
                f"{base_c.source} {base_c.mid:,.0f} × (1 + desvío mediano {beat:+.2%} en {len(beat_cases)} guías)",
                [{"kind": "historial_guia", "cases": beat_cases}]))
        # 4. analistas citados (años)
        if is_fy and year in analyst_by_year:
            a = analyst_by_year[year]
            scale = 1e6 if metric != "eps" else 1.0
            cands.append(Candidate(
                "analista_citado", float(a["low"]) * scale, float(a["median"]) * scale, float(a["high"]) * scale,
                f"mediana de {a.get('n_firms')} firmas citadas (bajo = mínimo, alto = máximo)",
                [{"kind": "analista", "firm": f.get("firm"), "url": f.get("url"), "date": f.get("as_of"),
                  # Una firma sin cifra es N/D, no 0.
                  "value": float(f["value_millions"]) * scale if f.get("value_millions") is not None else None}
                 for f in a.get("firms") or []]))
        # 5. modelo y 6. tasa base
        horizon_years = max(1, year - last_fy)
        if base_rate is not None:
            model = _model_candidate(metric, period, actuals, series, base_rate, horizon_years, ytd, reported_q,
                                     revenue_cells, revenue_actuals, cells)
            if model is not None:
                cands.append(model)
            p = prior(period) if metric != "eps" or is_fy else None
            prev_cell = cells.get(f"fy{year - 1}") if is_fy else None
            anchor = p.value if p else (prev_cell.published.mid if prev_cell and prev_cell.published else None)
            if anchor is not None and anchor > 0 and metric in ADDITIVE | {"eps"}:
                n_years = 1

                def grow(r: float, _a: float = anchor, _n: int = n_years) -> float:
                    return _a * (1 + r) ** _n
                cands.append(Candidate(
                    "tasa_base", grow(base_rate.p25), grow(base_rate.p50), grow(base_rate.p75),
                    f"{'dato' if p else 'estimación'} anterior {anchor:,.0f} × (1 + {base_rate.p50:+.2%}) "
                    f"(mediana del grupo «{base_rate.group}», n={base_rate.n}; rango p25–p75)",
                    ([_cite_actual(p)] if p else []) + [{"kind": "tasa_base", "source": base_rate.source}]))
        # 5b. modelo de BPA: el BPA del mismo periodo anterior escalado por el beneficio
        # operativo estimado (acciones, intereses e impuestos constantes).
        if metric == "eps" and operating_cells is not None and operating_actuals is not None:
            eps_model = _eps_candidate(period, actuals, cells, operating_cells, operating_actuals)
            if eps_model is not None:
                cands.append(eps_model)
        # puertas
        flags: list[str] = []
        prev_actual = prior(period)
        for c in cands:
            if is_fy and metric in ADDITIVE and reported_q:
                top = c.high if c.high is not None else c.mid
                if top < ytd * (1 - 1e-9):
                    c.rejected = (f"año_bajo_lo_contabilizado: {top:,.0f} < {ytd:,.0f} ya presentado en "
                                  f"{len(reported_q)} trimestre(s)")
                    continue
            if streak and prev_actual is not None and prev_actual.value:
                implied = 1 if c.mid > prev_actual.value else -1
                if implied != streak:
                    note = f"signo_contra_racha: {STREAK} trimestres {'al alza' if streak > 0 else 'a la baja'}"
                    if c.source in {"modelo", "tasa_base"}:
                        c.rejected = note
                        continue
                    c.flags.append(note)
        stale_days = STALE_DAYS["fy" if is_fy else "q"]
        published = next((c for c in cands if c.rejected is None), None)
        if (today - end).days > stale_days:
            cells[period] = Cell(metric, period, end, "vencido", None, cands, ["periodo_vencido"], {},
                                 f"el periodo cerró el {end.isoformat()} hace más de {stale_days} días y no hay dato")
            continue
        conf = confidence_for(published.source, horizon_of(end, today), measured) if published else {}
        if published is None:
            cells[period] = Cell(metric, period, end, "sin_estimacion", None, cands, flags, {},
                                 "ninguna fuente disponible pasa las puertas")
            continue
        cells[period] = Cell(metric, period, end, "estimado", published, [c for c in cands if c is not published],
                             flags, conf)
    # suma de trimestres frente al año
    if metric in ADDITIVE:
        for period, cell in cells.items():
            if not period.startswith("fy") or cell.published is None:
                continue
            year = int(period[2:])
            parts: list[float] = []
            for q in (1, 2, 3, 4):
                k = f"q{q}_{year}"
                if k in actuals:
                    parts.append(actuals[k].value)
                elif k in cells and cells[k].published is not None:
                    parts.append(cells[k].published.mid)  # type: ignore[union-attr]
            if len(parts) == 4 and cell.published.mid:
                gap = sum(parts) / cell.published.mid - 1
                if abs(gap) > SUM_TOLERANCE:
                    cell.flags.append(f"suma_trimestres≠año: los 4 trimestres suman {sum(parts):,.0f} "
                                      f"({gap:+.1%} frente al año)")
    return cells


def _prior_key(period: str) -> str:
    if period.startswith("fy"):
        return f"fy{int(period[2:]) - 1}"
    q, y = period.split("_")
    return f"{q}_{int(y) - 1}"


def _eps_candidate(period: str, eps_actuals: Mapping[str, Actual], eps_done: Mapping[str, Cell],
                   operating_cells: Mapping[str, Cell], operating_actuals: Mapping[str, Actual]) -> Candidate | None:
    """``modelo`` del BPA (regla ``bpa_escala_beneficio_operativo v1``).

    BPA estimado = BPA del mismo periodo anterior × (beneficio operativo estimado del
    periodo / beneficio operativo del periodo anterior). Supone constantes las acciones,
    los intereses y el tipo fiscal, y lo dice en la fórmula. Ancla presentada si existe;
    si no (el año +2), la estimación publicada del año anterior de las dos métricas.
    Sin estimación (None) si falta cualquiera de las cuatro cifras o alguna no es
    positiva: escalar una pérdida por un ratio no tiene sentido económico.
    """
    oi_cell = operating_cells.get(period)
    oi_est = oi_cell.published if oi_cell is not None else None
    if oi_est is None:
        return None
    prev = _prior_key(period)
    eps_prev_a, oi_prev_a = eps_actuals.get(prev), operating_actuals.get(prev)
    citations: list[dict[str, Any]] = []
    if eps_prev_a is not None and oi_prev_a is not None:
        eps_prev, oi_prev, label = eps_prev_a.value, oi_prev_a.value, f"{prev} presentado"
        citations = [_cite_actual(eps_prev_a), _cite_actual(oi_prev_a)]
    else:
        eps_c, oi_c = eps_done.get(prev), operating_cells.get(prev)
        if eps_prev_a is not None or oi_prev_a is not None or eps_c is None or oi_c is None \
                or eps_c.published is None or oi_c.published is None:
            return None
        eps_prev, oi_prev, label = eps_c.published.mid, oi_c.published.mid, f"{prev} estimado"
    if not (eps_prev > 0 and oi_prev > 0 and oi_est.mid > 0):
        return None

    def scale(v: float | None) -> float | None:
        return None if v is None or v <= 0 else eps_prev * v / oi_prev
    mid = eps_prev * oi_est.mid / oi_prev
    citations.append({"kind": "estimacion_beneficio_operativo", "source": oi_est.source, "period": period,
                      "value": oi_est.mid, "formula": oi_est.formula})
    return Candidate(
        "modelo", scale(oi_est.low), mid, scale(oi_est.high),
        f"BPA {label} {eps_prev:,.2f} × beneficio operativo estimado {oi_est.mid:,.0f} ({oi_est.source}) / "
        f"{oi_prev:,.0f} ({oi_est.mid / oi_prev - 1:+.1%}); acciones, intereses e impuestos constantes",
        citations)


def _model_candidate(metric: str, period: str, actuals: Mapping[str, Actual], series: Sequence[Actual],
                     base_rate: BaseRate, horizon_years: int, ytd: float, reported_q: Sequence[Actual],
                     revenue_cells: Mapping[str, Cell] | None, revenue_actuals: Mapping[str, Actual] | None,
                     done: Mapping[str, Cell]) -> Candidate | None:
    is_fy = period.startswith("fy")
    if metric == "revenue":
        g_trend, n, _index = trend_growth(series)
        if g_trend is None:
            return None
        g, w = shrunk_growth(g_trend, n, base_rate.p50, horizon_years)
        g_lo, _ = shrunk_growth(g_trend, n, base_rate.p25, horizon_years)
        g_hi, _ = shrunk_growth(g_trend, n, base_rate.p75, horizon_years)
        why = (f"tendencia {g_trend:+.2%} ({n} trimestres) × {w:.2f} + tasa base {base_rate.p50:+.2%} × {1 - w:.2f} "
               f"= {g:+.2%}")
        if not is_fy:
            q, y = period.split("_")
            prev = actuals.get(f"{q}_{int(y) - 1}")
            if prev is None:
                return None
            return Candidate("modelo", prev.value * (1 + g_lo), prev.value * (1 + g), prev.value * (1 + g_hi),
                             f"{q.upper()} anterior {prev.value:,.0f} × (1 {why})", [_cite_actual(prev)])
        year = int(period[2:])
        prev_fy = actuals.get(f"fy{year - 1}")
        if prev_fy is None:
            prev_cell = done.get(f"fy{year - 1}")
            if prev_cell is None or prev_cell.published is None:
                return None
            base = prev_cell.published.mid
            return Candidate("modelo", base * (1 + g_lo), base * (1 + g), base * (1 + g_hi),
                             f"estimación fy{year - 1} {base:,.0f} × (1 {why})", [])
        # año en curso: presentado + trimestres que faltan con el mismo crecimiento
        missing = [q for q in (1, 2, 3, 4) if f"q{q}_{year}" not in actuals]
        prevs = [actuals.get(f"q{q}_{year - 1}") for q in missing]
        if not all(prevs):
            return Candidate("modelo", prev_fy.value * (1 + g_lo), prev_fy.value * (1 + g), prev_fy.value * (1 + g_hi),
                             f"año anterior {prev_fy.value:,.0f} × (1 {why})", [_cite_actual(prev_fy)])
        rest = sum(p.value for p in prevs if p)
        return Candidate("modelo", ytd + rest * (1 + g_lo), ytd + rest * (1 + g), ytd + rest * (1 + g_hi),
                         f"presentado {ytd:,.0f} + trimestres pendientes del año anterior {rest:,.0f} × (1 {why})",
                         [_cite_actual(a) for a in reported_q])
    if metric == "operating_income" and revenue_cells is not None and revenue_actuals is not None:
        rev = revenue_cells.get(period)
        if rev is None or rev.published is None:
            return None
        r = rev.published

        def margin_of(key: str) -> float | None:
            o, v = actuals.get(key), revenue_actuals.get(key)
            if o is not None and v is not None and v.value > 0:
                return o.value / v.value
            cell_o, cell_v = done.get(key), revenue_cells.get(key)
            if cell_o and cell_o.published and cell_v and cell_v.published and cell_v.published.mid > 0:
                return cell_o.published.mid / cell_v.published.mid
            return None

        def scaled(m: float, src: str) -> Candidate:
            return Candidate("modelo", None if r.low is None else r.low * m, r.mid * m,
                             None if r.high is None else r.high * m,
                             f"ingresos estimados {r.mid:,.0f} × margen operativo {m:.2%} ({src}; ingresos: {r.source})",
                             [])
        if not is_fy:
            q, y = period.split("_")
            m = margin_of(f"{q}_{int(y) - 1}")
            return None if m is None else scaled(m, f"el del {q.upper()} del año anterior")
        year = int(period[2:])
        missing = [q for q in (1, 2, 3, 4) if f"q{q}_{year}" not in actuals]
        if reported_q and missing:
            parts: list[tuple[float, float, float]] = []
            for q in missing:
                cell = revenue_cells.get(f"q{q}_{year}")
                m = margin_of(f"q{q}_{year - 1}")
                if cell is None or cell.published is None or m is None:
                    break
                p = cell.published
                parts.append(((p.low if p.low is not None else p.mid) * m, p.mid * m,
                              (p.high if p.high is not None else p.mid) * m))
            else:
                return Candidate("modelo", ytd + sum(x[0] for x in parts), ytd + sum(x[1] for x in parts),
                                 ytd + sum(x[2] for x in parts),
                                 f"presentado {ytd:,.0f} + trimestres pendientes (ingresos estimados × margen del "
                                 f"mismo trimestre del año anterior)", [_cite_actual(a) for a in reported_q])
        m = margin_of(f"fy{year - 1}")
        return None if m is None else scaled(m, f"el del ejercicio fy{year - 1}")
    return None


# ---------------------------------------------------------------------- lectura de la BD
def _facts(db: Any, company: Any, fact_metric: str) -> list[tuple[str, float, date | None, str | None]]:
    from sqlalchemy import select

    from app.core.source_urls import sec_filing_url
    from app.models import FinancialFact

    rows = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                  FinancialFact.metric == fact_metric)).all()
    cik = getattr(company, "cik", None)
    out = []
    for r in rows:
        try:
            url = r.source_url
        except Exception:  # noqa: BLE001 - la relación puede no estar cargada
            url = None
        # El filing exacto de la cifra, no el listado genérico de la empresa.
        url = sec_filing_url(url, getattr(r, "accession_number", None), cik)
        out.append((str(r.period), float(r.value), r.filed, url))
    return out


def _guidance_rows(db: Any, company: Any, tenant_id: int, *, current_only: bool) -> list[GuidanceRow]:
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue

    stmt = select(DeclaredInputValue).where(
        DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
        DeclaredInputValue.input_key.like("guidance.%"))
    if current_only:
        stmt = stmt.where(DeclaredInputValue.superseded_at.is_(None))
    out: list[GuidanceRow] = []
    for row in db.scalars(stmt.order_by(DeclaredInputValue.id)).all():
        parts = row.input_key.split(".")
        if len(parts) != 3 or row.base is None or row.as_of is None:
            continue
        out.append(GuidanceRow(parts[1], parts[2], None if row.low is None else float(row.low), float(row.base),
                               None if row.high is None else float(row.high), row.as_of, row.source_url,
                               row.source_quote or ""))
    return out


def build_company_consensus(db: Any, company: Any, tenant_id: int, *, today: date | None = None,
                            base_rate_for: Any = None, measured_errors: Mapping[tuple[str, str], Sequence[float]]
                            | None = None) -> dict[str, Any]:
    """Celdas de ``METRICS`` para una empresa con lo que hay en la BD (sin red)."""
    today = today or date.today()
    analyst: list[dict[str, Any]] = []
    try:
        from app.services.analyst_consensus import aggregate, history_for, reported_revenue

        analyst = aggregate(history_for(db, company, tenant_id), reported_revenue(db, company))
    except Exception:  # noqa: BLE001 - sin analistas el consenso sigue con el resto de fuentes
        analyst = []
    if measured_errors is None:
        try:
            from app.services.estimate_accuracy import company_accuracy

            measured_errors = company_accuracy(db, company, tenant_id)["measured_errors"]
        except Exception:  # noqa: BLE001 - sin medición la confianza queda «bajo · muestra pequeña»
            measured_errors = {}
    guidance = _guidance_rows(db, company, tenant_id, current_only=True)
    history = _guidance_rows(db, company, tenant_id, current_only=False)
    out: dict[str, Any] = {"ticker": company.ticker, "as_of": today.isoformat(), "version": CONSENSUS_VERSION,
                           "source_order": list(SOURCE_ORDER), "cells": []}
    rev_actuals = actuals_from_facts(_facts(db, company, FACT_METRIC["revenue"]), metric="revenue")
    if base_rate_for is None:
        from app.services.estimate_base_rates import for_annual_revenue, sector_of_cik

        sector = sector_of_cik(getattr(company, "cik", None))

        def _default_rate(acts: Mapping[str, Actual]) -> BaseRate | None:
            annual = {int(k[2:]): a.value for k, a in acts.items() if k.startswith("fy")}
            return for_annual_revenue(annual, sector=sector)
        base_rate_for = _default_rate
    rate = base_rate_for(rev_actuals)
    rev_cells: dict[str, Cell] = {}
    oi_cells: dict[str, Cell] = {}
    oi_actuals: Mapping[str, Actual] = {}
    for metric in METRICS:
        acts = rev_actuals if metric == "revenue" else actuals_from_facts(_facts(db, company, FACT_METRIC[metric]),
                                                                           metric=metric)
        cells = build_cells(metric, acts, today=today, guidance=guidance, guidance_history=history,
                            analyst=analyst, base_rate=rate if metric != "eps" else None,
                            revenue_cells=rev_cells, revenue_actuals=rev_actuals, measured_errors=measured_errors,
                            operating_cells=oi_cells if metric == "eps" else None,
                            operating_actuals=oi_actuals if metric == "eps" else None)
        if metric == "revenue":
            rev_cells = cells
        elif metric == "operating_income":
            oi_cells, oi_actuals = cells, acts
        out["cells"].extend(c.as_dict() for c in cells.values())
    if rate is not None:
        out["base_rate"] = {"group": rate.group, "p25": rate.p25, "p50": rate.p50, "p75": rate.p75, "n": rate.n,
                            "source": rate.source}
    return out
