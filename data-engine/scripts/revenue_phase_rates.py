"""Recalcula la tabla de ``app/valuation/revenue_phase_rates.py`` (regla fase-industria-v1) con fuentes gratis de la SEC.

    python scripts/revenue_phase_rates.py --cache /tmp/frames [--sics 2833 2834 2835 2836 8731 3826]

1. EDGAR browse-by-SIC (todos los registrantes del SIC, también inactivos) → CIK → SIC.
2. SEC frames us-gaap CY2009–CY2024 (USD) de los conceptos de ingresos y de ResearchAndDevelopmentExpense.
3. Panel: empresa activa en s con ingresos del último año en una fase (F1–F3); cociente ingresos(s+N)/ingresos(s)
   para N = 3, 4, 5 (activa sin ingresos etiquetados → 0; inactiva → fuera, se cuenta). Tabla con s = 2015–2019;
   prueba fuera de muestra con s = 2014 (y 2010–2013, usada para diseñar la regla). Imprime la tabla y la prueba.
Ritmo ≤ 4 peticiones/s; un 403/429 corta la pasada (sin reintentos).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.valuation import revenue_phase_rates as R  # noqa: E402

UA = "GerarAI research tab@tab.bot"
REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
           "RevenueFromContractWithCustomerIncludingAssessedTax")
RND = "ResearchAndDevelopmentExpense"


def _get(url: str, path: str) -> bytes:
    if os.path.exists(path):
        return Path(path).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - URL fija de la SEC
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise SystemExit(f"SEC respondió {exc.code}: se para la pasada ({url})") from exc
        body = b""
    time.sleep(0.25)
    Path(path).write_bytes(body)
    return body


def _json(body: bytes) -> dict:
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body) if body else {}


def quantile(v: list[float], q: float) -> float:
    v = sorted(v)
    pos = q * (len(v) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--sics", nargs="*", type=int, default=[2833, 2834, 2835, 2836, 8731, 3826])
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    cik_sic: dict[int, int] = {}
    for sic in a.sics:
        for page in range(40):
            url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=&dateb=&owner=include"
                   f"&start={page * 100}&count=100&output=atom")
            got = [int(c) for c in re.findall(r"<cik>(\d+)</cik>", _get(url, f"{a.cache}/sic{sic}_{page}.xml")
                                              .decode("utf8", "ignore"))]
            for c in got:
                cik_sic.setdefault(c, sic)
            if len(got) < 100:
                break
    frames: dict[tuple[str, int], dict[int, float]] = {}
    for concept in (*REVENUE, RND):
        for y in range(2009, 2025):
            data = _json(_get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{y}.json",
                              f"{a.cache}/{concept}_{y}.json"))
            frames[(concept, y)] = {row["cik"]: row["val"] for row in data.get("data") or []}

    def rev(cik: int, y: int) -> float | None:
        vals = [frames[(c, y)].get(cik) for c in REVENUE]
        vals = [v for v in vals if v is not None]
        return max(vals) / 1e6 if vals else None

    def active(cik: int, y: int) -> bool:
        return rev(cik, y) is not None or frames[(RND, y)].get(cik) is not None

    obs: dict[tuple[str, str, int, str], list[float]] = {}
    gone: dict[tuple[str, str, int, str], int] = {}
    for cik, sic in cik_sic.items():
        group = str(sic)[:3]
        for s in range(2010, 2020):
            if not active(cik, s):
                continue
            r0 = rev(cik, s)
            phase = R.phase_for(r0)
            if phase is None or not r0:
                continue
            split = "tabla" if s >= 2015 else ("prueba_2014" if s == 2014 else "diseño_2010_13")
            for n in (3, 4, 5):
                if s + n > 2024:
                    continue
                key = (group, phase, n, split)
                if not active(cik, s + n):
                    gone[key] = gone.get(key, 0) + 1
                    continue
                obs.setdefault(key, []).append((rev(cik, s + n) or 0.0) / r0)
    table = {}
    for (g, ph, n, split), v in sorted(obs.items()):
        if split == "tabla" and len(v) >= R.MIN_N:
            tot = len(v) + gone.get((g, ph, n, split), 0)
            table[(g, ph, n)] = {"p25": round(quantile(v, .25), 4), "p50": round(quantile(v, .5), 4),
                                 "p75": round(quantile(v, .75), 4), "n": len(v), "inactivas": round(1 - len(v) / tot, 3)}
    for k, v in table.items():
        print(k, v)
    for split in ("diseño_2010_13", "prueba_2014"):
        inside = below = above = 0
        for (g, ph, n, sp), v in obs.items():
            cell = table.get((g, ph, n))
            if sp != split or cell is None:
                continue
            for x in v:
                below += x < cell["p25"]
                above += x > cell["p75"]
                inside += cell["p25"] <= x <= cell["p75"]
        tot = inside + below + above
        if tot:
            print(split, {"n": tot, "en_rango": round(inside / tot, 3), "debajo": round(below / tot, 3),
                          "encima": round(above / tot, 3)})


if __name__ == "__main__":
    main()
