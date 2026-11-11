"""HTTP status, not digits in a LEI/error message, determines issuer absence."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors import esef


@pytest.mark.parametrize("lei", ["959800ABCDEFGH123456", "959800404DEFGH123456"])
@pytest.mark.parametrize("status", [400, 404, 500, 502])
def test_only_actual_404_means_no_issuer(monkeypatch, lei, status):
    monkeypatch.setattr(esef, "_MIN_INTERVAL_S", 0)

    async def probe():
        transport = httpx.MockTransport(lambda r: httpx.Response(status, json={}, request=r))
        async with httpx.AsyncClient(base_url=esef.ESEF_BASE_URL, transport=transport) as http:
            return await esef.EsefClient(http).list_filings_for_lei(lei)

    if status == 404:
        assert asyncio.run(probe()) == []
    else:
        with pytest.raises(esef.EsefError) as caught:
            asyncio.run(probe())
        assert caught.value.status_code == status


@pytest.mark.parametrize("failure", ["transport", "json"])
def test_404_in_non_http_failure_is_not_absent_issuer(monkeypatch, failure):
    monkeypatch.setattr(esef, "_MIN_INTERVAL_S", 0)

    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("proxy error 404", request=request)
        return httpx.Response(200, content="not JSON", request=request)

    async def probe():
        async with httpx.AsyncClient(base_url=esef.ESEF_BASE_URL, transport=httpx.MockTransport(handler)) as http:
            return await esef.EsefClient(http).list_filings_for_lei("959800404DEFGH123456")

    with pytest.raises(esef.EsefError):
        asyncio.run(probe())
