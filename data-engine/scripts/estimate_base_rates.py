"""Recalcula ``app/data/estimate_base_rates.json`` (tasas base de crecimiento y de margen).

Uso: ``python scripts/estimate_base_rates.py FRAMES_DIR SUB_DIR > app/data/estimate_base_rates.json``

- ``FRAMES_DIR``: los «frames» anuales de SEC XBRL (gratis, sin clave), un JSON por
  etiqueta y año natural: ``https://data.sec.gov/api/xbrl/frames/us-gaap/<TAG>/USD/CY<año>.json``
  guardado como ``<TAG>_<año>.json`` para Revenues,
  RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet y OperatingIncomeLoss.
- ``SUB_DIR``: ``<cik>.json`` con ``{"sic": "...", "name": "..."}`` de
  ``https://data.sec.gov/submissions/CIK<cik 10 dígitos>.json``.

Regla (fijada antes de mirar los resultados): una observación es (empresa, año de
partida ``y``) con ingresos ≥ 10 M$ en ``y`` y dato en ``y−3`` y ``y+h``. Se agrupa por
tamaño (ingresos en ``y``), crecimiento previo (TCAC ``y−3``→``y``) y sector (división
SIC); se guardan p10/p25/p50/p75/p90 y n del TCAC ``y``→``y+h`` (h = 1, 3, 5) y de la
variación del margen operativo en puntos (``margen(y+h) − margen(y)``). Ingresos por
año: la primera etiqueta presente en el orden de arriba. Sesgo conocido: los frames
llevan la última cifra presentada (reexpresiones incluidas), no la primera publicada.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import date

REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
OP_TAG = "OperatingIncomeLoss"
HORIZONS = (1, 3, 5)
MIN_REVENUE = 10e6
SIZE = (("<100M", 0, 1e8), ("100M-1B", 1e8, 1e9), ("1B-10B", 1e9, 1e10), (">10B", 1e10, float("inf")))
PRIOR = (("decrece", float("-inf"), 0.0), ("0-5 %", 0.0, 0.05), ("5-10 %", 0.05, 0.10), ("10-20 %", 0.10, 0.20),
         ("> 20 %", 0.20, float("inf")))
SECTORS = (("mineria_energia", 1000, 1500), ("construccion", 1500, 1800), ("manufactura", 2000, 4000),
           ("transporte_utilities_telecom", 4000, 5000), ("mayorista", 5000, 5200), ("minorista", 5200, 6000),
           ("finanzas", 6000, 6800), ("servicios", 7000, 9000))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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


def load(frames_dir, sub_dir):
    rev: dict[int, dict[int, float]] = {}
    op: dict[int, dict[int, float]] = {}
    for tag in REVENUE_TAGS[::-1]:  # la primera etiqueta del orden gana: se escribe la última
        for f in sorted(glob.glob(os.path.join(frames_dir, f"{tag}_*.json"))):
            year = int(f.rsplit("_", 1)[1][:4])
            for row in read(f).get("data", []):
                rev.setdefault(int(row["cik"]), {})[year] = float(row["val"])
    for f in sorted(glob.glob(os.path.join(frames_dir, f"{OP_TAG}_*.json"))):
        year = int(f.rsplit("_", 1)[1][:4])
        for row in read(f).get("data", []):
            op.setdefault(int(row["cik"]), {})[year] = float(row["val"])
    sic: dict[int, int] = {}
    for f in glob.glob(os.path.join(sub_dir, "*.json")):
        try:
            v = read(f).get("sic")
            if v:
                sic[int(os.path.basename(f)[:-5])] = int(v)
        except (ValueError, OSError):
            continue
    return rev, op, sic


def main(frames_dir, sub_dir):
    rev, op, sic = load(frames_dir, sub_dir)
    obs: dict[tuple, dict[str, list[float]]] = {}
    last_year = max(y for r in rev.values() for y in r)
    for cik, series in rev.items():
        sector = bucket(SECTORS, sic.get(cik, -1)) or "otros"
        for y, r0 in series.items():
            past = series.get(y - 3)
            if r0 < MIN_REVENUE or not past or past <= 0:
                continue
            prior = (r0 / past) ** (1 / 3) - 1
            size, pg = bucket(SIZE, r0), bucket(PRIOR, prior)
            for h in HORIZONS:
                rh = series.get(y + h)
                if rh is None or rh <= 0:
                    continue
                g = (rh / r0) ** (1 / h) - 1
                margin = None
                o0, oh = op.get(cik, {}).get(y), op.get(cik, {}).get(y + h)
                if o0 is not None and oh is not None:
                    margin = oh / rh - o0 / r0
                for key in ((size, pg, sector), (size, pg, "*"), ("*", pg, "*"), ("*", "*", "*")):
                    slot = obs.setdefault((h,) + key, {"growth": [], "margin": []})
                    slot["growth"].append(g)
                    if margin is not None and abs(margin) < 1.0:
                        slot["margin"].append(margin)
    groups = {}
    for (h, size, pg, sector), slot in sorted(obs.items()):
        item = {}
        for metric, values in slot.items():
            if len(values) >= 30:
                item[metric] = {q: round(pct(values, p), 4) for q, p in
                                (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9))}
                item[metric]["n"] = len(values)
        if item:
            groups[f"h{h}|{size}|{pg}|{sector}"] = item
    out = {
        "version": "tasas_base_sec v1",
        "built": date.today().isoformat(),
        "source": (f"SEC XBRL frames (data.sec.gov/api/xbrl/frames, años naturales CY2009–CY{last_year}) y SIC de "
                   f"data.sec.gov/submissions; {len(rev)} empresas con ingresos"),
        "rule": __doc__.split("Regla", 1)[1].split("\n\n")[0].strip(),
        "buckets": {"size": [b[0] for b in SIZE], "prior_growth": [b[0] for b in PRIOR],
                    "sector": [b[0] for b in SECTORS] + ["otros"]},
        "groups": groups,
        # sector de cada CIK con SIC conocido (índice en ``buckets.sector``), para agrupar sin red
        "sector_by_cik": {str(c): [b[0] for b in SECTORS].index(bucket(SECTORS, v))
                          for c, v in sorted(sic.items()) if c in rev and bucket(SECTORS, v)},
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=0, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
