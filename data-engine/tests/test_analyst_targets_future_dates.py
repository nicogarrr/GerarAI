"""An analyst note dated in the future is not a published observation."""
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app.services import analyst_targets_service as svc

TODAY = date(2026, 11, 13)


def record(day, target=100):
    return {"firm": "Example Research", "date": day, "price_target": target}


@pytest.mark.parametrize("day", ["2026-11-14", date(2026, 11, 14), datetime(2026, 11, 14, 12, tzinfo=UTC), "2027-01-01"])
def test_future_notes_are_not_published(day):
    assert svc.normalize_rows([record(day)], reference_price=50, today=TODAY) == []


def test_future_note_cannot_replace_the_latest_real_note_from_the_same_firm():
    rows = svc.normalize_rows(
        [record("2026-11-12", 100), record("2026-11-14", 300)],
        reference_price=50, today=TODAY,
    )
    assert len(rows) == 1
    assert rows[0].date == "2026-11-12"
    assert rows[0].price_target == 100
    assert rows[0].upside_percent == 100


def test_today_and_exact_age_boundary_remain_valid():
    cutoff = TODAY - timedelta(days=svc.MAX_AGE_DAYS)
    for day in (TODAY, cutoff):
        assert len(svc.normalize_rows([record(day)], reference_price=None, today=TODAY)) == 1
    assert svc.normalize_rows([record(cutoff - timedelta(days=1))], reference_price=None, today=TODAY) == []


def test_service_excludes_future_note_with_real_default_clock(monkeypatch):
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: {
        "records": [record(tomorrow)], "consensus": {}, "currency": "USD",
    })
    result = asyncio.run(svc.AnalystTargetsService().get("EXAMPLE"))
    assert result.rows == []
    assert result.status == "empty"
    assert result.note_code == "no_targets"
