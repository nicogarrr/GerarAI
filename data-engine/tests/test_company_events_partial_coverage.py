"""One successful calendar chunk does not prove complete earnings coverage."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize("failed", [1, 3, 5])
def test_missing_chunks_are_partial_not_all_clear(failed):
    count = 0

    async def calendar(start, end):
        nonlocal count
        count += 1
        return None if count <= failed else {"earningsCalendar": []}

    service = CompanyEventsService(None, calendar_fetcher=calendar,
                                  eps_history_fetcher=lambda symbol: asyncio.sleep(0, []))
    result = asyncio.run(service.get_events(SimpleNamespace(ticker="EXAMPLE", name="Example")))
    assert count == 6
    assert result["calendar_status"] == "partial"
    assert result["note"] and "parcial" in result["note"].lower()
    assert result["next_event"] is None
    assert result["eps_history_status"] == "ok"


def test_calendar_outage_remains_explicit_even_with_eps_history():
    service = CompanyEventsService(None, calendar_fetcher=lambda *args: asyncio.sleep(0, None),
                                  eps_history_fetcher=lambda symbol: asyncio.sleep(0, []))
    result = asyncio.run(service.get_events(SimpleNamespace(ticker="EXAMPLE", name="Example")))
    assert result["calendar_status"] == "unavailable"
    assert result["eps_history_status"] == "ok"
    assert result["note"] and "calendario" in result["note"].lower()


def test_eps_outage_is_not_hidden_by_successful_calendar():
    service = CompanyEventsService(None, calendar_fetcher=lambda *args: asyncio.sleep(0, {"earningsCalendar": []}),
                                  eps_history_fetcher=lambda symbol: asyncio.sleep(0, None))
    result = asyncio.run(service.get_events(SimpleNamespace(ticker="EXAMPLE", name="Example")))
    assert result["calendar_status"] == "ok"
    assert result["eps_history_status"] == "unavailable"
    assert result["note"] and "BPA" in result["note"]


def test_successful_empty_calendar_is_not_mislabelled_as_outage():
    service = CompanyEventsService(None, calendar_fetcher=lambda *args: asyncio.sleep(0, {"earningsCalendar": []}),
                                  eps_history_fetcher=lambda symbol: asyncio.sleep(0, []))
    result = asyncio.run(service.get_events(SimpleNamespace(ticker="EXAMPLE", name="Example")))
    assert result["calendar_status"] == result["eps_history_status"] == "ok"
    assert result["note"] is None
