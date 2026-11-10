"""Annual exhibit fetch boundaries with no external requests."""

import asyncio

import httpx
import pytest

from app.services import annual_report_exhibits as exhibits
from app.services.connectors.sec_pacing import pacer

BASE = "https://www.sec.gov/Archives/edgar/data/1001085/000100108526000006/"
ACCESSION = "0001001085-26-000006"


def _row(name, size, kind="EX-99.2"):
    return f"<tr><td>1</td><td>Report</td><td>{name}</td><td>{kind}</td><td>{size}</td></tr>"


def test_parser_ignores_malformed_sizes_and_caps_largest_reports():
    html = "<tr><td>short row</td></tr>" + _row("broken.htm", "unknown") + _row("small.pdf", 99999)
    html += "".join(_row(f"report{i}.html", f"{100000 * i:,}") for i in range(1, 6))
    result = exhibits.parse_report_exhibits(html)
    assert [row["filename"] for row in result] == ["report5.html", "report4.html", "report3.html"]
    assert [row["size"] for row in result] == [500000, 400000, 300000]
    assert len(result) == exhibits.MAX_EXHIBITS
    assert exhibits.parse_report_exhibits(_row("minimum.pdf", 100000)) == [
        {"type": "EX-99.2", "filename": "minimum.pdf", "size": 100000, "description": "Report"},
    ]


@pytest.mark.parametrize(
    "filing",
    [
        {},
        {"index_url": BASE},
        {"accession_number": ACCESSION},
        {"index_url": BASE, "accession_number": "../bad"},
        {"index_url": BASE, "accession_number": "000100108526000006"},
    ],
)
def test_invalid_index_identity_has_no_url(filing):
    assert exhibits.index_page_url(filing) is None


@pytest.mark.parametrize("form", ["40-F", "40-F/A", "10-K", "10-K/A"])
def test_supported_form_fetches_paced_index_and_returns_absolute_exhibits(monkeypatch, form):
    calls = []

    async def wait():
        calls.append("pace")

    async def get(self, url):
        calls.append(url)
        assert self.timeout.read == 30.0
        assert self.headers["user-agent"]
        return httpx.Response(200, text=_row("full.pdf", "250,000"), request=httpx.Request("GET", url))

    monkeypatch.setattr(pacer, "wait", wait)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    filing = {"form": form.lower(), "index_url": BASE, "accession_number": ACCESSION}
    result = asyncio.run(exhibits.fetch_report_exhibits(filing))
    assert calls == ["pace", BASE + ACCESSION + "-index.html"]
    assert result == [
        {
            "type": "EX-99.2",
            "filename": "full.pdf",
            "size": 250000,
            "description": "Report",
            "url": BASE + "full.pdf",
        }
    ]


@pytest.mark.parametrize(
    "filing",
    [
        {"form": "20-F", "index_url": BASE, "accession_number": ACCESSION},
        {"form": "40-F", "index_url": BASE, "accession_number": "invalid"},
    ],
)
def test_ineligible_filing_never_paces_or_requests(monkeypatch, filing):
    async def forbidden(*args, **kwargs):
        pytest.fail("ineligible filing must not request SEC")

    monkeypatch.setattr(pacer, "wait", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "get", forbidden)
    assert asyncio.run(exhibits.fetch_report_exhibits(filing)) == []


@pytest.mark.parametrize("timeout", [False, True])
def test_fetch_errors_are_not_disguised_as_an_empty_index(monkeypatch, timeout):
    async def wait():
        return None

    async def get(self, url):
        request = httpx.Request("GET", url)
        if timeout:
            raise httpx.ReadTimeout("SEC unavailable", request=request)
        return httpx.Response(403, request=request)

    monkeypatch.setattr(pacer, "wait", wait)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    expected = httpx.ReadTimeout if timeout else httpx.HTTPStatusError
    with pytest.raises(expected):
        asyncio.run(
            exhibits.fetch_report_exhibits({"form": "40-F", "index_url": BASE, "accession_number": ACCESSION})
        )
