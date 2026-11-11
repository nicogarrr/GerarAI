"""Issuer filing history must not stop at the first JSON:API page.

All HTTP responses are fixtures: no claim about any issuer's live coverage.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors import esef

LEI = "959800ABCDEFGH123456"
OTHER_LEI = "959800ZZZZZZZZ123456"


def _row(number, lei=LEI):
    return {"attributes": {
        "fxo_id": f"{lei}-{number}", "country": "GB",
        "period_end": f"{2025 - number}-12-31", "json_url": f"/{lei}/{number}.json",
    }}


def _page(rows, total):
    return {"data": rows, "meta": {"count": total}}


def _run(monkeypatch, responses, page_size=2):
    monkeypatch.setattr(esef, "_MIN_INTERVAL_S", 0)
    seen = []

    def handler(request):
        assert request.url.path == f"/api/entities/{LEI}/filings"
        assert request.url.params["page[size]"] == str(page_size)
        page = int(request.url.params.get("page[number]", "1"))
        seen.append(page)
        response = responses[page]
        if isinstance(response, int):
            return httpx.Response(response, json={}, request=request)
        return httpx.Response(200, json=response, request=request)

    async def probe():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=esef.ESEF_BASE_URL) as http:
            return await esef.EsefClient(http).list_filings_for_lei(LEI, page_size=page_size)

    return probe, seen


def test_history_includes_second_and_third_pages(monkeypatch):
    probe, seen = _run(monkeypatch, {
        1: _page([_row(0), _row(1)], 5),
        2: _page([_row(2), _row(3)], 5),
        3: _page([_row(4)], 5),
    })
    filings = asyncio.run(probe())
    assert seen == [1, 2, 3]
    assert [f.fxo_id for f in filings] == [f"{LEI}-{n}" for n in range(5)]


def test_exact_multiple_does_not_fetch_an_extra_page(monkeypatch):
    probe, seen = _run(monkeypatch, {1: _page([_row(0), _row(1)], 4), 2: _page([_row(2), _row(3)], 4)})
    assert len(asyncio.run(probe())) == 4
    assert seen == [1, 2]


@pytest.mark.parametrize("response", [404, _page([], 0), _page([_row(0)], 1)])
def test_single_page_and_absent_issuer_contract(monkeypatch, response):
    probe, seen = _run(monkeypatch, {1: response})
    expected = 1 if isinstance(response, dict) and response["data"] else 0
    assert len(asyncio.run(probe())) == expected
    assert seen == [1]


def test_first_page_server_error_is_not_an_absent_issuer(monkeypatch):
    probe, seen = _run(monkeypatch, {1: 500})
    with pytest.raises(esef.EsefError):
        asyncio.run(probe())
    assert seen == [1]


def test_every_page_is_filtered_by_requested_issuer(monkeypatch):
    probe, seen = _run(monkeypatch, {
        1: _page([_row(0, OTHER_LEI), _row(1)], 3),
        2: _page([_row(2, OTHER_LEI)], 3),
    })
    assert [f.fxo_id for f in asyncio.run(probe())] == [f"{LEI}-1"]
    assert seen == [1, 2]


@pytest.mark.parametrize("response", [404, 500, {"data": [], "meta": {}}])
def test_later_page_failure_is_not_silently_partial_history(monkeypatch, response):
    probe, seen = _run(monkeypatch, {1: _page([_row(0), _row(1)], 3), 2: response})
    with pytest.raises(esef.EsefError):
        asyncio.run(probe())
    assert seen == [1, 2]


@pytest.mark.parametrize("failed_page", [1, 2])
def test_rate_limit_propagates_without_returning_partial_history(monkeypatch, failed_page):
    calls = []

    async def fake_get(self, url, params=None, accept=None):
        page = params.get("page[number]", 1)
        calls.append(page)
        if page == failed_page:
            raise esef.EsefRateLimited(url, 3600)
        return _page([_row(0), _row(1)], 3)

    monkeypatch.setattr(esef.EsefClient, "_get_json", fake_get)

    async def probe():
        async with httpx.AsyncClient() as http:
            return await esef.EsefClient(http).list_filings_for_lei(LEI, page_size=2)

    with pytest.raises(esef.EsefRateLimited) as caught:
        asyncio.run(probe())
    assert caught.value.retry_after == 3600
    assert calls == list(range(1, failed_page + 1))


@pytest.mark.parametrize("page_size", [0, -1])
def test_non_positive_page_size_rejected_before_http(monkeypatch, page_size):
    async def no_http(*args, **kwargs):
        raise AssertionError("invalid page size must not issue HTTP requests")

    monkeypatch.setattr(esef.EsefClient, "_get_json", no_http)

    async def probe():
        async with httpx.AsyncClient() as http:
            return await esef.EsefClient(http).list_filings_for_lei(LEI, page_size=page_size)

    with pytest.raises(ValueError, match="page_size"):
        asyncio.run(probe())
