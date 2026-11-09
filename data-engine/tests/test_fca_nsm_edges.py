"""FCA NSM failure and package boundaries using local streams and archives."""

import asyncio
import hashlib
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.services.connectors import fca_nsm as nsm

LEI = "12345678901234567890"


def filing():
    return nsm.NsmFiling(
        "fixture",
        LEI,
        "Fixture issuer",
        nsm.ANNUAL_REPORT_TYPE,
        "Tagged",
        "2026-11-09",
        "fixture.zip",
        "2026-09-30",
    )


@pytest.mark.parametrize("previous,expected_wait", [(99.0, 1.0), (90.0, None)])
def test_throttle_waits_only_for_remaining_interval(monkeypatch, previous, expected_wait):
    clock = Mock(side_effect=[100.0, 102.0])
    sleep = AsyncMock()
    monkeypatch.setattr(nsm, "_last_request_at", previous)
    monkeypatch.setattr(nsm, "_MIN_INTERVAL_S", 2.0)
    monkeypatch.setattr(nsm, "time", SimpleNamespace(monotonic=clock))
    monkeypatch.setattr(nsm, "asyncio", SimpleNamespace(sleep=sleep))
    asyncio.run(nsm._throttle())
    if expected_wait is None:
        sleep.assert_not_awaited()
    else:
        sleep.assert_awaited_once_with(expected_wait)
    assert nsm._last_request_at == 102.0


def test_parser_skips_malformed_hits_and_accepts_publication_fallback():
    good = {
        "lei": LEI,
        "download_link": "fixture.zip",
        "publication_date": "2026-11-09T10:00:00",
        "tag_esef": "Tagged",
    }
    hits = [
        None,
        {"_source": []},
        {"_source": {}},
        {"_source": {**good, "lei": ""}},
        {"_source": {**good, "download_link": ""}},
        {"_source": {**good, "publication_date": ""}},
        {"_id": "fixture", "_source": good},
    ]
    rows = nsm.parse_search_hits({"hits": {"hits": hits}}, lei=LEI)
    assert len(rows) == 1
    assert rows[0].submitted_date == "2026-11-09"
    assert rows[0].disclosure_id == "fixture" and rows[0].tagged
    assert rows[0].period_end is None
    assert nsm.search_body(LEI, filing_type=None, size=7)["criteriaObj"]["criteria"] == [
        {"name": "company_lei", "value": ["", LEI, "disclose_org", "related_org"]}
    ]
    assert nsm.search_body(LEI, filing_type=None, size=7)["size"] == 7


@pytest.mark.parametrize("blob", [b"<html>fixture</html>", b"<?xml version='1.0'?><root/>"])
def test_standalone_markup_is_returned_without_archive_path(blob):
    assert nsm.report_from_package(blob) == (blob, "")


@pytest.mark.parametrize("blob,reason", [(b"plain text", "no es un paquete"), (b"PKnot a zip", "ilegible")])
def test_non_report_or_corrupt_archive_fails_explicitly(blob, reason):
    with pytest.raises(nsm.NsmError, match=reason):
        nsm.report_from_package(blob)


def test_archive_without_report_is_not_an_empty_success():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("META-INF/reportPackage.json", "{}")
    with pytest.raises(nsm.NsmError, match="sin informe"):
        nsm.report_from_package(buf.getvalue())


@pytest.mark.parametrize("failure", ["http", "json", "transport"])
def test_search_errors_are_wrapped_with_original_cause(monkeypatch, failure):
    throttle = AsyncMock()
    monkeypatch.setattr(nsm, "_throttle", throttle)

    def handler(request):
        assert request.method == "POST"
        assert request.url.params["index"] == "nsm-search"
        if failure == "transport":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(503 if failure == "http" else 200, text="not JSON")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await nsm.NsmClient(client).list_filings_for_lei(LEI)

    with pytest.raises(nsm.NsmError, match="busqueda NSM fallida") as exc:
        asyncio.run(go())
    assert isinstance(
        exc.value.__cause__,
        {"http": httpx.HTTPStatusError, "json": ValueError, "transport": httpx.ConnectError}[failure],
    )
    throttle.assert_awaited_once_with()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            yield part

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("parts,oversize", [([b"ab", b"cd"], False), ([b"ab", b"cd", b"e"], True)])
def test_download_stream_exact_cap_and_overflow_close_response(monkeypatch, parts, oversize):
    monkeypatch.setattr(nsm, "MAX_PACKAGE_BYTES", 4)
    throttle = AsyncMock()
    monkeypatch.setattr(nsm, "_throttle", throttle)
    stream = Chunks(parts)

    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == filing().url
        assert request.headers["user-agent"] == nsm.USER_AGENT
        return httpx.Response(200, stream=stream)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await nsm.NsmClient(client).fetch_document(filing())

    if oversize:
        with pytest.raises(nsm.NsmError, match="documento mayor"):
            asyncio.run(go())
    else:
        assert asyncio.run(go()) == (b"abcd", hashlib.sha256(b"abcd").hexdigest())
    assert stream.closed
    throttle.assert_awaited_once_with()


def test_download_http_failure_wraps_original_and_closes_response(monkeypatch):
    monkeypatch.setattr(nsm, "_throttle", AsyncMock())
    stream = Chunks([b"unavailable"])

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(404, stream=stream))
        ) as client:
            await nsm.NsmClient(client).fetch_document(filing())

    with pytest.raises(nsm.NsmError, match="descarga NSM fallida") as exc:
        asyncio.run(go())
    assert isinstance(exc.value.__cause__, httpx.HTTPStatusError)
    assert stream.closed


def test_client_close_closes_injected_http_client():
    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
        await nsm.NsmClient(client).aclose()
        assert client.is_closed

    asyncio.run(go())


def test_older_redeposit_does_not_replace_newest_report():
    from dataclasses import replace

    current = filing()
    older = replace(current, disclosure_id="older", submitted_date="2026-11-08")
    assert nsm.tagged_annual_reports([current, older]) == [current]


def test_context_without_numeric_facts_has_no_validated_entity(monkeypatch):
    monkeypatch.setattr(nsm, "_throttle", AsyncMock())
    report = f"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:xbrli="http://www.xbrl.org/2003/instance">
<body><xbrli:context id="i"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{LEI}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context></body></html>""".encode()

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=report))
        ) as client:
            await nsm.NsmClient(client).fetch_tagged_facts(filing())

    with pytest.raises(nsm.NsmError, match="no declara un LEI"):
        asyncio.run(go())
