"""ICS titles preserve known estimated and unknown earnings confirmation."""
from datetime import UTC, datetime

import pytest

from app.services.calendar_feed_service import build_ics


@pytest.mark.parametrize(('confirmed', 'notice'), [
    (None, 'confirmación no indicada por la fuente'),
    (False, 'fecha estimada'),
    (True, None),
])
def test_ics_preserves_confirmation_status(confirmed, notice):
    source = 'NASDAQ'
    url = 'https://example.com/earnings'
    event = {'date': '2026-11-20', 'company': 'Example', 'ticker': 'EX',
             'confirmed': confirmed, 'session': None, 'fiscal_label': 'Q3 2026',
             'source': source, 'source_url': url}
    ics = build_ics({'days': [{'events': [event]}]}, now=datetime(2026, 11, 14, tzinfo=UTC))
    unfolded = ics.replace('\r\n ', '')
    summary = next(line for line in unfolded.splitlines() if line.startswith('SUMMARY:'))
    if notice:
        assert notice in summary
        assert f'DESCRIPTION:Mañana: Example (EX): resultados ({notice})' in unfolded
    else:
        assert summary == 'SUMMARY:Example (EX): resultados'
        assert 'fecha estimada' not in unfolded
        assert 'confirmación no indicada' not in unfolded
    assert 'DTSTART;VALUE=DATE:20261120' in unfolded
    assert 'DTEND;VALUE=DATE:20261121' in unfolded
    assert f'Fuente: {source}' in unfolded
    assert f'URL:{url}' in unfolded
    assert all(len(line.encode()) <= 75 for line in ics.split('\r\n'))
