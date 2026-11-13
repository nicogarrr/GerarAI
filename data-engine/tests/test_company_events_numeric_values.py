"""A malformed numeric provider field must not poison the events JSON."""
import json
from datetime import date

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 'not-a-number', True])
def test_invalid_finnhub_numbers_are_unknown_not_json_errors(bad):
    service = CompanyEventsService(None)
    row = {'date': '2026-11-01', 'epsEstimate': bad, 'epsActual': bad,
           'revenueEstimate': bad, 'revenueActual': bad}
    history = service._history([row], [{'period': '2026-09-30', 'actual': bad,
                                      'estimate': bad, 'surprisePercent': bad}], date(2026, 11, 13))
    for item in history:
        for key in ('eps_estimate', 'eps_actual', 'revenue_estimate', 'revenue_actual', 'eps_surprise_percent'):
            assert item[key] is None
    event = service._next_event([{**row, 'date': '2026-12-01'}], date(2026, 11, 13))
    assert event['eps_estimate'] is event['revenue_estimate'] is None
    json.dumps([history, event], allow_nan=False)


def test_negative_eps_and_zero_actual_are_real_values():
    service = CompanyEventsService(None)
    history = service._history([], [{'period': '2026-09-30', 'actual': 0,
                                    'estimate': -1.5, 'surprisePercent': -20}], date(2026, 11, 13))
    assert history[0]['eps_actual'] == 0
    assert history[0]['eps_estimate'] == -1.5
    assert history[0]['eps_surprise_percent'] == -20
