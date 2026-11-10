"""Recalcula ``app/data/estimate_base_rates.json`` (tasas base de crecimiento y de margen), point-in-time.

Uso::

    python scripts/estimate_base_rates.py COMPANYFACTS_ZIP [--sector-json app/data/estimate_base_rates.json] \
        [--workers 8] > app/data/estimate_base_rates.json

- ``COMPANYFACTS_ZIP``: el fichero masivo gratuito de la SEC con todos los companyfacts XBRL
  (``https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip``, una sola descarga:
  ~1,4 GB, sin clave y sin una petición por empresa). Se lee en streaming, sin descomprimirlo.
- ``--sector-json``: de dónde sale el SIC de cada CIK (``sector_by_cik`` de la tabla anterior,
  medido en ``data.sec.gov/submissions``); un CIK sin SIC conocido va al sector «otros».

Regla (fijada antes de mirar los resultados): una observación es (empresa, año de
partida ``y``) con ingresos ≥ 10 M$ en ``y`` y dato en ``y−3`` y ``y+h``. Cada cifra anual
(duración de 350 a 380 días, formularios 10-K/20-F/40-F y sus enmiendas) es la PRIMERA
publicada para ese cierre (la de menor fecha de presentación), y solo vale si se presentó
como mucho 400 días después del cierre: así ni el punto de partida ni el resultado llevan
reexpresiones posteriores (una cifra que solo aparece años después como comparativa no
cuenta). El año es el del punto medio del ejercicio (cierre − 182 días). Se agrupa por
tamaño (ingresos en ``y``), crecimiento previo (TCAC ``y−3``→``y``) y sector (división
SIC); se guardan p5…p95 (cada 5 puntos), p10/p25/p50/p75/p90 y n del TCAC ``y``→``y+h``
(h = 1, 2, 3, 5, 7, 10) y lo mismo de la variación del margen operativo en puntos
(``margen(y+h) − margen(y)``, solo |Δ| < 100 puntos). Ingresos por año: la primera
etiqueta presente en el orden Revenues, RevenueFromContractWithCustomerExcludingAssessedTax,
SalesRevenueNet. Grupos con n < 30 no se guardan. Sesgo que queda: solo empresas que
presentan en XBRL (desde 2009–2011); las que dejaron de presentar sí están (supervivencia
no filtrada), pero no hay dato de por qué dejaron de hacerlo.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import zipfile
from datetime import date, timedelta
from multiprocessing import Pool

REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
OP_TAG = "OperatingIncomeLoss"
FORMS = frozenset({"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"})
HORIZONS = (1, 2, 3, 5, 7, 10)
MIN_REVENUE = 10e6
MIN_N = 30
MAX_FILING_LAG_DAYS = 400
GRID = tuple(round(0.05 * i, 2) for i in range(1, 20))  # p5 … p95
SIZE = (("<100M", 0, 1e8), ("100M-1B", 1e8, 1e9), ("1B-10B", 1e9, 1e10), (">10B", 1e10, float("inf")))
PRIOR = (("decrece", float("-inf"), 0.0), ("0-5 %", 0.0, 0.05), ("5-10 %", 0.05, 0.10), ("10-20 %", 0.10, 0.20),
         ("> 20 %", 0.20, float("inf")))
SECTORS = (("mineria_energia", 1000, 1500), ("construccion", 1500, 1800), ("manufactura", 2000, 4000),
           ("transporte_utilities_telecom", 4000, 5000), ("mayorista", 5000, 5200), ("minorista", 5200, 6000),
           ("finanzas", 6000, 6800), ("servicios", 7000, 9000))
SECTOR_NAMES = [b[0] for b in SECTORS]


def bucket(table, x):
    for name, lo, hi in table:
        if lo <= x < hi:
            return name
    return None


def pct(values, q):
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def annual_points(units):
    """{cierre: [primera fecha, primera cifra, última fecha, última cifra]} de los hechos anuales en USD."""
    per: dict[str, list] = {}
    for u in units:
        if u.get("form") not in FORMS or not u.get("start") or not u.get("end") or not u.get("filed"):
            continue
        try:
            days = (date.fromisoformat(u["end"]) - date.fromisoformat(u["start"])).days
        except ValueError:
            continue
        if not 350 <= days <= 380:
            continue
        cur, filed, val = per.get(u["end"]), u["filed"], float(u["val"])
        if cur is None:
            per[u["end"]] = [filed, val, filed, val]
            continue
        if filed < cur[0]:
            cur[0], cur[1] = filed, val
        if filed > cur[2]:
            cur[2], cur[3] = filed, val
    return per


def yearly(per, *, mode: str = "first"):
    """{año: cifra} con la regla de arriba (``mode='last'`` solo para medir el sesgo de la tabla anterior)."""
    out: dict[int, tuple[str, float]] = {}
    for end, (f_first, v_first, _f_last, v_last) in per.items():
        e = date.fromisoformat(end)
        if mode == "first" and (date.fromisoformat(f_first) - e).days > MAX_FILING_LAG_DAYS:
            continue
        year = (e - timedelta(days=182)).year
        if year not in out or end > out[year][0]:  # dos cierres en un año (cambio de ejercicio): el último
            out[year] = (end, v_first if mode == "first" else v_last)
    return {y: v for y, (_e, v) in out.items()}


def company(raw: bytes):
    j = json.loads(raw)
    g = (j.get("facts") or {}).get("us-gaap") or {}
    pts = {t: annual_points(((g.get(t) or {}).get("units") or {}).get("USD") or []) for t in REVENUE_TAGS + (OP_TAG,)}
    pts = {t: p for t, p in pts.items() if p}
    if not any(t in pts for t in REVENUE_TAGS):
        return None
    return int(j.get("cik") or 0), pts


def _chunk(args):
    path, names = args
    z = zipfile.ZipFile(path)
    out = []
    for n in names:
        try:
            got = company(z.read(n))
        except (ValueError, KeyError):
            continue
        if got:
            out.append(got)
    return out


def load(path, workers):
    names = [n for n in zipfile.ZipFile(path).namelist() if n.endswith(".json")]
    chunks = [(path, names[i:i + 200]) for i in range(0, len(names), 200)]
    if workers <= 1:
        return [c for args in chunks for c in _chunk(args)]
    with Pool(workers) as pool:
        return [c for part in pool.imap_unordered(_chunk, chunks) for c in part]


def series(pts, mode):
    rev: dict[int, float] = {}
    for tag in REVENUE_TAGS[::-1]:  # la primera etiqueta del orden gana: se escribe la última
        rev.update(yearly(pts.get(tag, {}), mode=mode))
    return rev, yearly(pts.get(OP_TAG, {}), mode=mode)


def observations(companies, sector_of, mode):
    obs: dict[tuple, dict[str, list[float]]] = {}
    for cik, pts in companies:
        rev, op = series(pts, mode)
        sector = sector_of.get(cik) or "otros"
        for y, r0 in rev.items():
            past = rev.get(y - 3)
            if r0 < MIN_REVENUE or not past or past <= 0:
                continue
            prior = (r0 / past) ** (1 / 3) - 1
            size, pg = bucket(SIZE, r0), bucket(PRIOR, prior)
            for h in HORIZONS:
                rh = rev.get(y + h)
                if rh is None or rh <= 0:
                    continue
                g = (rh / r0) ** (1 / h) - 1
                margin = None
                o0, oh = op.get(y), op.get(y + h)
                if o0 is not None and oh is not None:
                    margin = oh / rh - o0 / r0
                for key in ((size, pg, sector), (size, pg, "*"), ("*", pg, "*"), ("*", "*", "*")):
                    slot = obs.setdefault((h,) + key, {"growth": [], "margin": []})
                    slot["growth"].append(g)
                    if margin is not None and abs(margin) < 1.0:
                        slot["margin"].append(margin)
    return obs


def summarize(values, *, grid: bool):
    item = {q: round(pct(values, p), 4) for q, p in (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75),
                                                       ("p90", .9))}
    if grid:
        item["q"] = [round(pct(values, p), 4) for p in GRID]
    item["n"] = len(values)
    return item


def revisions(companies):
    """Cuánto cambian después las cifras de ingresos: primera publicada frente a la última."""
    gaps = []
    for _cik, pts in companies:
        for tag in REVENUE_TAGS:
            for end, (f_first, v_first, _fl, v_last) in pts.get(tag, {}).items():
                if v_first > 0 and (date.fromisoformat(f_first) - date.fromisoformat(end)).days <= MAX_FILING_LAG_DAYS:
                    gaps.append(abs(v_last / v_first - 1))
    changed = [g for g in gaps if g > 0.005]
    return {"cifras": len(gaps), "reexpresadas_mas_0_5pct": len(changed),
            "pct_reexpresadas": round(len(changed) / len(gaps), 4) if gaps else None,
            "mediana_cambio_reexpresadas": round(statistics.median(changed), 4) if changed else None,
            "p90_cambio_reexpresadas": round(pct(changed, 0.9), 4) if changed else None}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("companyfacts_zip")
    ap.add_argument("--sector-json", default="app/data/estimate_base_rates.json")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    with open(a.sector_json, encoding="utf-8") as fh:
        old = json.load(fh)
    old_names = old["buckets"]["sector"]
    sector_of = {int(c): old_names[i] for c, i in (old.get("sector_by_cik") or {}).items()
                 if isinstance(i, int) and 0 <= i < len(old_names) and old_names[i] in SECTOR_NAMES}
    companies = load(a.companyfacts_zip, a.workers)
    obs = observations(companies, sector_of, "first")
    groups = {}
    for (h, size, pg, sector), slot in sorted(obs.items()):
        item = {m: summarize(v, grid=True) for m, v in slot.items() if len(v) >= MIN_N}
        if item:
            groups[f"h{h}|{size}|{pg}|{sector}"] = item
    last = observations(companies, sector_of, "last").get((1, "*", "*", "*"), {}).get("growth") or []
    years = sorted({y for _c, pts in companies for t in REVENUE_TAGS for y in yearly(pts.get(t, {}))})
    with_rev = {cik for cik, pts in companies if series(pts, "first")[0]}
    out = {
        "version": "tasas_base_sec v2 (primera cifra publicada)",
        "built": date.today().isoformat(),
        "source": (f"SEC XBRL companyfacts (www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip), primera "
                   f"cifra anual publicada de cada cierre, ejercicios {years[0]}–{years[-1]}; SIC de "
                   f"data.sec.gov/submissions; {len(with_rev)} empresas con ingresos"),
        "rule": (__doc__ or "").split("Regla", 1)[1].split("\n\n")[0].strip(),
        "grid": list(GRID),
        "buckets": {"size": [b[0] for b in SIZE], "prior_growth": [b[0] for b in PRIOR],
                    "sector": SECTOR_NAMES + ["otros"]},
        "groups": groups,
        "revisions": revisions(companies),
        "restated_check": {"h1_all_p50_primera": groups.get("h1|*|*|*", {}).get("growth", {}).get("p50"),
                           "h1_all_p50_ultima": round(pct(last, 0.5), 4) if last else None, "n_ultima": len(last)},
        "sector_by_cik": {str(c): SECTOR_NAMES.index(s) for c, s in sorted(sector_of.items()) if c in with_rev},
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
