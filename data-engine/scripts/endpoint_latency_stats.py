"""Métricas reproducibles de muestras, sin interpolar errores como latencias útiles."""
from __future__ import annotations

import math
from collections import Counter


def percentile(samples: list[float], quantile: float) -> float | None:
    """Rango más próximo: p95 de N muestras = elemento ceil(0,95*N)."""
    if not 0 < quantile <= 1:
        raise ValueError("El percentil debe estar entre 0 y 1")
    if any(not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("Las muestras deben ser finitas y no negativas")
    if not samples:
        return None
    return sorted(samples)[math.ceil(quantile * len(samples)) - 1]


def summarize(samples: list[dict]) -> dict:
    """Sólo respuestas 2xx entran en p50/p95; los fallos se cuentan aparte."""
    ok = [sample for sample in samples if 200 <= sample["status"] < 300]
    return {
        "n": len(samples),
        "n_ok": len(ok),
        "status_counts": dict(Counter(str(sample["status"]) for sample in samples)),
        "p50_ms": percentile([sample["elapsed_ms"] for sample in ok], 0.50),
        "p95_ms": percentile([sample["elapsed_ms"] for sample in ok], 0.95),
        "max_queries": max((sample["queries"] for sample in ok), default=None),
        "max_bytes": max((sample["bytes"] for sample in ok), default=None),
        "p95_sql_ms": percentile([sample["sql_ms"] for sample in ok], 0.95),
    }
