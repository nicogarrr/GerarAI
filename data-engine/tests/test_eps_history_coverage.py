"""Invalid EPS periods are missing coverage, not verified absence."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


def run_history(rows):
    service = CompanyEventsService(
        None,
        calendar_fetcher=lambda *_: asyncio.sleep(0, {"earningsCalendar": []}),
        eps_history_fetcher=lambda *_: asyncio.sleep(0, rows),
    )
    return asyncio.run(service.get_events(SimpleNamespace(ticker="ABC", name="Example")))


@pytest.mark.parametrize("row", [{}, {"period": "bad"}, {"period": "2999-01-01"}, "bad", None])
def test_unverifiable_eps_row_is_not_ok_empty(row):
    result = run_history([row])
    assert result["eps_history_status"] == "unavailable"
    assert result["history"] == []
    assert "BPA" in result["note"]


def test_mixed_history_keeps_verified_period_and_warns():
    period = (datetime.now(UTC).date() - timedelta(days=60)).isoformat()
    result = run_history([{"period": period, "actual": 2}, {"period": "bad"}])
    assert result["eps_history_status"] == "partial"
    assert result["history"][0]["eps_actual"] == 2
    assert "BPA parcial" in result["note"]


def test_explicit_empty_list_is_still_verified_empty():
    result = run_history([])
    assert result["eps_history_status"] == "ok"
    assert result["note"] is None
