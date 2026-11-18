"""Auditoria 2026-11-18 (v4): Retry-After HTTP-date en NOD y pacer unico de
TODO cnmv.es (OIR incluido).

(1) NOD ignoraba un Retry-After HTTP-date valido (429 con fecha a +3600 s daba
cero llamadas a cool_down). Ahora NOD, PS y OIR usan UN parser compartido.
(2) El conector OIR conservaba su throttle local independiente: ahora usa el
mismo cnmv_pacer que NOD y PS."""

import asyncio
import time
from datetime import date
from email.utils import formatdate
from pathlib import Path

import httpx
import pytest

from app.services.connectors import cnmv, cnmv_nod, cnmv_pacer, cnmv_ps

NOD_FIXTURE = (Path(__file__).parent / "fixtures" / "cnmv" / "nod_results_2026-11.html").read_text(
    encoding="utf-8"
)


async def _noop_wait():
    return None


@pytest.fixture
def cooldowns(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(cnmv_pacer.cnmv_pacer, "cool_down", lambda s: calls.append(s))
    monkeypatch.setattr(cnmv_pacer.cnmv_pacer, "wait_sync", lambda: None)
    monkeypatch.setattr(cnmv_pacer.cnmv_pacer, "wait", _noop_wait)
    return calls


def test_one_pacer_instance_for_all_cnmv_connectors():
    assert cnmv_nod._pacer is cnmv_pacer.cnmv_pacer
    assert cnmv_ps._pacer is cnmv_pacer.cnmv_pacer


def test_nod_retry_after_http_date_marks_cooldown(cooldowns):
    """Repro del auditor: 429 con Retry-After HTTP-date a +3600 s."""
    future = formatdate(time.time() + 3600, usegmt=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": future}, text="lento")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        cnmv_nod.fetch_entries(date(2026, 11, 17), date(2026, 11, 18), client=client)
    assert len(cooldowns) == 1
    assert 3500.0 < cooldowns[0] <= 3600.0  # integro, no recortado


def test_shared_parser_numeric_absent_past_date_and_garbage(cooldowns):
    cnmv_pacer.respect_retry_after(httpx.Response(429, headers={"Retry-After": "3600"}))
    assert cooldowns == [3600.0]
    cnmv_pacer.respect_retry_after(httpx.Response(200))
    assert cooldowns == [3600.0]  # sin cabecera: nada
    past = formatdate(time.time() - 600, usegmt=True)
    cnmv_pacer.respect_retry_after(httpx.Response(503, headers={"Retry-After": past}))
    assert cooldowns[-1] == 0.0  # fecha pasada: sin espera (nunca negativo)
    cnmv_pacer.respect_retry_after(httpx.Response(429, headers={"Retry-After": "pronto"}))
    assert cooldowns[-1] == 60.0  # ilegible: 60 s declarados


def test_ps_wrapper_uses_shared_parser(cooldowns):
    cnmv_ps._respect_retry_after(httpx.Response(429, headers={"Retry-After": "120"}))
    assert cooldowns == [120.0]


def test_oir_retry_after_marks_shared_cooldown(cooldowns):
    future = formatdate(time.time() + 900, usegmt=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": future}, text="lento")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await cnmv.fetch_oir_filings(days=1, client=client)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())
    assert len(cooldowns) == 1 and 800.0 < cooldowns[0] <= 900.0


def _oir(handler, monkeypatch):
    monkeypatch.setattr(cnmv_pacer.cnmv_pacer, "wait", _noop_wait)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cnmv.fetch_oir_filings(days=1, client=client)

    return asyncio.run(run())


def test_oir_transport_error_and_parse_error_propagate(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("sin red", request=request)

    with pytest.raises(httpx.ConnectError):
        _oir(boom, monkeypatch)
    with pytest.raises(cnmv.CNMVParseError):
        _oir(lambda r: httpx.Response(200, text="<html><body>otra cosa</body></html>"), monkeypatch)


def test_oir_own_client_is_created_and_closed(monkeypatch):
    monkeypatch.setattr(cnmv_pacer.cnmv_pacer, "wait", _noop_wait)
    closed = []
    real = httpx.AsyncClient

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>")))

    monkeypatch.setattr(cnmv.httpx, "AsyncClient", factory)
    original_aclose = real.aclose

    async def spy(self):
        closed.append(1)
        await original_aclose(self)

    monkeypatch.setattr(real, "aclose", spy)
    with pytest.raises(cnmv.CNMVParseError):
        asyncio.run(cnmv.fetch_oir_filings(days=1))
    assert closed == [1]


def test_oir_cooldown_does_not_block_event_loop():
    """Repro del auditor: cooldown compartido de 150 ms + latido asyncio a
    10 ms. Con wait_sync el latido se paraba ~150 ms; con await pacer.wait()
    el bucle sigue latiendo (hueco maximo < 80 ms)."""
    pacer = cnmv_pacer.cnmv_pacer
    pacer.reset()
    t0 = time.monotonic()
    pacer.cool_down(0.15)
    gaps: list[float] = []

    async def heartbeat(stop: asyncio.Event):
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    async def run():
        stop = asyncio.Event()
        beat = asyncio.create_task(heartbeat(stop))
        handler = lambda r: httpx.Response(200, text=NOD_FIXTURE_OIR)  # noqa: E731
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await cnmv.fetch_oir_filings(days=1, client=client)
            elapsed = time.monotonic() - t0
        stop.set()
        await beat
        return elapsed

    try:
        elapsed = asyncio.run(run())
    finally:
        pacer.reset()
    assert elapsed >= 0.14  # el cooldown SI se respeta
    assert len(gaps) >= 5 and max(gaps) < 0.08  # y el loop sigue latiendo (latido vivo)


OIR_HTML = (Path(__file__).parent / "fixtures" / "cnmv_oir_results.html").read_text(encoding="utf-8")
NOD_FIXTURE_OIR = OIR_HTML


def test_oir_days_out_of_range():
    for days in (0, 31):
        with pytest.raises(ValueError, match="days must be"):
            asyncio.run(cnmv.fetch_oir_filings(days=days))


def test_oir_parser_drift_branches():
    with pytest.raises(cnmv.CNMVParseError, match="incomplete result block"):
        cnmv.parse_oir_results(OIR_HTML.replace("verdocumento", "otro", 1))
    with pytest.raises(cnmv.CNMVParseError, match="unparseable date"):
        cnmv.parse_oir_results(OIR_HTML.replace("2026", "XXXX", 1) if False else _bad_date(OIR_HTML))
    with pytest.raises(cnmv.CNMVParseError, match="without nif"):
        cnmv.parse_oir_results(OIR_HTML.replace("datosentidad.aspx?nif=", "datosentidad.aspx?otro=", 1))
    relative = OIR_HTML.replace('href="https://www.cnmv.es/webservices/verdocumento', 'href="/webservices/verdocumento', 1)
    assert cnmv.parse_oir_results(relative)[0]["document_url"].startswith("https://www.cnmv.es/webservices/verdocumento")
    empty_container = '<html><body><ul id="listaElementosPrimernivel"></ul></body></html>'
    assert cnmv.parse_oir_results(empty_container) == []


def _bad_date(html: str) -> str:
    import re

    return re.sub(r"(fecha-con-hora[^>]*>)\s*\d{2}/\d{2}/\d{4}", r"\g<1>99/99/9999", html, count=1)
