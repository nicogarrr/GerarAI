"""Backtest point-in-time del motor de TIR para el accionista (8-nov-2026).

Uso (datos locales ya descargados; ver ``--help``):
    python scripts/backtest_irr_pit.py --sec DIR [DIR…] --px DIR [DIR…] --sub DIR --out panel.csv

Para cada fecha ``t`` (30-jun y 31-dic, 2010–2024) y cada empresa:
  1. hechos SEC companyfacts presentados ANTES de ``t`` (``irr_pit_backtest.as_of`` lo comprueba con assert),
     primera cifra publicada de cada ejercicio;
  2. precio que cotizaba en ``t`` (cierre ajustado por splits de Yahoo × splits posteriores a ``t``) y acciones
     diluidas del último ejercicio × splits entre su cierre y ``t``;
  3. comparables: hasta 8 empresas del mismo SIC de 2 dígitos y misma base (EV/EBITDA o PER), las más
     parecidas en ingresos, con su múltiplo de partida en ``t``;
  4. TIR base/bajista/alcista a 5 y 10 años con ``run_valuation`` del producto (sin guía);
  5. SOLO para puntuar: rentabilidad total anual realizada a 1, 3 y 5 años (cierre ajustado, con dividendos).
Las tasas base nunca llevan información posterior a ``t``: la tabla del producto (ingresos hasta 2019,
``rules.base_rates_known_at``) solo se usa después; antes se recalculan con lo publicado antes de ``t`` y, sin
observaciones suficientes, la regla usa su respaldo sin datos (0 / 3 / 6 %). Con ``--pit-base-rates`` se
recalculan en todas las fechas.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.valuation import irr_pit_backtest as bt  # noqa: E402
from app.valuation import shareholder_irr_rules as rules  # noqa: E402

DATES = [date(y, m, d) for y in range(2010, 2025) for m, d in ((6, 30), (12, 31))]
HORIZONS = (1, 3, 5)


def _find(dirs: list[str], name: str) -> str | None:
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _prices(path: str) -> tuple[list[tuple[date, float]], list[tuple[date, float]], list[tuple[date, float]]]:
    close, adj, splits = [], [], []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            d = date.fromisoformat(r["Date"][:10])
            try:
                c, a = float(r["Close"]), float(r["Adj Close"])
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(c) and math.isfinite(a)):
                continue
            close.append((d, c))
            adj.append((d, a))
            sp = float(r.get("Stock Splits") or 0)
            if sp and sp != 1:
                splits.append((d, sp))
    return close, adj, splits


def company_pass(args: tuple[str, dict]) -> list[dict]:
    """Insumos point-in-time de una empresa en todas las fechas (o el motivo por el que no hay)."""
    ticker, cfg = args
    sec = _find(cfg["sec"], f"{ticker}.json.gz")
    px = _find(cfg["px"], f"{cfg['listing'].get(ticker, ticker)}.csv")
    if not sec or not px:
        return [{"ticker": ticker, "t": t.isoformat(), "status": "sin_datos"} for t in DATES]
    with open(sec, "rb") as fh:
        facts = bt.facts_from_companyfacts(json.loads(gzip.decompress(fh.read())))
    close, adj, splits = _prices(px)
    sub = cfg["subs"].get(ticker, {})
    co = SimpleNamespace(sic_code=sub.get("sic"), sector=sub.get("sicDescription") or "", industry="",
                         company_type="")
    from app.services.shareholder_irr_service import _is_financial
    financial = _is_financial(cast(Any, co))  # mismo criterio SIC/sector que el producto
    units = {f.unit for f in facts if f.metric == "revenue"}
    currency = "USD" if "USD" in units or not units else sorted(units)[0]
    last_px = close[-1][0] if close else None
    rows = []
    for t in DATES:
        row: dict = {"ticker": ticker, "t": t.isoformat(), "sic": sub.get("sic"), "financial": financial,
                     "currency": currency}
        seen = bt.as_of(facts, t)
        row["max_filed"] = max((f.filed for f in seen), default=None)
        row["rev_hist"] = bt.annual(seen, "revenue")
        pc, pd_ = bt.price_on(close, t)
        if pc is None or pd_ is None or (t - pd_).days > 7:
            row["status"] = "sin_precio"
            rows.append(row)
            continue
        raw = pc * bt.split_factor(splits, t, last_px or t)
        row["price"] = raw
        for h in HORIZONS:
            row[f"tsr{h}"] = bt.total_return(adj, t, h)
        try:
            inp = bt.build_inputs(seen, t=t, price=raw, splits=splits, financial=financial, currency=currency)
        except (ValueError, ZeroDivisionError) as exc:
            row["status"] = "sin_insumos: " + str(exc)[:80]
            rows.append(row)
            continue
        row["status"] = "ok"
        row["inputs"] = inp
        row["method"] = inp.method["chosen"]
        row["basis"] = inp.start.basis
        row["multiple"] = inp.start.multiple
        row["revenue"] = inp.start.revenue
        row["market_cap"] = inp.start.market_cap
        row["fy_end"] = inp.fy_end.isoformat()
        rows.append(row)
    return rows


def pit_base_rates(rows_t: list[dict], min_n: int = 20) -> dict[str, dict[str, float]] | None:
    """Tasas base con lo publicado antes de t: TCAC 5 años siguientes según la TCAC de los 3 previos."""
    obs: dict[str, list[float]] = {b[0]: [] for b in rules.BASE_RATE_BUCKETS}
    for r in rows_t:
        rev = r.get("rev_hist") or {}
        for s in rev:
            a, b, c = rev.get(s - 3), rev.get(s), rev.get(s + 5)
            if a and b and c and a > 0 and b > 0 and c > 0:
                name, _ = rules.base_rate_for((b / a) ** (1 / 3) - 1)
                if name:
                    obs[name].append((c / b) ** (1 / 5) - 1)
    out = {}
    for name, v in obs.items():
        if len(v) < min_n:
            return None
        v.sort()
        q = lambda p: v[int(p * (len(v) - 1))]  # noqa: E731
        out[name] = {"p25": q(0.25), "p50": q(0.5), "p75": q(0.75), "n": len(v)}
    return out


def value_date(args: tuple[str, list[dict], bool]) -> list[dict]:
    t, rows, pit_rates = args
    # La tabla del producto usa ingresos hasta 2019: en fechas anteriores llevaría información futura. Ahí se
    # recalcula con lo publicado antes de t y, si aún no hay observaciones suficientes, la regla usa su
    # respaldo sin datos (tabla vacía → 0 / 3 / 6 %, con aviso), nunca la tabla del producto.
    leaky = rules.base_rates_known_at(date.fromisoformat(t)) is None
    shipped = dict(rules.BASE_RATES)
    rates = pit_base_rates(rows) if (pit_rates or leaky) else None
    ok = [r for r in rows if r.get("status") == "ok"]
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k not in ("rev_hist",)}
        inp = r.pop("inputs", None)
        if inp is None:
            out.append(r)
            continue
        lo, hi = rules.MULTIPLE_BOUNDS[inp.start.basis]
        peers = [p for p in ok if p is not r and p["ticker"] != r["ticker"] and p["basis"] == r["basis"]
                 and str(p.get("sic") or "")[:2] == str(r.get("sic") or "")[:2] and p.get("multiple")
                 and lo / 2 <= p["multiple"] <= hi * 2 and p.get("revenue", 0) > 0]
        rv = max(r.get("revenue") or 1e-9, 1e-9)
        peers.sort(key=lambda p: abs(math.log(p["revenue"] / rv)))
        mult = [p["multiple"] for p in peers[:8]]
        r["n_peers"] = len(mult)
        if pit_rates and rates is None:
            r["status"] = "sin_tasa_base_pit"
            out.append(r)
            continue
        if pit_rates or leaky:
            r["base_rates"] = "pit" if rates is not None else "sin_datos_previos"
            rules.BASE_RATES.clear()
            rules.BASE_RATES.update(rates or {})
        else:
            r["base_rates"] = "producto"
        try:
            v = bt.value(inp, peer_multiples=mult)
            r.update({k: v[k] for k in ("bear", "base", "bull", "bear_10", "base_10", "bull_10", "weighted")})
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            r["status"] = "sin_tir: " + str(exc)[:80]
        finally:
            rules.BASE_RATES.clear()
            rules.BASE_RATES.update(shipped)
        out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", nargs="+", required=True)
    ap.add_argument("--px", nargs="+", required=True)
    ap.add_argument("--sub", required=True)
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--listing", default="", help="TICKER=FICHERO,… cotización en la moneda de las cuentas")
    ap.add_argument("--pit-base-rates", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tickers = a.tickers or sorted({p[:-8] for d in a.sec for p in os.listdir(d) if p.endswith(".json.gz")})
    subs = {}
    for t in tickers:
        p = os.path.join(a.sub, f"{t}.json")
        if os.path.exists(p):
            with open(p) as fh:
                subs[t] = json.load(fh)
    listing = dict(x.split("=") for x in a.listing.split(",") if "=" in x)
    cfg = {"sec": a.sec, "px": a.px, "subs": subs, "listing": listing}
    with ProcessPoolExecutor(a.workers) as ex:
        per_co = list(ex.map(company_pass, [(t, cfg) for t in tickers], chunksize=4))
    by_t: dict[str, list[dict]] = {}
    for rows in per_co:
        for r in rows:
            by_t.setdefault(r["t"], []).append(r)
    # garantía de no mirar al futuro: ningún hecho usado se presentó en o después de t
    for t, rows in by_t.items():
        for r in rows:
            mf = r.get("max_filed")
            assert mf is None or mf < date.fromisoformat(t), (r["ticker"], t, mf)
    with ProcessPoolExecutor(a.workers) as ex:
        dated = list(ex.map(value_date, [(t, rows, a.pit_base_rates) for t, rows in sorted(by_t.items())]))
    cols = ["ticker", "t", "status", "sic", "financial", "currency", "method", "basis", "price", "market_cap",
            "revenue", "multiple", "n_peers", "fy_end", "max_filed", "bear", "base", "bull", "bear_10", "base_10",
            "bull_10", "weighted", "base_rates", "tsr1", "tsr3", "tsr5"]
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for rows in dated:
            for r in rows:
                w.writerow(r)
    n_ok = sum(1 for rows in dated for r in rows if r.get("base") is not None)
    print(json.dumps({"rows": sum(len(r) for r in dated), "valued": n_ok,
                      "median_base": median([r["base"] for rows in dated for r in rows if r.get("base") is not None])
                      if n_ok else None}))


if __name__ == "__main__":
    main()
