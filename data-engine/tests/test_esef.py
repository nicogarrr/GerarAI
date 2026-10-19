"""ESEF connector — real-fixture contract tests (filings.xbrl.org)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.services.connectors.esef import (
    EsefClient,
    EsefError,
    normalize_xbrl_json,
    parse_entity,
    parse_filings_page,
    parse_period,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_real_filings_page():
    filings, total = parse_filings_page(_fixture("esef_filings_page.json"))
    assert total == 542  # meta.count captured 2026-09-24
    assert len(filings) == 5
    f = filings[0]
    assert f.country == "ES"
    assert len(f.lei) == 20
    assert f.fxo_id.startswith(f.lei)
    assert all(x.package_url or x.json_url for x in filings)


def test_parse_filings_page_drift_raises_honestly():
    with pytest.raises(EsefError):
        parse_filings_page({"unexpected": True})
    with pytest.raises(EsefError):
        parse_filings_page({"data": {"not": "a list"}, "meta": {"count": 1}})


def test_parse_real_entity():
    lei, name = parse_entity(_fixture("esef_entity_fcc.json"))
    assert lei == "95980020140005178328"
    assert name == "FOMENTO DE CONSTRUCCIONES Y CONTRATAS S.A."


def test_parse_entity_drift_raises_honestly():
    with pytest.raises(EsefError):
        parse_entity({"data": {"attributes": {"identifier": "X"}}})


def test_parse_period_shapes():
    # Los instantes xBRL-JSON son EXCLUSIVOS a medianoche: «2023-01-01T00:00:00»
    # es el cierre inclusivo de 2022-12-31 (ver _inclusive_date).
    assert parse_period("2023-01-01T00:00:00") == {"instant": "2022-12-31"}
    assert parse_period("2022-01-01T00:00:00/2023-01-01T00:00:00") == {
        "start": "2022-01-01",
        "end": "2022-12-31",
    }
    # date-only ya es fecha inclusiva: se respeta tal cual
    assert parse_period("2022-12-31") == {"instant": "2022-12-31"}


def test_normalize_real_xbrl_json_fixture():
    doc = _fixture("esef_xbrl_json_fcc_trimmed.json")
    facts = normalize_xbrl_json(doc)
    revenue = facts["ifrs-full:Revenue"]["iso4217:EUR"]
    assert revenue[0]["start"] == "2022-01-01"
    assert revenue[0]["end"] == "2022-12-31"  # instante exclusivo -> fecha inclusiva
    assert revenue[0]["val"] == "7705687000"  # string preserved, never rounded
    assert revenue[0]["lei"] == "95980020140005178328"
    cash = facts["ifrs-full:CashAndCashEquivalents"]["iso4217:EUR"]
    assert cash[0]["instant"] == "2022-12-31"
    assert "ifrs-full:ProfitLoss" in facts


def test_normalize_drift_raises_honestly():
    with pytest.raises(EsefError):
        normalize_xbrl_json({"no_facts": {}})
    with pytest.raises(EsefError):
        normalize_xbrl_json([1, 2, 3])


def test_normalize_skips_dimensional_facts_without_guessing():
    doc = {
        "facts": {
            "fact-1": {
                "value": "1",
                "decimals": 0,
                "dimensions": {"concept": "ifrs-full:Revenue", "period": "2023-01-01T00:00:00"},
                # no unit -> defaults to pure
            },
            "fact-2": {"value": "2", "dimensions": {}},  # broken: skipped
        }
    }
    facts = normalize_xbrl_json(doc)
    assert facts["ifrs-full:Revenue"]["pure"][0]["val"] == "1"
    assert len(facts) == 1


def test_client_list_filings_page_with_mock_transport():
    asyncio.run(_test_client_list_filings_page_with_mock_transport_impl())


async def _test_client_list_filings_page_with_mock_transport_impl():
    payload = _fixture("esef_filings_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter[country]"] == "ES"
        return httpx.Response(200, json=payload)

    client = EsefClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://filings.xbrl.org"))
    filings, total = await client.list_filings_page("ES", page=1, page_size=5)
    assert total == 542
    assert len(filings) == 5


def test_client_entity_name_with_mock_transport():
    asyncio.run(_test_client_entity_name_with_mock_transport_impl())


async def _test_client_entity_name_with_mock_transport_impl():
    payload = _fixture("esef_entity_fcc.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = EsefClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://filings.xbrl.org"))
    assert await client.get_entity_name("95980020140005178328") == "FOMENTO DE CONSTRUCCIONES Y CONTRATAS S.A."


def test_client_http_error_raises_honestly():
    asyncio.run(_test_client_http_error_raises_honestly_impl())


async def _test_client_http_error_raises_honestly_impl():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    client = EsefClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://filings.xbrl.org"))
    with pytest.raises(EsefError):
        await client.list_filings_page("ES")


def test_fetch_filing_json_unavailable_raises_honestly():
    asyncio.run(_test_fetch_filing_json_unavailable_raises_honestly_impl())


async def _test_fetch_filing_json_unavailable_raises_honestly_impl():
    filings, _ = parse_filings_page(_fixture("esef_filings_page.json"))
    no_json = next(f for f in filings if f.json_url is None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be called without json_url")

    client = EsefClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://filings.xbrl.org"))
    with pytest.raises(EsefError, match="no xBRL-JSON render"):
        await client.fetch_filing_json(no_json)
