"""get_with_retry: intentos, esperas y excepciones fijados (sleep falso).

Contrato que no puede moverse al pasar el bucle a tenacity: mismo número de
peticiones, mismas esperas (backoff, tope, Retry-After como suelo, jitter) y
misma excepción final. El ritmo con los proveedores no cambia.
"""

from __future__ import annotations

import asyncio
import random

import httpx
import pytest

from app.services.connectors import base
from app.services.connectors.base import UpstreamRateLimited, get_with_retry

_REQ = httpx.Request("GET", "https://example.test/x")


def _resp(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(status, headers=headers, request=_REQ)


def _run(steps, monkeypatch, **kwargs):
    """Ejecuta get_with_retry con respuestas/excepciones en orden; devuelve
    (resultado o excepción, nº de llamadas, esperas)."""
    sleeps: list[float] = []
    calls = {"n": 0}
    queue = list(steps)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def fetch():
        calls["n"] += 1
        step = queue.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    monkeypatch.setattr(base.asyncio, "sleep", fake_sleep)
    try:
        outcome = asyncio.run(get_with_retry(fetch, **kwargs))
    except Exception as exc:  # noqa: BLE001 - la excepción es parte del contrato
        outcome = exc
    return outcome, calls["n"], sleeps


def test_ok_first_try(monkeypatch):
    out, n, sleeps = _run([_resp(200)], monkeypatch)
    assert isinstance(out, httpx.Response) and out.status_code == 200
    assert (n, sleeps) == (1, [])


def test_5xx_then_ok_default_backoff(monkeypatch):
    out, n, sleeps = _run([_resp(503), _resp(500), _resp(200)], monkeypatch)
    assert out.status_code == 200
    assert (n, sleeps) == (3, [0.5, 1.0])


def test_5xx_exhausted_raises_http_status_error(monkeypatch):
    out, n, sleeps = _run([_resp(502)] * 4, monkeypatch, max_retries=3, base_seconds=1.0)
    assert isinstance(out, httpx.HTTPStatusError) and out.response.status_code == 502
    assert (n, sleeps) == (4, [1.0, 2.0, 4.0])


def test_backoff_is_capped(monkeypatch):
    out, n, sleeps = _run([_resp(500)] * 5 + [_resp(200)], monkeypatch,
                          max_retries=5, base_seconds=1.0, cap_seconds=3.0)
    assert out.status_code == 200
    assert (n, sleeps) == (6, [1.0, 2.0, 3.0, 3.0, 3.0])


def test_4xx_is_not_retried(monkeypatch):
    out, n, sleeps = _run([_resp(404)], monkeypatch)
    assert isinstance(out, httpx.HTTPStatusError) and out.response.status_code == 404
    assert (n, sleeps) == (1, [])


def test_429_retry_after_is_a_floor(monkeypatch):
    out, n, sleeps = _run([_resp(429, "5"), _resp(429, "0.1"), _resp(200)], monkeypatch, base_seconds=1.0)
    assert out.status_code == 200
    assert (n, sleeps) == (3, [5.0, 2.0])


def test_429_exhausted_raises_upstream_rate_limited(monkeypatch):
    out, n, sleeps = _run([_resp(429)] * 3, monkeypatch)
    assert isinstance(out, UpstreamRateLimited)
    assert str(out) == "upstream rate limited after 2 retries"
    assert out.retry_after is None
    assert (n, sleeps) == (3, [0.5, 1.0])


def test_429_last_attempt_keeps_retry_after(monkeypatch):
    out, n, sleeps = _run([_resp(429, "1"), _resp(429, "7")], monkeypatch, max_retries=1)
    assert isinstance(out, UpstreamRateLimited) and out.retry_after == 7.0
    assert (n, sleeps) == (2, [1.0])


def test_429_retry_after_above_cap_is_postponed_without_retry(monkeypatch):
    out, n, sleeps = _run([_resp(429, "3600")], monkeypatch)
    assert isinstance(out, UpstreamRateLimited) and out.retry_after == 3600.0
    assert "pospuesto sin reintento inline" in str(out)
    assert (n, sleeps) == (1, [])


def test_transport_errors_retry_without_jitter_then_reraise(monkeypatch):
    timeout = httpx.ReadTimeout("t", request=_REQ)
    conn = httpx.ConnectError("c", request=_REQ)
    out, n, sleeps = _run([timeout, conn, timeout], monkeypatch, jitter=True)
    assert out is timeout
    assert (n, sleeps) == (3, [0.5, 1.0])
    out, n, sleeps = _run([conn, _resp(200)], monkeypatch)
    assert out.status_code == 200 and (n, sleeps) == (2, [0.5])


def test_other_exceptions_are_not_retried(monkeypatch):
    boom = ValueError("x")
    out, n, sleeps = _run([boom], monkeypatch)
    assert out is boom and (n, sleeps) == (1, [])


def test_max_retries_zero(monkeypatch):
    out, n, sleeps = _run([_resp(500)], monkeypatch, max_retries=0)
    assert isinstance(out, httpx.HTTPStatusError) and (n, sleeps) == (1, [])
    out, n, sleeps = _run([_resp(429)], monkeypatch, max_retries=0)
    assert str(out) == "upstream rate limited after 0 retries" and (n, sleeps) == (1, [])
    timeout = httpx.ReadTimeout("t", request=_REQ)
    out, n, sleeps = _run([timeout], monkeypatch, max_retries=0)
    assert out is timeout and (n, sleeps) == (1, [])


@pytest.mark.parametrize("statuses", [[500, 503, 200], [429, 429, 200]])
def test_jitter_draws_same_uniform_sequence(monkeypatch, statuses):
    random.seed(1234)
    out, n, sleeps = _run([_resp(s) for s in statuses], monkeypatch, base_seconds=1.0, jitter=True)
    random.seed(1234)
    expected = [random.uniform(0.0, 1.0), random.uniform(0.0, 2.0)]
    assert out.status_code == 200
    assert (n, sleeps) == (3, expected)
