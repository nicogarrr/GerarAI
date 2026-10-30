"""SEC: descargas concurrentes de la misma URL comparten una sola peticion.

Con la cache fria, los ``cik_for_ticker`` en paralelo de los catalizadores
descargaban el mapa de tickers de la SEC (~1 MB) una vez por ticker (4 veces
en una carga real), cada una ocupando un hueco del reloj compartido de la SEC.
"""

import asyncio

import httpx
import pytest

from app.services.connectors import sec as sec_mod
from app.services.connectors.sec import SECClient, reset_sec_client_state

URL = "https://www.sec.gov/files/company_tickers.json"
PAYLOAD = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(sec_mod.sec_edgar, "read_snapshot_for", lambda url: None)
    reset_sec_client_state()
    yield
    reset_sec_client_state()


class _Resp:
    def json(self):
        return {"0": dict(PAYLOAD["0"])}


def _client(calls, *, fail_first=False):
    client = SECClient(use_cache=True)

    async def fake_get(url):
        calls.append(url)
        await asyncio.sleep(0.05)
        if fail_first and len(calls) == 1:
            raise httpx.ConnectError("sec caida")
        return _Resp()

    client._get = fake_get  # noqa: SLF001
    return client


def test_concurrent_requests_share_one_download():
    calls: list[str] = []
    client = _client(calls)

    async def run():
        return await asyncio.gather(*(client._get_json(URL) for _ in range(4)))  # noqa: SLF001

    results = asyncio.run(run())
    assert calls == [URL]
    assert all(r == PAYLOAD for r in results)
    assert len({id(r) for r in results}) == 4  # cada llamador con su copia


def test_failure_reaches_every_waiter_and_is_not_cached():
    calls: list[str] = []
    client = _client(calls, fail_first=True)

    async def run():
        return await asyncio.gather(
            *(client._get_json(URL) for _ in range(3)),
            return_exceptions=True,  # noqa: SLF001
        )

    results = asyncio.run(run())
    assert all(isinstance(r, httpx.ConnectError) for r in results)
    assert asyncio.run(client._get_json(URL)) == PAYLOAD  # noqa: SLF001
    assert calls == [URL, URL]


def test_cancelled_first_caller_does_not_cancel_the_others():
    calls: list[str] = []
    client = _client(calls)

    async def run():
        first = asyncio.ensure_future(client._get_json(URL))  # noqa: SLF001
        await asyncio.sleep(0)
        second = asyncio.ensure_future(client._get_json(URL))  # noqa: SLF001
        await asyncio.sleep(0)
        first.cancel()
        return await second

    assert asyncio.run(run()) == PAYLOAD
    assert calls == [URL]
