"""Backtest point-in-time del sistema DCA real de la app frente a DCA plano, comprar y mantener y DCA en SPY.

Usa EXACTAMENTE las reglas de la app, importadas del codigo de produccion:

* nivel mensual (1X-4X, recorte ligero/fuerte): ``dca_signal_engine.evaluate_series``
  con ``DEFAULT_PARAMS`` (o una variante para la sensibilidad);
* importes del mes: ``plan_contribution_split.split_contribution`` (peso nivel²,
  recortes 0, valores poco volatiles 2X-4X como 1X, nivel caducado o ausente
  como 1X) y el tope de concentracion ``_apply_concentration_cap`` (2x el peso base);
* la app NO vende en recorte: la zona de recorte solo deja de recibir dinero (y
  avisa si ``DCA_ALERT_TRIMS``). Vender en recorte se mide aparte como
  diagnostico (``trim_exec``), con impuesto sobre plusvalias.

Sin look-ahead (se comprueba en cada ejecucion; ver ``assert_no_leak``):

* la compra del mes ``t`` usa el veredicto CONFIRMADO del mes ``t-1`` y se
  ejecuta al primer cierre de ``t`` (la convencion de ``app/services/dca_backtest.py``);
* el veredicto de un mes solo ve cierres hasta ese mes: se recalcula sobre la
  serie truncada en una muestra de (valor, mes) y debe coincidir;
* un valor solo es elegible desde su primer filing en la SEC (``filed`` de
  companyfacts) y desde que tiene precio; nunca con fechas posteriores.

Puro: sin DB ni red. Precios: CSV ``Date, Close|Adj Close[, Low]`` (cierre
ajustado como la app). Los niveles son invariantes a la escala, asi que el ajuste
por dividendos/splits no mete informacion futura en los ratios.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import json
import math
import random
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import plan_contribution_split as pcs  # noqa: E402
from app.services.dca_signal_engine import (  # noqa: E402
    DEFAULT_PARAMS,
    DailyBar,
    DcaParams,
    evaluate_series,
)

COST = 0.001  # comision por compra/venta (la del backtest de calibracion)
TAX_RATE = 0.21  # IRPF del ahorro (tramo 6-50 k EUR), solo para el diagnostico trim_exec
TRIM_SELL = {-1: 0.10, -2: 0.25}  # fraccion vendida en el diagnostico trim_exec
LEVELS = (4, 3, 2, 1, -1, -2)


def month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def month_label(m: int) -> str:
    return f"{m // 12:04d}-{m % 12 + 1:02d}"


@dataclass
class Series:
    """Serie mensual de un valor: primer y ultimo cierre de cada mes y veredicto confirmado."""

    symbol: str
    bars: list[DailyBar]
    first: dict[int, float] = field(default_factory=dict)
    last: dict[int, float] = field(default_factory=dict)
    level: dict[int, int] = field(default_factory=dict)
    vol: dict[int, float | None] = field(default_factory=dict)
    eligible_from: int | None = None  # mes del primer filing SEC (None = sin filtro)


def read_price_csv(path: Path) -> list[DailyBar]:
    out: dict[date, DailyBar] = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw = row.get("Adj Close") or row.get("Close")
            try:
                close = float(raw) if raw not in (None, "") else math.nan
            except ValueError:
                continue
            if not math.isfinite(close) or close <= 0:
                continue  # sin precio: el mes se construye con los cierres validos
            day = datetime.fromisoformat(str(row["Date"])[:10]).date()
            low_raw = row.get("Low")
            low = None
            if low_raw not in (None, "") and row.get("Adj Close"):
                # Low viene sin ajustar cuando hay Adj Close: se reescala con el factor del dia.
                try:
                    low = float(low_raw) * close / float(row["Close"])
                except (ValueError, ZeroDivisionError):
                    low = None
            elif low_raw not in (None, ""):
                with contextlib.suppress(ValueError):
                    low = float(low_raw)
            if low is not None and (not math.isfinite(low) or low <= 0):
                low = None
            out[day] = DailyBar(day=day, close=close, low=low)
    return [out[d] for d in sorted(out)]


def first_sec_filing_month(path: Path) -> int | None:
    """Mes del primer ``filed`` de companyfacts (10-K/10-Q/20-F/40-F/6-K)."""
    with gzip.open(path, "rt") as fh:
        facts = json.load(fh).get("facts", {})
    first: str | None = None
    for taxonomy in facts.values():
        for concept in taxonomy.values():
            for unit_rows in concept.get("units", {}).values():
                for row in unit_rows:
                    filed = row.get("filed")
                    if filed and (first is None or filed < first):
                        first = filed
    return month_index(date.fromisoformat(first)) if first else None


def build_series(symbol: str, bars: list[DailyBar], params: DcaParams = DEFAULT_PARAMS) -> Series:
    s = Series(symbol=symbol, bars=bars)
    for b in bars:
        m = month_index(b.day)
        s.first.setdefault(m, b.close)
        s.last[m] = b.close
    for v in evaluate_series(bars, params=params, month_complete=True):
        if v.status != "confirmed":
            continue
        m = int(v.period[:4]) * 12 + int(v.period[5:7]) - 1
        s.level[m] = int(v.level)
        vol = v.metrics.get("vol")
        s.vol[m] = float(vol) if vol is not None else None
    return s


def assert_no_leak(
    series: Sequence[Series], *, samples: int = 200, seed: int = 7, params: DcaParams = DEFAULT_PARAMS
) -> int:
    """Recalcula el veredicto de meses al azar con la serie TRUNCADA en ese mes.

    Si el nivel o la vol difieren, el veredicto usaba datos posteriores: falla.
    Devuelve cuantos (valor, mes) se comprobaron.
    """
    rng = random.Random(seed)
    pool = [(s, m) for s in series for m in s.level]
    checked = 0
    for s, m in rng.sample(pool, min(samples, len(pool))):
        cut = [b for b in s.bars if month_index(b.day) <= m]
        trunc = [
            v for v in evaluate_series(cut, params=params, month_complete=True) if v.status == "confirmed"
        ]
        assert trunc, f"{s.symbol} {month_label(m)}: sin veredicto truncado"
        v = trunc[-1]
        assert v.period == month_label(m), (s.symbol, v.period, month_label(m))
        assert int(v.level) == s.level[m], f"FUGA {s.symbol} {month_label(m)}: {v.level} != {s.level[m]}"
        vol = v.metrics.get("vol")
        assert (vol is None and s.vol[m] is None) or (
            vol is not None and s.vol[m] is not None and abs(float(vol) - s.vol[m]) < 1e-9
        ), f"FUGA vol {s.symbol} {month_label(m)}"
        assert max(b.day for b in cut) <= s.bars[-1].day
        checked += 1
    return checked


@contextlib.contextmanager
def plan_constants(*, low_vol: float | None = None, cap: float | None = None) -> Iterator[None]:
    """Cambia temporalmente los umbrales del reparto (solo sensibilidad, nunca la app)."""
    old = (pcs.LOW_VOLATILITY_THRESHOLD, pcs.CONCENTRATION_CAP)
    try:
        if low_vol is not None:
            pcs.LOW_VOLATILITY_THRESHOLD = low_vol
        if cap is not None:
            pcs.CONCENTRATION_CAP = Decimal(str(cap))
        yield
    finally:
        pcs.LOW_VOLATILITY_THRESHOLD, pcs.CONCENTRATION_CAP = old


def irr_annual(flows: Sequence[float], final_value: float) -> float:
    """TIR anual de aportaciones mensuales al inicio de cada mes y valor final al cierre del ultimo."""
    n = len(flows)

    def fv(rate_m: float) -> float:
        return sum(c * (1 + rate_m) ** (n - i) for i, c in enumerate(flows))

    lo, hi = -0.99, 1.0
    if sum(flows) <= 0:
        return math.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        if fv((1 + mid) ** (1 / 12) - 1) > final_value:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


@dataclass
class Result:
    strategy: str
    irr: float
    twr_cagr: float
    max_dd: float
    invested: float
    final: float
    turnover: float  # ventas / valor medio de la cartera, anualizado (0 si nunca vende)
    buys_per_year: float = 0.0  # compras / valor medio, anualizado
    tax_paid: float = 0.0
    monthly_returns: list[float] = field(default_factory=list)
    curve: list[float] = field(default_factory=list)
    zone_months: dict[int, int] = field(default_factory=dict)


def simulate(
    universe: Sequence[Series],
    months: Sequence[int],
    *,
    strategy: str,
    budget_per_stock: float = 100.0,
    spy: Series | None = None,
) -> Result:
    """Simula una cartera mes a mes.

    strategy: ``app`` (reglas de la app), ``app_nocap`` (sin tope de concentracion), ``plano``, ``trim_exec``
    (app + vender 10/25 % en recorte, con impuesto), ``buy_hold`` (todo el dinero
    al inicio, a partes iguales) o ``spy`` (DCA en SPY con el mismo dinero).
    """
    k = len(universe)
    contrib = k * budget_per_stock
    shares = [0.0] * k
    basis = [0.0] * k
    spy_shares = 0.0
    cash = 0.0
    flows: list[float] = []
    prev_v = 0.0
    idx = 1.0
    peak = 1.0
    mdd = 0.0
    traded = 0.0
    sold_value = 0.0
    values: list[float] = []
    rets: list[float] = []
    tax = 0.0
    zones: dict[int, int] = {}
    last_px = [math.nan] * k
    total_cash = contrib * len(months)
    for step, t in enumerate(months):
        px = [s.first.get(t, math.nan) for s in universe]
        alive = [math.isfinite(p) for p in px]
        for i, p in enumerate(px):
            if alive[i]:
                last_px[i] = p
        flow = contrib if strategy != "buy_hold" else (total_cash if step == 0 else 0.0)
        flows.append(contrib)
        cash += flow
        if strategy == "spy":
            assert spy is not None
            p = spy.first[t]
            spy_shares += cash * (1 - COST) / p
            traded += cash
            cash = 0.0
        elif strategy == "buy_hold":
            if step == 0:
                live = [i for i in range(k) if alive[i]]
                for i in live:
                    amt = cash / len(live)
                    shares[i] += amt * (1 - COST) / px[i]
                    basis[i] += amt
                traded += cash
                cash = 0.0
        else:
            cands = []
            live = [i for i in range(k) if alive[i] and t >= (universe[i].eligible_from or 0)]
            for i in live:
                s = universe[i]
                lvl = s.level.get(t - 1) if strategy != "plano" else None
                # Sin veredicto del mes anterior (historia corta o hueco): la app pesa 1X.
                if lvl is not None:
                    zones[lvl] = zones.get(lvl, 0) + 1
                cands.append(
                    pcs.SplitCandidate(
                        ticker=s.symbol,
                        base_weight=Decimal(1),
                        dca_level=lvl,
                        dca_period=month_label(t - 1) if lvl is not None else None,
                        dca_status="confirmed" if lvl is not None else None,
                        dca_vol=s.vol.get(t - 1) if strategy != "plano" else None,
                    )
                )
            if strategy == "trim_exec":
                for i in live:
                    lvl = universe[i].level.get(t - 1)
                    frac = TRIM_SELL.get(lvl or 0, 0.0)
                    if frac and shares[i] > 0:
                        sold = shares[i] * frac
                        proceeds = sold * px[i] * (1 - COST)
                        cost_part = basis[i] * frac
                        gain = proceeds - cost_part
                        t_amt = max(gain, 0.0) * TAX_RATE
                        tax += t_amt
                        cash += proceeds - t_amt
                        sold_value += sold * px[i]
                        shares[i] -= sold
                        basis[i] -= cost_part
            if strategy in ("app", "trim_exec") and cands:  # app_nocap: sin tope
                mv = {universe[i].symbol: Decimal(str(shares[i] * px[i])) for i in live if shares[i] > 0}
                # Como la app: valor de mercado de las posiciones vivas; sin posiciones, sin tope.
                cands = pcs._apply_concentration_cap(cands, mv or None)
            split = pcs.split_contribution(Decimal(str(round(cash, 2))), cands) if cands else None
            if split and split["status"] == "ok":
                by = {a["ticker"]: a["amount"] for a in split["allocations"]}
                spent = 0.0
                for i in live:
                    amt = by.get(universe[i].symbol, 0.0)
                    if amt > 0:
                        shares[i] += amt * (1 - COST) / px[i]
                        basis[i] += amt
                        spent += amt
                traded += spent
                cash -= spent
                cash = max(cash, 0.0)
            # all_trim / sin candidatos: la cuota queda en liquidez y se suma al mes siguiente.
        lp = [s.last.get(t, math.nan) for s in universe]
        v = cash + sum(
            sh * (lp[i] if math.isfinite(lp[i]) else last_px[i]) for i, sh in enumerate(shares) if sh
        )
        if strategy == "spy":
            assert spy is not None
            v = cash + spy_shares * spy.last[t]
        base = prev_v + flow
        r = v / base - 1 if base > 0 else 0.0
        rets.append(r)
        idx *= 1 + r
        peak = max(peak, idx)
        mdd = min(mdd, idx / peak - 1)
        prev_v = v
        values.append(v)
    n_years = len(months) / 12
    avg_v = sum(values) / len(values) if values else 1.0
    final = values[-1]
    if strategy == "buy_hold":
        irr = (final / total_cash) ** (1 / n_years) - 1
    else:
        irr = irr_annual(flows, final)
    twr = idx ** (1 / n_years) - 1
    return Result(
        strategy=strategy,
        irr=irr,
        twr_cagr=twr,
        max_dd=mdd,
        invested=total_cash,
        final=final,
        turnover=sold_value / max(avg_v, 1e-9) / n_years,
        buys_per_year=traded / max(avg_v, 1e-9) / n_years,
        tax_paid=tax,
        monthly_returns=rets,
        curve=values,
        zone_months=zones,
    )


def block_bootstrap_mean(
    x: Sequence[float], *, block: int = 12, draws: int = 2000, seed: int = 11
) -> tuple[float, float, float]:
    """Media y IC 95 % por bootstrap de bloques moviles (circular) de ``block`` meses."""
    n = len(x)
    rng = random.Random(seed)
    nb = math.ceil(n / block)
    means = []
    for _ in range(draws):
        acc = 0.0
        cnt = 0
        for _b in range(nb):
            start = rng.randrange(n)
            for j in range(block):
                if cnt >= n:
                    break
                acc += x[(start + j) % n]
                cnt += 1
        means.append(acc / n)
    means.sort()
    return sum(x) / n, means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def load_universe(
    px_dirs: Sequence[Path], symbols: Sequence[str], sec_dirs: Sequence[Path], params: DcaParams
) -> list[Series]:
    out = []
    for sym in symbols:
        best: list[DailyBar] | None = None
        for d in px_dirs:
            p = d / f"{sym}.csv"
            if p.exists():
                bars = read_price_csv(p)
                if bars and (best is None or bars[0].day < best[0].day):
                    best = bars
        if not best:
            continue
        s = build_series(sym, best, params)
        for d in sec_dirs:
            p = d / f"{sym.split('.')[0]}.json.gz"
            if p.exists():
                s.eligible_from = first_sec_filing_month(p)
                break
        out.append(s)
    return out


STRATEGIES = ("app", "app_nocap", "plano", "trim_exec", "buy_hold", "spy")


def _median(xs: Sequence[float]) -> float:
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def run_benchmark(
    universe: Sequence[Series],
    spy: Series,
    months: Sequence[int],
    *,
    portfolios: int,
    sizes: Sequence[int],
    seed: int,
    strategies: Sequence[str] = STRATEGIES,
    fixed: Sequence[Series] | None = None,
) -> dict:
    """Carteras aleatorias (y opcionalmente una cartera fija) con las mismas fechas y dinero.

    Devuelve por estrategia la mediana de TIR, CAGR (TWR), caida maxima, rotacion
    e impuesto; la ventaja de la app frente al plano (mediana, % de carteras
    ganadas, peor cartera) y el IC 95 % por bootstrap de bloques de 12 meses de
    la diferencia media de rentabilidad mensual; y el % de meses en cada zona.
    """
    t0 = months[0]
    elig = [s for s in universe if all(m in s.first for m in months) and (t0 - 1) in s.level]
    rng = random.Random(seed)
    per: dict[str, list[Result]] = {st: [] for st in strategies}
    for size in sizes:
        for _ in range(portfolios):
            pick = rng.sample(elig, size)
            for st in strategies:
                per[st].append(simulate(pick, months, strategy=st, spy=spy))
    out: dict = {"eligible": len(elig), "portfolios": len(per[strategies[0]]), "strategies": {}}
    for st, res in per.items():
        out["strategies"][st] = {
            "irr_median": _median([r.irr for r in res]),
            "twr_cagr_median": _median([r.twr_cagr for r in res]),
            "max_dd_median": _median([r.max_dd for r in res]),
            "turnover_median": _median([r.turnover for r in res]),
            "tax_over_invested_median": _median([r.tax_paid / r.invested for r in res]),
        }
    if "app" in per and "plano" in per:
        diffs = [a.irr - b.irr for a, b in zip(per["app"], per["plano"], strict=True)]
        n = len(per["app"])
        monthly = [
            sum(
                a.monthly_returns[i] - b.monthly_returns[i]
                for a, b in zip(per["app"], per["plano"], strict=True)
            )
            / n
            for i in range(len(months))
        ]
        mean, lo, hi = block_bootstrap_mean(monthly)
        out["app_vs_plano"] = {
            "irr_diff_median": _median(diffs),
            "irr_diff_mean": sum(diffs) / n,
            "win_share": sum(d > 0 for d in diffs) / n,
            "worst": min(diffs),
            "monthly_diff_annualized": mean * 12,
            "ci95_block12": [lo * 12, hi * 12],
        }
        zones: dict[int, int] = {}
        for r in per["app"]:
            for k, v in r.zone_months.items():
                zones[k] = zones.get(k, 0) + v
        tot = sum(zones.values()) or 1
        out["zone_share"] = {str(k): zones.get(k, 0) / tot for k in LEVELS}
    if fixed:
        out["fixed"] = {
            st: {"irr": r.irr, "twr_cagr": r.twr_cagr, "max_dd": r.max_dd, "turnover": r.turnover}
            for st in strategies
            for r in [simulate(fixed, months, strategy=st, spy=spy)]
        }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--px", nargs="+", type=Path, required=True, help="directorios con <TICKER>.csv")
    ap.add_argument(
        "--sec", nargs="*", type=Path, default=[], help="directorios con <TICKER>.json.gz (companyfacts)"
    )
    ap.add_argument("--symbols", type=Path, required=True, help="fichero con un ticker por linea")
    ap.add_argument(
        "--fixed", type=Path, default=None, help="cartera fija (un ticker por linea), p. ej. la de Nico"
    )
    ap.add_argument("--start", default="2010-01")
    ap.add_argument("--end", default="2024-12")
    ap.add_argument("--portfolios", type=int, default=100, help="carteras aleatorias por tamano")
    ap.add_argument("--sizes", default="10,15,20")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--leak-samples", type=int, default=400)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    syms = [x.strip() for x in a.symbols.read_text().split() if x.strip()]
    fixed_syms = [x.strip() for x in a.fixed.read_text().split() if x.strip()] if a.fixed else []
    uni = load_universe(a.px, list(dict.fromkeys([*syms, *fixed_syms, "SPY"])), a.sec, DEFAULT_PARAMS)
    spy = next(s for s in uni if s.symbol == "SPY")
    uni = [s for s in uni if s.symbol != "SPY"]
    checked = assert_no_leak(uni, samples=a.leak_samples)
    y0, m0 = (int(x) for x in a.start.split("-"))
    y1, m1 = (int(x) for x in a.end.split("-"))
    months = list(range(y0 * 12 + m0 - 1, y1 * 12 + m1))
    t0 = months[0]
    # Universo PIT: con filing SEC anterior al inicio (nunca una fecha posterior).
    pit = [s for s in uni if s.symbol in syms and s.eligible_from is not None and s.eligible_from <= t0]
    fixed = [s for s in uni if s.symbol in fixed_syms]
    out = run_benchmark(
        pit,
        spy,
        months,
        portfolios=a.portfolios,
        sizes=[int(x) for x in a.sizes.split(",")],
        seed=a.seed,
        fixed=fixed or None,
    )
    out["checked_no_leak"] = checked
    out["window"] = [month_label(months[0]), month_label(months[-1])]
    a.out.write_text(json.dumps(out, indent=1))
    print(
        json.dumps({"checked_no_leak": checked, "eligible": out["eligible"], "portfolios": out["portfolios"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
