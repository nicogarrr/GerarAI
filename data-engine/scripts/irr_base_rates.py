"""Recalcula ``BASE_RATES`` de :mod:`app.valuation.shareholder_irr_rules` (tasas base de crecimiento).

Uso: ``python scripts/irr_base_rates.py DIR`` con un JSON por empresa en DIR con la forma
``{"sic": "3571", "m": {"revenue": {"2014-12-31": [valor, "fecha de presentación"], ...}}}`` (SEC
companyfacts, 10-K, primera cifra publicada por ejercicio). Imprime la tabla para pegarla en el módulo,
con la fecha en que cada tramo quedó conocido: la presentación más tardía de las cifras que usa
(``known_at``). La tabla entera se conoce en la más tardía de todas (``BASE_RATES_KNOWN_AT``), no al
día siguiente del último cierre: un 10-K se presenta semanas o meses después de cerrar el ejercicio.
"""
from __future__ import annotations

import glob
import json
import os
import sys

BUCKETS = (("decrece", -1.0, 0.0), ("0-5 %", 0.0, 0.05), ("5-10 %", 0.05, 0.10), ("10-20 %", 0.10, 0.20),
           ("> 20 %", 0.20, 10.0))
START_YEARS = range(2010, 2015)


def percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def observations(path: str) -> tuple[dict[str, list[float]], dict[str, str]]:
    """(TCAC a 5 años por tramo, fecha de presentación más tardía de lo usado por tramo)."""
    obs: dict[str, list[float]] = {b[0]: [] for b in BUCKETS}
    known: dict[str, str] = {}
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        with open(f) as fh:
            j = json.load(fh)
        if 6000 <= int(j.get("sic") or 0) < 6800:
            continue
        rev: dict[int, tuple[float, str]] = {}
        for end, v in sorted(j["m"].get("revenue", {}).items()):
            rev[int(end[:4])] = (v[0], str(v[1]) if len(v) > 1 and v[1] else "")
        for y in START_YEARS:
            years = (y - 3, y, y + 5)
            if all(k in rev and rev[k][0] > 0 for k in years):
                filed = [rev[k][1] for k in years]
                if not all(filed):
                    raise SystemExit(f"{f}: cifra sin fecha de presentación; sin ella no se sabe cuándo se conoció")
                past = (rev[y][0] / rev[y - 3][0]) ** (1 / 3) - 1
                fwd = (rev[y + 5][0] / rev[y][0]) ** (1 / 5) - 1
                for name, lo, hi in BUCKETS:
                    if lo <= past < hi:
                        obs[name].append(fwd)
                        known[name] = max(known.get(name, ""), *filed)
    return obs, known


def main(path: str) -> None:
    obs, known = observations(path)
    for name, values in obs.items():
        print(f'    "{name}": {{"p25": {percentile(values, .25):.4f}, "p50": {percentile(values, .5):.4f}, '
              f'"p75": {percentile(values, .75):.4f}, "n": {len(values)}, "known_at": "{known.get(name, "")}"}},')
    print(f"BASE_RATES_KNOWN_AT = {max(known.values()) if known else None!r}")


if __name__ == "__main__":
    main(sys.argv[1])
