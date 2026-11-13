"""Reject malformed index observations without inventing an older replacement."""
from types import SimpleNamespace

import httpx
import pytest

from app.api.routes.market import _fetch_index


def fetch(closes, *, timestamps=None, status=200):
    node = {"indicators": {"quote": [{"close": closes}]}}
    if timestamps is not None:
        node["timestamp"] = timestamps
    response = SimpleNamespace(status_code=status, json=lambda: {"chart": {"result": [node]}})
    client = SimpleNamespace(get=lambda *args, **kwargs: response)
    return _fetch_index(client, "^GSPC")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, False, "100", {}, [], 0, -100])
@pytest.mark.parametrize("position", [0, 1])
def test_invalid_close_cannot_become_price_or_change(bad, position):
    closes = [100, 101]
    closes[position] = bad
    assert fetch(closes) is None


def test_bad_newest_close_does_not_silently_fall_back_to_older_data():
    assert fetch([99, 100, -1], timestamps=[10, 20, 30]) is None


def test_finite_inputs_cannot_publish_infinite_derived_change():
    assert fetch([1e-300, 1e300]) is None


def test_null_gaps_preserve_timestamp_alignment_and_real_variation():
    quote = fetch([100, None, 101, None], timestamps=[10, 20, 30, 40])
    assert quote == {"symbol": "^GSPC", "priceAsOf": 30, "price": 101.0,
                     "change": 1.0, "changePercent": 1.0}


def test_missing_timestamp_is_not_fabricated():
    assert fetch([100, 100])["priceAsOf"] is None


@pytest.mark.parametrize("closes", [[], [100], [None, 100], [None, None]])
def test_missing_real_comparison_is_unavailable(closes):
    assert fetch(closes) is None


def test_http_error_response_is_unavailable():
    assert fetch([100, 101], status=429) is None


def test_transport_failure_is_unavailable():
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")
    assert _fetch_index(SimpleNamespace(get=fail), "^GSPC") is None


def test_malformed_payload_is_unavailable():
    response = SimpleNamespace(status_code=200, json=lambda: {})
    assert _fetch_index(SimpleNamespace(get=lambda *args, **kwargs: response), "^GSPC") is None
