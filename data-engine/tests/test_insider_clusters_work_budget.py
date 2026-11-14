"""Paridad del agrupado de compras y guardia de trabajo, sin red ni LLM."""
import random
from datetime import date, timedelta
from typing import Any

from app.services import insider_summary as svc
from app.services.insider_summary import CLUSTER_MIN_INSIDERS, CLUSTER_WINDOW_DAYS


def _reference_clusters(buys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated = sorted((r for r in buys if r["tx_date"]), key=lambda r: r["tx_date"])
    clusters: list[dict[str, Any]] = []
    for i, start in enumerate(dated):
        start_day = date.fromisoformat(start["tx_date"])
        end_limit = start_day + timedelta(days=CLUSTER_WINDOW_DAYS - 1)
        members = [r for r in dated[i:] if date.fromisoformat(r["tx_date"]) <= end_limit]
        insiders = {r["_key"] for r in members}
        if len(insiders) < CLUSTER_MIN_INSIDERS:
            continue
        end_day = max(date.fromisoformat(r["tx_date"]) for r in members)
        if clusters and start_day <= date.fromisoformat(clusters[-1]["end"]):
            last = clusters[-1]
            merged = {id(r): r for r in last["_rows"] + members}
            last["_rows"] = list(merged.values())
            last["end"] = max(last["end"], end_day.isoformat())
            continue
        clusters.append({"start": start_day.isoformat(), "end": end_day.isoformat(), "_rows": members})
    out = []
    for c in clusters:
        rows = c.pop("_rows")
        names = sorted({str(r["insider"] or r["_key"]) for r in rows})
        out.append({
            **c,
            "insiders": len({r["_key"] for r in rows}),
            "names": names,
            "trades": len(rows),
            "value": None if any(r["value"] is None for r in rows) else sum(float(r["value"]) for r in rows),
            "value_missing": sum(1 for r in rows if r["value"] is None),
        })
    return out

def _rows(n, *, step=40):
    return [{"_key": str(i % 5), "insider": f"Persona {i % 5}",
             "tx_date": (date(2020, 1, 1) + timedelta(days=step*i)).isoformat(),
             "value": None if i % 7 == 0 else float(i)} for i in range(n)]


def test_date_parsing_not_quadratic_for_sparse_history(monkeypatch):
    rows = _rows(500)
    calls = []
    class CountedDate(date):
        @classmethod
        def fromisoformat(cls, value):
            calls.append(1)
            return date.fromisoformat(value)
    monkeypatch.setattr(svc, "date", CountedDate)
    assert svc._clusters(rows) == []
    assert len(calls) <= 2 * len(rows), len(calls)


def test_exact_cluster_parity_random_dense_sparse_and_boundary():
    rng = random.Random(4021)
    cases = [[], _rows(1), _rows(200), _rows(100, step=1), _rows(80, step=0)]
    for _ in range(30):
        rows = _rows(70)
        for row in rows:
            row["tx_date"] = (date(2020, 1, 1) + timedelta(days=rng.randrange(180))).isoformat()
        rng.shuffle(rows)
        cases.append(rows)
    boundary = _rows(4, step=1)
    boundary[2]["tx_date"] = "2020-01-30"  # último día incluido
    boundary[3]["tx_date"] = "2020-01-31"  # fuera de la primera ventana
    cases.append(boundary)
    cases.append([*boundary, boundary[0], {**boundary[0]}, {**boundary[1], "tx_date": None}])
    for rows in cases:
        assert svc._clusters(rows) == _reference_clusters(rows)
