"""SEC payload shape failures are unavailable, not proof no filing exists."""
import asyncio
from datetime import date

import pytest

from app.services import earnings_materials_service as service
from tests.test_earnings_materials_service import FakeSEC


@pytest.mark.parametrize('payload', [
    {'filings': []}, {'filings': {'recent': []}},
    {'filings': {'recent': {'form': '8-K'}}},
    {'filings': {'recent': {'form': ['8-K'], 'items': '2.02'}}},
    {'filings': {'recent': {'form': ['8-K'], 'filingDate': {}}}},
])
def test_malformed_submissions_are_unavailable(payload):
    result = asyncio.run(service.resolve_materials(
        sec=FakeSEC(payload), ticker='TSLA', event_date=date(2026, 7, 22),
        fiscal_label='Jun/2026', confirmed=True,
    ))
    assert result['status'] == 'no_disponible'
    assert result['documents'] == []
