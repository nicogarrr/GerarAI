"""Estadística del banco: percentiles explícitos, fallos fuera de la distribución."""
import pytest

from scripts.endpoint_latency_stats import percentile, summarize


def test_nearest_rank_and_empty():
    assert percentile(list(range(1, 21)), 0.95) == 19
    assert percentile([9, 1, 5, 3], 0.5) == 3
    assert percentile([], 0.5) is None
    assert percentile([7], 0.95) == 7


@pytest.mark.parametrize("values,q", [([float("nan")], .5), ([float("inf")], .5), ([-1], .5), ([1], 0), ([1], 1.01)])
def test_invalid_samples(values, q):
    with pytest.raises(ValueError):
        percentile(values, q)


def test_errors_not_reported_as_success_latency():
    rows = [
        dict(status=200, elapsed_ms=20, queries=3, bytes=40, sql_ms=2),
        dict(status=503, elapsed_ms=1, queries=0, bytes=10, sql_ms=0),
    ]
    result = summarize(rows)
    assert result == dict(n=2, n_ok=1, status_counts={"200": 1, "503": 1},
                          p50_ms=20, p95_ms=20, max_queries=3, max_bytes=40, p95_sql_ms=2)
    assert summarize(rows[1:])["p95_ms"] is None
    assert summarize([])["max_queries"] is None
