"""Historical-stress loader: HTTP boundary, adjusted closes and cache without network."""

from __future__ import annotations

import asyncio
from datetime import UTC, date
from datetime import datetime as RealDatetime
from types import SimpleNamespace

import httpx
import pytest

from app.services import historical_stress_service as svc


class FixedDatetime(RealDatetime):
    @classmethod
    def now(cls, tz=None):
        return RealDatetime(2026, 11, 10, 12, tzinfo=UTC).astimezone(tz)


@pytest.fixture
def loader(monkeypatch):
    requests = []
    successes = []
    failures = []
    state = {"now": 100000.0, "handler": None}
    real_client = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return state["handler"](request)

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(svc.httpx, "AsyncClient", client)
    monkeypatch.setattr(svc, "datetime", FixedDatetime)
    monkeypatch.setattr(svc, "_CACHE", {})
    monkeypatch.setattr(svc.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(
        svc,
        "get_data_source_registry",
        lambda: SimpleNamespace(
            record_success=lambda *args: successes.append(args),
            record_failure=lambda *args: failures.append(args),
        ),
    )
    return SimpleNamespace(state=state, requests=requests, successes=successes, failures=failures)


def payload(values=None, stamps=None):
    if values is None:
        values = [10.0]
    if stamps is None:
        stamps = [int(RealDatetime(2020, 1, 2, 16, tzinfo=UTC).timestamp())]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"exchangeTimezoneName": "America/New_York", "currency": "USD"},
                    "timestamp": stamps,
                    "indicators": {"adjclose": [{"adjclose": values}], "quote": [{"close": [999.0]}]},
                }
            ]
        }
    }


def respond(loader, data):
    loader.state["handler"] = lambda request: httpx.Response(200, json=data, request=request)


def load(ticker="TEST"):
    return asyncio.run(svc.load_history(ticker))


def test_adjusted_only_finite_positive_completed_local_days_and_request(loader):
    # 00:30 UTC is still November 9 in New York, so this observation is complete.
    dates = (
        [RealDatetime(2026, 11, 10, 0, 30, tzinfo=UTC)]
        + [RealDatetime(2020, 1, day, 16, tzinfo=UTC) for day in range(2, 8)]
        + [RealDatetime(2026, 11, 10, 16, tzinfo=UTC)]
    )
    data = payload([42.0, None, 0, -2, "NaN", "Infinity", 12.0, 100.0], [int(d.timestamp()) for d in dates])
    respond(loader, data)
    result = load("ABC/DEF")
    assert result["prices"] == {date(2026, 11, 9): 42.0, date(2020, 1, 7): 12.0}
    request = loader.requests[0]
    assert request.url.raw_path.split(b"?")[0].endswith(b"/ABC%2FDEF")
    assert request.url.params["interval"] == "1d"
    assert int(request.url.params["period1"]) == int(RealDatetime(2007, 12, 1, tzinfo=UTC).timestamp())
    assert int(request.url.params["period2"]) == int(FixedDatetime.now(UTC).timestamp())
    assert result["source_url"] == str(request.url)
    assert result["source"] == "Yahoo Finance" and result["currency"] == "USD"
    assert result["fetched_at"] == FixedDatetime.now(UTC).isoformat()
    assert len(loader.successes) == 1 and loader.successes[0][0] == "yahoo_finance"
    assert loader.successes[0][1] >= 0 and not loader.failures


def test_cache_key_and_strict_six_hour_expiry(loader):
    respond(loader, payload())
    first = load()
    loader.state["now"] += 21599
    assert load() is first and len(loader.requests) == 1
    # Another symbol does not borrow TEST's cache.
    load("OTHER")
    loader.state["now"] += 1
    assert load() == first and len(loader.requests) == 3
    assert len(loader.successes) == 3


def test_cache_capacity_evicts_oldest_entry_not_new_result(loader):
    respond(loader, payload())
    svc._CACHE.update({f"OLD{i}": (loader.state["now"], {"sentinel": i}) for i in range(256)})
    result = load()
    assert len(svc._CACHE) == 256
    assert "OLD0" not in svc._CACHE and "OLD1" in svc._CACHE
    assert svc._CACHE["TEST"][1] is result


@pytest.mark.parametrize(
    "status,source_failure", [(400, False), (404, False), (429, True), (999, True), (500, True)]
)
def test_http_failures_never_cache_and_only_provider_errors_degrade_source(loader, status, source_failure):
    loader.state["handler"] = lambda request: httpx.Response(status, request=request)
    with pytest.raises(httpx.HTTPStatusError):
        load()
    assert not svc._CACHE and not loader.successes
    assert bool(loader.failures) is source_failure
    if source_failure:
        assert loader.failures[0][0] == "yahoo_finance"
        assert f"HTTP {status}" in loader.failures[0][1]
        assert ("CAPTCHA" in loader.failures[0][1]) is (status in (429, 999))


def test_transport_failure_records_source_without_cache(loader):
    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    loader.state["handler"] = fail
    with pytest.raises(httpx.ConnectError):
        load()
    assert not loader.successes and not svc._CACHE
    assert loader.failures == [("yahoo_finance", "error de red: ConnectError")]


def test_non_json_response_records_failure_not_success(loader):
    loader.state["handler"] = lambda request: httpx.Response(
        200, text="<html>challenge</html>", request=request
    )
    with pytest.raises(ValueError):
        load()
    assert not loader.successes and not svc._CACHE
    assert len(loader.failures) == 1 and "no JSON" in loader.failures[0][1]


def test_incomplete_adjusted_series_does_not_use_raw_close_or_cache(loader):
    respond(loader, payload([], [1]))
    with pytest.raises(ValueError, match="Incomplete adjusted-close"):
        load()
    # Valid JSON HTTP success is recorded before ticker-specific validation.
    assert len(loader.successes) == 1 and not loader.failures and not svc._CACHE


def test_missing_adjusted_close_never_falls_back_to_quote(loader):
    data = payload()
    del data["chart"]["result"][0]["indicators"]["adjclose"]
    respond(loader, data)
    with pytest.raises(ValueError, match="Incomplete adjusted-close"):
        load()
    assert not svc._CACHE and not loader.failures and len(loader.successes) == 1
