"""A cache hit must not claim the source was fetched again."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import macro_calendar_service as svc


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime(2026, 11, 13, 12, tzinfo=UTC), "mono": 100.0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"]

    monkeypatch.setattr(svc, "datetime", Clock)
    monkeypatch.setattr(svc.time, "monotonic", lambda: state["mono"])
    svc.clear_cache()
    yield state
    svc.clear_cache()


def sources(monkeypatch):
    fomc = AsyncMock(return_value=[{"date": "2026-12-09", "start_date": "2026-12-08", "projections": True}])
    bls = AsyncMock(return_value=[{"date": "2026-12-10", "title": "Consumer Price Index", "time_et": "08:30"}])
    monkeypatch.setattr(svc.connector, "fetch_fomc", fomc)
    monkeypatch.setattr(svc.connector, "fetch_bls", bls)
    return fomc, bls


def read(**kwargs):
    return asyncio.run(svc.get_macro_events(date(2026, 11, 13), date(2026, 12, 9), **kwargs))


def test_hot_cache_preserves_source_fetch_time(clock, monkeypatch):
    fomc, bls = sources(monkeypatch)
    first = read()
    clock["now"] += timedelta(hours=1)
    clock["mono"] += 3600
    second = read()
    assert fomc.await_count == bls.await_count == 1
    assert [row["fetched_at"] for row in second["sources"]] == [row["fetched_at"] for row in first["sources"]]
    assert first["events"] == second["events"]


def test_expired_cache_records_new_fetch_time(clock, monkeypatch):
    fomc, bls = sources(monkeypatch)
    first = read()
    clock["now"] += timedelta(seconds=svc.CACHE_TTL_SECONDS)
    clock["mono"] += svc.CACHE_TTL_SECONDS
    second = read()
    assert fomc.await_count == bls.await_count == 2
    assert all(row["fetched_at"] == clock["now"].isoformat() for row in second["sources"])
    assert second["sources"][0]["fetched_at"] != first["sources"][0]["fetched_at"]


def test_injected_client_still_bypasses_cache(clock, monkeypatch):
    fomc, bls = sources(monkeypatch)
    read(client=object())
    clock["now"] += timedelta(minutes=5)
    second = read(client=object())
    assert fomc.await_count == bls.await_count == 2
    assert all(row["fetched_at"] == clock["now"].isoformat() for row in second["sources"])
    assert not svc._cache


def test_failed_refresh_is_unavailable_not_stale_success(clock, monkeypatch):
    fomc, bls = sources(monkeypatch)
    read()
    clock["now"] += timedelta(seconds=svc.CACHE_TTL_SECONDS)
    clock["mono"] += svc.CACHE_TTL_SECONDS
    fomc.side_effect = httpx.ConnectError("offline")
    second = read()
    assert [row["status"] for row in second["sources"]] == ["unavailable", "ready"]
    assert second["sources"][0]["fetched_at"] == clock["now"].isoformat()
    assert all(event["kind"] != "fomc" for event in second["events"])
