"""SupGP transport failures never count as validated success."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from app.services.connectors import celestrak_ast_supgp as service
from tests.test_asts_supgp import NOW, gp_row


@pytest.mark.parametrize("payload", [None, {}, [], "invalid"])
def test_normalizer_rejects_non_list_or_empty_payload(payload):
    with pytest.raises(ValueError, match="Invalid AST SupGP payload"):
        service.normalize_supgp(payload, fetched_at=NOW)


@pytest.mark.parametrize(
    "mode,reason", [("large", "oversized"), ("json", "no JSON"), ("network", "transport")]
)
def test_transport_payload_failures_report_exactly_once(monkeypatch, mode, reason):
    events = []
    monkeypatch.setattr(service, "_record_parse_failure", lambda reason: events.append(reason))
    monkeypatch.setattr(service, "_record_transport_failure", lambda exc: events.append("transport"))
    monkeypatch.setattr(
        service, "_record_success", lambda: pytest.fail("invalid response must not record success")
    )

    async def scenario():
        def handler(request):
            if mode == "network":
                raise httpx.ReadTimeout("upstream unavailable", request=request)
            return httpx.Response(200, content=b"x" * 2_000_001 if mode == "large" else b"not json")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.ReadTimeout if mode == "network" else ValueError):
                await service.fetch_supgp(client=client, fetched_at=NOW)

    asyncio.run(scenario())
    assert events == [reason]


def test_owned_client_uses_fixed_endpoint_headers_and_validates_before_success(monkeypatch):
    client_class = httpx.AsyncClient
    events = []

    @asynccontextmanager
    async def owned(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False}

        def handler(request):
            assert str(request.url) == service.SUPGP_URL
            assert request.headers["user-agent"] == "GerarAI/1.0 (AST catalog research)"
            events.append("request")
            return httpx.Response(200, json=[gp_row(CLASSIFICATION_TYPE="C", DATA_SOURCE="AST-E")])

        async with client_class(transport=httpx.MockTransport(handler)) as client:
            yield client

    monkeypatch.setattr(service.httpx, "AsyncClient", owned)
    monkeypatch.setattr(service, "_record_success", lambda: events.append("success"))
    result = asyncio.run(service.fetch_supgp(fetched_at=NOW))
    assert result[0]["norad_cat_id"] == 100242
    assert events == ["request", "success"]
