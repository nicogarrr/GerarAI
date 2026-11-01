"""Tests hermeticos de los conectores gratuitos (SEC EDGAR + FRED). Sin red."""

import asyncio

import httpx
import pytest

from app.services.connectors import fred as fred_connector
from app.services.connectors import sec_edgar as sec_edgar_connector
from app.services.connectors.fred import FREDClient
from app.services.financial_ingestion_service import _free_data_snapshot


@pytest.fixture(autouse=True)
def _clean_sec_pacer():
    from app.services.connectors.sec_pacing import pacer

    pacer.reset()
    yield
    pacer.reset()


def run_async(coroutine):
    return asyncio.run(coroutine)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------- SEC EDGAR ----------------


def test_sec_edgar_user_agent_carries_contact():
    async def probe():
        seen = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["ua"] = request.headers.get("user-agent", "")
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}}, request=request)

        async with _client(handler) as client:
            cik = await sec_edgar_connector.cik_for_ticker("aapl", client)
        return cik, seen["ua"]

    cik, ua = run_async(probe())
    assert cik == "0000320193"
    assert "@" in ua  # la SEC exige contacto en el User-Agent


def test_sec_edgar_cik_none_when_not_a_filer():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}}, request=request
            )

        async with _client(handler) as client:
            return await sec_edgar_connector.cik_for_ticker("NOPE", client)

    assert run_async(probe()) is None


def test_sec_edgar_tolerates_429_with_backoff_then_succeeds(monkeypatch):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fast_sleep(delay):
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    calls = {"n": 0}

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(
                    429, text="slow down", headers={"Retry-After": "0"}, request=request
                )
            return httpx.Response(200, json={"ok": True}, request=request)

        async with _client(handler) as client:
            return await sec_edgar_connector._get_json(
                "https://data.sec.gov/x", client, base_delay=0.01
            )

    assert run_async(probe()) == {"ok": True}
    assert calls["n"] == 3
    assert len([s for s in sleeps if s < 1]) == 2  # dos backoffs, ademas del pacing compartido


def test_sec_edgar_recent_filings_filters_10k_10q():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000123", "0000320193-24-000100"],
                "form": ["10-K", "8-K"],
                "filingDate": ["2024-11-01", "2024-10-15"],
                "reportDate": ["2024-09-28", "2024-10-15"],
                "primaryDocument": ["aapl-20240928.htm", "current-report.htm"],
            }
        }
    }

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload, request=request)

        async with _client(handler) as client:
            return await sec_edgar_connector.recent_filings("320193", client=client)

    items = run_async(probe())
    assert len(items) == 1  # el 8-K queda fuera
    assert items[0]["form"] == "10-K"
    assert items[0]["document_url"].endswith("320193/000032019324000123/aapl-20240928.htm")


def test_sec_edgar_get_fundamentals_picks_first_reporting_tag():
    facts = {
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 391035000000,
                                "filed": "2024-11-01",
                                "form": "10-K",
                            }
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 93736000000,
                                "filed": "2024-11-01",
                                "form": "10-K",
                            }
                        ]
                    }
                },
            }
        },
    }
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": [],
                "form": [],
                "filingDate": [],
                "reportDate": [],
                "primaryDocument": [],
            }
        }
    }

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            if "companyfacts" in request.url.path:
                return httpx.Response(200, json=facts, request=request)
            if "company_tickers" in request.url.path:
                return httpx.Response(
                    200,
                    json={"0": {"cik_str": 320193, "ticker": "AAPL"}},
                    request=request,
                )
            return httpx.Response(200, json=submissions, request=request)

        async with _client(handler) as client:
            return await sec_edgar_connector.get_fundamentals("AAPL", client=client)

    result = run_async(probe())
    assert result["status"] == "ok"
    assert result["cik"] == "0000320193"
    assert result["metrics"]["revenue"]["value"] == 391035000000
    assert result["metrics"]["net_income"]["form"] == "10-K"


def test_sec_edgar_get_fundamentals_unavailable_for_non_filer():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}}, request=request
            )

        async with _client(handler) as client:
            return await sec_edgar_connector.get_fundamentals("NOPE", client=client)

    result = run_async(probe())
    assert result["status"] == "unavailable"


# ---------------- FRED ----------------


def _no_fred_key(monkeypatch):
    """Deja FRED sin clave tanto en entorno como en settings (hermetico)."""
    from app.core.config import get_settings

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(get_settings(), "fred_api_key", None)


def test_fred_degrades_to_none_without_key(monkeypatch):
    _no_fred_key(monkeypatch)
    assert fred_connector.get_api_key() is None
    assert fred_connector.is_configured() is False
    assert run_async(fred_connector.fetch_observations("cpi")) is None
    assert run_async(fred_connector.latest_observation("cpi")) is None


def test_fred_client_series_still_raises_without_key(monkeypatch):
    _no_fred_key(monkeypatch)
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        run_async(FREDClient().series("CPIAUCSL"))


def test_fred_alias_resolves_and_parses_latest(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    payload = {
        "observations": [
            {"date": "2024-10-01", "value": "314.175"},
            {"date": "2024-11-01", "value": "."},
            {"date": "2024-12-01", "value": "315.605"},
        ]
    }
    seen = {}

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            seen["ua"] = request.headers.get("user-agent", "")
            return httpx.Response(200, json=payload, request=request)

        async with _client(handler) as client:
            return await fred_connector.latest_observation("cpi", client=client)

    latest = run_async(probe())
    assert latest == {"series_id": "CPIAUCSL", "date": "2024-10-01", "value": 314.175}
    assert seen["params"]["series_id"] == "CPIAUCSL"
    assert seen["params"]["api_key"] == "test-key"
    assert "Mozilla" in seen["ua"]  # User-Agent de navegador


def test_fred_raw_series_id_passes_through(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"observations": [{"date": "2024-01-01", "value": "5.3"}]},
                request=request,
            )

        async with _client(handler) as client:
            return await fred_connector.latest_observation("DGS10", client=client)

    assert run_async(probe())["series_id"] == "DGS10"


def test_fred_invalid_indicator_raises_value_error():
    with pytest.raises(ValueError, match="no es un alias"):
        fred_connector.resolve_series_id("bank of japan rate prefix that is way too long")


# ---------------- Hook best-effort ----------------


def test_free_data_snapshot_never_breaks_the_flow(monkeypatch):
    async def boom(*args, **kwargs):
        raise httpx.ConnectError("red caida")

    monkeypatch.setattr(sec_edgar_connector, "recent_filings", boom)
    monkeypatch.setattr(fred_connector, "latest_observation", boom)
    snapshot = run_async(_free_data_snapshot("AAPL", "0000320193"))
    assert snapshot["recent_filings"] == []
    assert snapshot["macro"] is None
    assert "filings_error" in snapshot


def test_free_data_snapshot_collects_both_sources(monkeypatch):
    async def fake_filings(*args, **kwargs):
        return [{"form": "10-K", "accession_number": "x"}]

    async def fake_macro(*args, **kwargs):
        return {"series_id": "CPIAUCSL", "date": "2024-12-01", "value": 315.605}

    monkeypatch.setattr(sec_edgar_connector, "recent_filings", fake_filings)
    monkeypatch.setattr(fred_connector, "latest_observation", fake_macro)
    snapshot = run_async(_free_data_snapshot("AAPL", "0000320193"))
    assert snapshot["status"] == "ok"
    assert snapshot["recent_filings"][0]["form"] == "10-K"
    assert snapshot["macro"]["series_id"] == "CPIAUCSL"
