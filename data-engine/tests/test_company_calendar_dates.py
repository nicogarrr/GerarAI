"""Una fecha ilegible no confirma ausencia de eventos de resultados."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize("day", [None, "", "fecha ilegible", "2026-02-30", 0, False])
@pytest.mark.parametrize("keep_valid", [False, True])
def test_invalid_dates_do_not_claim_complete_calendar(day, keep_valid):
    invalid = {"symbol": "EXAMPLE", "date": day}
    valid = {"symbol": "EXAMPLE", "date": "2099-01-01"}
    rows = [invalid, valid] if keep_valid else [invalid]
    service = CompanyEventsService(
        None,
        calendar_fetcher=lambda *_: asyncio.sleep(0, {"earningsCalendar": rows}),
        eps_history_fetcher=lambda *_: asyncio.sleep(0, []),
    )
    result = asyncio.run(service.get_events(SimpleNamespace(ticker="EXAMPLE", name="Example")))
    assert result["calendar_status"] == ("partial" if keep_valid else "unavailable")
    assert result["note"]
    assert result["eps_history_status"] == "ok"
    assert result["history"] == []
    if keep_valid:
        assert result["next_event"]["date"] == valid["date"]
    else:
        assert result["next_event"] is None
