"""Pure classifier contract. All prices/dates here are synthetic fixtures."""
from datetime import UTC, datetime, timedelta

import pytest

from app.services.vix_context import VIX_SOURCE_URL, vix_context

NOW = datetime(2026, 11, 20, 17, tzinfo=UTC)


def point(value=31):
    return {"value": value, "date": "2026-11-19", "fetched_at": "2026-11-20T14:00:00Z",
            "source": "FRED", "source_url": VIX_SOURCE_URL, "unit": "índice"}


@pytest.mark.parametrize("value,band", [(14.99, "low"), (15, "middle"), (20, "middle"), (30, "middle"), (30.01, "high")])
def test_thresholds(value, band):
    result = vix_context(point(value), NOW)
    assert result["status"] == "available"
    assert result["band"] == band
    assert result["frequency"] == "daily_close"
    assert result["date"] == "2026-11-19"
    assert result["source_url"] == VIX_SOURCE_URL
    assert "action" not in result


@pytest.mark.parametrize("value", [True, "31", None, -1, 0, float("nan"), float("inf"), {}])
def test_invalid_values(value):
    assert vix_context(point(value), NOW)["reason"] == "invalid"


@pytest.mark.parametrize("patch", [
    {"date": "bad"}, {"date": "2026-11-21"}, {"date": None},
    {"fetched_at": "2026-11-20T18:00:00Z"}, {"fetched_at": "2026-11-19T14:00:00"},
    {"fetched_at": "bad"}, {"source": "screenshot"}, {"source_url": "https://example.com"},
    {"unit": "porcentaje"}, {"date": "2026-11-20", "fetched_at": "2026-11-19T14:00:00Z"},
])
def test_untrusted_or_future_metadata(patch):
    result = vix_context({**point(), **patch}, NOW)
    assert result["reason"] == "invalid"
    assert "band" not in result and "value" not in result


@pytest.mark.parametrize("metric", [None, {}, [], "31"])
def test_missing(metric):
    assert vix_context(metric, NOW)["reason"] == "missing"


def test_age_is_observation_age_not_snapshot_or_download_age():
    p = {**point(), "date": "2026-11-15"}
    assert vix_context(p, NOW)["status"] == "available"
    stale = vix_context(p, NOW + timedelta(days=1))
    assert stale["reason"] == "stale" and "band" not in stale
    assert stale["date"] == "2026-11-15"


def test_naive_request_time_is_rejected():
    assert vix_context(point(), NOW.replace(tzinfo=None))["reason"] == "invalid"
