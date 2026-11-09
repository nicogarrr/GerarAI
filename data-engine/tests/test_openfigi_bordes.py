"""Bordes del conector OpenFIGI no cubiertos por las suites existentes.

Sin red: httpx.MockTransport (y parche de httpx.AsyncClient/httpx.Client para las
rutas que crean cliente propio). Cubre: configured() de ambos clientes, validacion
de identificador en la via async, exchCode en el job, creacion de cliente propio,
payload y matches invalidos (async y sync), poda y espera del rate limiter,
__len__ de la cache, base_url override y _post sin cliente inyectado.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import openfigi as of

JOB_OK = [
    {
        "figi": "BBG000B9XRY4",
        "name": "APPLE INC",
        "ticker": "AAPL",
        "exchCode": "US",
        "compositeFIGI": "BBG000B9XRY4",
        "shareClassFIGI": None,
        "securityType": "Common Stock",
        "marketSector": "Equity",
        "securityDescription": None,
    }
]


def _async_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_client_y_connector_configured():
    assert of.OpenFIGIClient().configured() is True
    assert of.OpenFIGIConnector().configured() is True


def test_async_identificador_invalido_lanza():
    async def run():
        async with _async_client(lambda request: httpx.Response(200, json=[{"data": JOB_OK}])) as client:
            await of.OpenFIGIClient(client).map_identifier("   ")

    with pytest.raises(ValueError, match="Invalid identifier"):
        asyncio.run(run())
    with pytest.raises(ValueError, match="Invalid identifier"):
        asyncio.run(of.OpenFIGIClient(MagicMock()).map_identifier("X" * 41))


def test_async_exch_code_se_envia_en_el_job():
    seen = {}

    def handler(request):
        import json

        seen.update(json.loads(request.content)[0])
        return httpx.Response(200, json=[{"data": JOB_OK}])

    async def run():
        async with _async_client(handler) as client:
            return await of.OpenFIGIClient(client).map_identifier("us0378331005", exch_code="  mx ")

    result = asyncio.run(run())
    assert seen == {"idType": "ID_ISIN", "idValue": "US0378331005", "exchCode": "MX"}
    assert result["status"] == "matched"


def test_async_sin_cliente_crea_uno(monkeypatch):
    real_client = of.httpx.AsyncClient
    monkeypatch.setattr(
        of.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"data": JOB_OK}]))
        ),
    )
    result = asyncio.run(of.OpenFIGIClient().map_identifier("us0378331005"))
    assert result["status"] == "matched" and result["matches"][0]["ticker"] == "AAPL"


def test_async_payload_invalido_lanza():
    async def run():
        async with _async_client(lambda request: httpx.Response(200, json={"error": "x"})) as client:
            await of.OpenFIGIClient(client).map_identifier("US0378331005")

    with pytest.raises(RuntimeError, match="invalid mapping response"):
        asyncio.run(run())


def test_async_matches_invalidos_lanza():
    async def run():
        async with _async_client(lambda request: httpx.Response(200, json=[{"data": ["no-dict"]}])) as client:
            await of.OpenFIGIClient(client).map_identifier("US0378331005")

    with pytest.raises(RuntimeError, match="invalid mapping matches"):
        asyncio.run(run())


def test_rate_limiter_poda_hits_antiguos():
    limiter = of.OpenFIGIRateLimiter(requests_per_minute=1)
    limiter._hits.append(time.monotonic() - 61.0)
    limiter._hits.append(time.monotonic() - 30.0)
    espera = limiter.wait_seconds()
    assert len(limiter._hits) == 1
    assert 29.0 < espera <= 30.0


def test_rate_limiter_wait_if_needed_duerme(monkeypatch):
    dormido = []
    monkeypatch.setattr(time, "sleep", dormido.append)
    limiter = of.OpenFIGIRateLimiter(requests_per_minute=1)
    limiter.record()
    limiter.wait_if_needed()
    assert len(dormido) == 1 and 0 < dormido[0] <= 60.0
    of.OpenFIGIRateLimiter(requests_per_minute=60).wait_if_needed()
    assert len(dormido) == 1


def test_cache_len():
    cache = of.OpenFIGICache()
    cache.set("ID_ISIN", "A", {"status": "ok"})
    cache.set("ID_ISIN", "B", {"status": "ok"}, exch_code="MX")
    assert len(cache) == 2


def test_sync_base_url_override():
    connector = of.OpenFIGIConnector(base_url="http://openfigi.example/v3/mapping")
    assert connector.base_url == "http://openfigi.example/v3/mapping"


def test_sync_post_sin_cliente_crea_uno(monkeypatch):
    real_client = of.httpx.Client
    monkeypatch.setattr(
        of.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"data": JOB_OK}]))
        ),
    )
    connector = of.OpenFIGIConnector()
    result = connector.map_identifier("us0378331005")
    assert result["status"] == "matched" and result["matches"][0]["ticker"] == "AAPL"


def test_sync_exch_code_se_envia_en_el_job():
    seen = {}

    def handler(request):
        import json

        seen.update(json.loads(request.content)[0])
        return httpx.Response(200, json=[{"data": JOB_OK}])

    connector = of.OpenFIGIConnector(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = connector.map_identifier("us0378331005", exch_code="mx")
    assert seen == {"idType": "ID_ISIN", "idValue": "US0378331005", "exchCode": "MX"}
    assert result["status"] == "matched"


def test_sync_payload_invalido_lanza():
    connector = of.OpenFIGIConnector(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"error": "x"}))
        )
    )
    with pytest.raises(RuntimeError, match="invalid mapping response"):
        connector.map_identifier("US0378331005")


def test_sync_matches_invalidos_lanza():
    connector = of.OpenFIGIConnector(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"data": [42]}]))
        )
    )
    with pytest.raises(RuntimeError, match="invalid mapping matches"):
        connector.map_identifier("US0378331005")
