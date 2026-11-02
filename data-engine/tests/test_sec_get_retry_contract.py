"""SECClient._get: intentos, esperas y orden de pasos fijados (sleep falso).

Contrato del bucle de reintento al pasarlo a tenacity: un hueco del reloj
compartido (``_throttle``) antes de CADA petición, ``rate_limited`` tras cada
respuesta, mismas esperas (Retry-After con tope o backoff que se dobla) y misma
excepción final. El ritmo con la SEC no cambia.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors import sec as sec_module
from app.services.connectors import sec_pacing
from app.services.connectors.sec import SECClient, reset_sec_client_state

URL = "https://data.sec.gov/x.json"


@pytest.fixture(autouse=True)
def _clean():
    reset_sec_client_state()
    yield
    reset_sec_client_state()


def _run(steps, monkeypatch, *, max_retries: int = 3):
    events: list = []
    queue = list(steps)

    async def fake_sleep(seconds):
        events.append(("sleep", seconds))

    async def fake_throttle(self):
        events.append("throttle")

    def fake_rate_limited(response):
        events.append(("seen", response.status_code))

    monkeypatch.setattr(sec_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(SECClient, "_throttle", fake_throttle)
    monkeypatch.setattr(sec_pacing, "rate_limited", fake_rate_limited)

    async def handler(request: httpx.Request) -> httpx.Response:
        step = queue.pop(0)
        if isinstance(step, type) and issubclass(step, httpx.TransportError):
            raise step("boom", request=request)
        status, headers = step if isinstance(step, tuple) else (step, {})
        return httpx.Response(status, headers=headers, request=request)

    async def probe():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            try:
                return await SECClient(client=http, max_retries=max_retries)._get(URL)
            except Exception as exc:  # noqa: BLE001 - la excepción es parte del contrato
                return exc

    return asyncio.run(probe()), events


def test_retry_after_then_doubling_backoff(monkeypatch):
    out, events = _run([(429, {"retry-after": "2"}), 503, 200], monkeypatch)
    assert out.status_code == 200
    assert events == [
        "throttle", ("seen", 429), ("sleep", 2.0),
        "throttle", ("seen", 503), ("sleep", 2.0),
        "throttle", ("seen", 200),
    ]


def test_backoff_doubles_and_retry_after_is_capped(monkeypatch):
    out, events = _run([500, 502, (429, {"retry-after": "500"}), 200], monkeypatch)
    assert out.status_code == 200
    assert [e for e in events if e[0] == "sleep"] == [("sleep", 1.0), ("sleep", 2.0), ("sleep", 60.0)]
    assert events.count("throttle") == 4


def test_retry_after_zero_uses_backoff(monkeypatch):
    out, events = _run([500, (429, {"retry-after": "0"}), 200], monkeypatch)
    assert out.status_code == 200
    assert [e for e in events if e[0] == "sleep"] == [("sleep", 1.0), ("sleep", 2.0)]


def test_backoff_cap(monkeypatch):
    out, events = _run([503] * 8, monkeypatch, max_retries=7)
    assert isinstance(out, httpx.HTTPStatusError) and out.response.status_code == 503
    assert [e[1] for e in events if e[0] == "sleep"] == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0]
    assert events.count("throttle") == 8


def test_5xx_exhausted_raises_http_status_error(monkeypatch):
    out, events = _run([503, 503, 503], monkeypatch, max_retries=2)
    assert isinstance(out, httpx.HTTPStatusError) and out.response.status_code == 503
    assert events == [
        "throttle", ("seen", 503), ("sleep", 1.0),
        "throttle", ("seen", 503), ("sleep", 2.0),
        "throttle", ("seen", 503),
    ]


def test_429_exhausted_raises_http_status_error(monkeypatch):
    out, events = _run([429, 429], monkeypatch, max_retries=1)
    assert isinstance(out, httpx.HTTPStatusError) and out.response.status_code == 429
    assert [e for e in events if e[0] == "sleep"] == [("sleep", 1.0)]


@pytest.mark.parametrize("status", [403, 404, 401, 400])
def test_non_retryable_status_is_not_retried(monkeypatch, status):
    out, events = _run([status], monkeypatch)
    assert isinstance(out, httpx.HTTPStatusError) and out.response.status_code == status
    assert events == ["throttle", ("seen", status)]


def test_transport_errors_retry_then_reraise(monkeypatch):
    out, events = _run([httpx.ConnectTimeout, httpx.ReadError, 200], monkeypatch)
    assert out.status_code == 200
    assert events == ["throttle", ("sleep", 1.0), "throttle", ("sleep", 2.0), "throttle", ("seen", 200)]
    out, events = _run([httpx.ConnectTimeout] * 3, monkeypatch, max_retries=2)
    assert isinstance(out, httpx.ConnectTimeout)
    assert events == ["throttle", ("sleep", 1.0), "throttle", ("sleep", 2.0), "throttle"]


def test_max_retries_zero(monkeypatch):
    out, events = _run([503], monkeypatch, max_retries=0)
    assert isinstance(out, httpx.HTTPStatusError) and events == ["throttle", ("seen", 503)]
    out, events = _run([httpx.ConnectError], monkeypatch, max_retries=0)
    assert isinstance(out, httpx.ConnectError) and events == ["throttle"]
