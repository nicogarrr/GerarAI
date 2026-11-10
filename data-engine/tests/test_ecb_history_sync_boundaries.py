"""ECB history synchronous HTTP seams with local transport and registry."""

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest

from app.services.connectors import ecb_history as ecb

DAY = date(2026, 11, 9)


@pytest.mark.parametrize("status", [200, 404, 500])
def test_sync_fetch_request_and_registry_outcome(monkeypatch, status):
    registry = Mock()
    monkeypatch.setattr(ecb, "get_data_source_registry", lambda: registry)
    requests = []
    original_client = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="local CSV fixture")

    monkeypatch.setattr(
        ecb.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw)
    )
    if status == 200:
        assert ecb.fetch_ecb_csv_sync(["USD", "GBP"], DAY, DAY) == "local CSV fixture"
        registry.record_success.assert_called_once()
        assert registry.record_success.call_args.args[0] == "ecb"
        assert registry.record_success.call_args.args[1] >= 0
        registry.record_failure.assert_not_called()
    else:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            ecb.fetch_ecb_csv_sync(["USD", "GBP"], DAY, DAY)
        assert exc.value.response.status_code == status
        registry.record_failure.assert_called_once_with("ecb", f"HTTP {status}")
        registry.record_success.assert_not_called()
    assert len(requests) == 1
    request = requests[0]
    assert request.url.scheme == "https" and request.url.host == "data-api.ecb.europa.eu"
    assert request.url.path == "/service/data/EXR/D.GBP+USD.EUR.SP00.A"
    assert dict(request.url.params) == {
        "startPeriod": "2026-11-09",
        "endPeriod": "2026-11-09",
        "format": "csvdata",
    }


def test_sync_transport_failure_records_failure_and_reraises_same_error(monkeypatch):
    registry = Mock()
    monkeypatch.setattr(ecb, "get_data_source_registry", lambda: registry)
    original_client = httpx.Client
    error = httpx.ConnectError("local unavailable")

    def handler(request):
        raise error

    monkeypatch.setattr(
        ecb.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw)
    )
    with pytest.raises(httpx.ConnectError) as exc:
        ecb.fetch_ecb_csv_sync(["USD"], DAY, DAY)
    assert exc.value is error
    registry.record_failure.assert_called_once_with("ecb", "error de red: ConnectError")
    registry.record_success.assert_not_called()


def test_csv_missing_malformed_and_nonpositive_rows_do_not_supply_rates():
    text = """CURRENCY,TIME_PERIOD,OBS_VALUE
 usd ,2026-11-09, 1.25
,2026-11-09,1
USD,,1
USD,2026-11-09,
USD,bad-date,1
USD,2026-11-09,bad-number
USD,2026-11-09,0
USD,2026-11-09,-1
"""
    assert ecb.parse_ecb_csv(text) == [(DAY, "USD", Decimal("1.25"))]


def test_backfill_non_euro_base_rejected_without_fetching():
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    with pytest.raises(ValueError, match="base EUR"):
        asyncio.run(
            ecb.backfill_ecb_rates(
                object(), currencies={"USD"}, start=DAY, end=DAY, base_currency="USD", fetcher=fetch
            )
        )
    fetch.assert_not_called()


def test_only_euro_request_is_empty_without_fetch_or_commit():
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    db = Mock()
    assert asyncio.run(
        ecb.backfill_ecb_rates(db, currencies={"EUR", " eur ", ""}, start=DAY, end=DAY, fetcher=fetch)
    ) == {"source": "ECB", "written": {}, "not_published": []}
    fetch.assert_not_called()
    db.commit.assert_not_called()


def test_async_transport_failure_records_failure_and_reraises_same_error(monkeypatch):
    registry = Mock()
    monkeypatch.setattr(ecb, "get_data_source_registry", lambda: registry)
    original_client = httpx.AsyncClient
    error = httpx.ConnectError("local async unavailable")

    def handler(request):
        raise error

    monkeypatch.setattr(
        ecb.httpx,
        "AsyncClient",
        lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(httpx.ConnectError) as exc:
        asyncio.run(ecb.fetch_ecb_csv(["USD"], DAY, DAY))
    assert exc.value is error
    registry.record_failure.assert_called_once_with("ecb", "error de red: ConnectError")
    registry.record_success.assert_not_called()
