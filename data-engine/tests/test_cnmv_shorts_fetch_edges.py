"""CNMV current positions reject structural drift and report HTTP failures."""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.services.cnmv_mapping import CNMVIssuer
from app.services.connectors import cnmv_shorts as connector

ISSUER = CNMVIssuer("TEST", "Test Issuer", "A-00000001", "ES0000000001")


def _page(row):
    return f"<html><body>{ISSUER.isin}<table><caption>Notificaciones vivas iguales o superiores</caption><tbody>{row}</tbody></table></body></html>"


@pytest.mark.parametrize(
    "row,error",
    [
        ("<tr><td>Fund</td></tr>", "table drift"),
        ("<tr><td></td><td>1,0</td><td>01/01/2026</td><td></td></tr>", "table drift"),
        ("<tr><td>Fund</td><td>1,0</td><td>02/01/2026</td><td></td></tr>", "Future position date"),
    ],
)
def test_bad_rows_and_future_dates_are_not_interpreted_as_zero(row, error):
    with pytest.raises(ValueError, match=error):
        connector.parse_positions(_page(row), ISSUER, now=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize("mode", ["http", "network"])
def test_http_and_transport_errors_are_recorded_and_reraised(monkeypatch, mode):
    events = []

    class Registry:
        def record_failure(self, source, reason):
            events.append((source, reason))

        def record_success(self, source):
            pytest.fail("failure must not record success")

    monkeypatch.setattr(connector, "get_data_source_registry", lambda: Registry())

    async def scenario():
        def handler(request):
            if mode == "network":
                raise httpx.ConnectError("private error", request=request)
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            expected = httpx.ConnectError if mode == "network" else httpx.HTTPStatusError
            with pytest.raises(expected):
                await connector.fetch_positions(ISSUER, client=client)

    asyncio.run(scenario())
    assert events == [("cnmv", "HTTP 503" if mode == "http" else "error de red: ConnectError")]


def test_owned_client_configuration_and_empty_current_table(monkeypatch):
    from contextlib import asynccontextmanager

    calls = []
    client_class = httpx.AsyncClient

    @asynccontextmanager
    async def owned(**kwargs):
        assert kwargs == {"timeout": 12, "follow_redirects": False}

        def handler(request):
            calls.append(request)
            return httpx.Response(200, text=_page(""))

        async with client_class(transport=httpx.MockTransport(handler)) as client:
            yield client

    class Registry:
        def record_success(self, source):
            calls.append(source)

    monkeypatch.setattr(connector.httpx, "AsyncClient", owned)
    monkeypatch.setattr(connector, "get_data_source_registry", lambda: Registry())
    result = asyncio.run(connector.fetch_positions(ISSUER))
    assert result["positions"] == [] and result["public_total_percent"] == 0
    assert result["kind"] == "OFICIAL" and result["total_kind"] == "DERIVADO"
    assert calls[0].url.params["nif"] == "A00000001" and calls[1] == "cnmv"
