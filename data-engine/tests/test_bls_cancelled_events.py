"""A cancelled release is not an upcoming official publication."""
from app.services.connectors.macro_calendar import parse_bls_ics


def _event(status: str | None) -> str:
    lines = ['BEGIN:VEVENT', 'DTSTART;TZID=US-Eastern:20261113T083000',
             'SUMMARY:Consumer Price Index']
    if status is not None:
        lines.append(f'STATUS:{status}')
    return '\r\n'.join([*lines, 'END:VEVENT'])


def test_cancelled_release_is_not_published_as_scheduled():
    result = parse_bls_ics('BEGIN:VCALENDAR\r\n' + _event('CANCELLED') + '\r\nEND:VCALENDAR')
    assert result == []


def test_cancellation_does_not_hide_other_releases():
    result = parse_bls_ics('BEGIN:VCALENDAR\r\n' + _event('CANCELLED') + '\r\n'
                           + _event('CONFIRMED') + '\r\n' + _event(None) + '\r\nEND:VCALENDAR')
    assert len(result) == 2
    assert all(row['date'] == '2026-11-13' for row in result)
