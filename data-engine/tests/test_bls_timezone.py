"""BLS release clocks must be converted to the ET contract, never relabelled."""
import pytest

from app.services.connectors.macro_calendar import parse_bls_ics


@pytest.mark.parametrize('start,day,hour', [
    ('DTSTART;TZID=US-Eastern:20261113T0830', '2026-11-13', '08:30'),
    ('DTSTART:20261113T133000Z', '2026-11-13', '08:30'),
    ('DTSTART:20260713T123000Z', '2026-07-13', '08:30'),
    ('DTSTART:20261113T010000Z', '2026-11-12', '20:00'),
    ('DTSTART;TZID=Europe/London:20261113T133000', '2026-11-13', '08:30'),
    ('DTSTART;TZID=Unknown/Zone:20261113T083000', '2026-11-13', None),
])
def test_bls_clock_timezone_is_not_silently_called_new_york(start, day, hour):
    text = f'BEGIN:VEVENT\n{start}\nSUMMARY:Consumer Price Index\nEND:VEVENT'
    assert parse_bls_ics(text) == [{'title': 'Consumer Price Index', 'date': day, 'time_et': hour}]
