"""A valid publication date does not authenticate malformed clock fields."""
import pytest

from app.services.connectors.macro_calendar import parse_bls_ics


@pytest.mark.parametrize('clock', ['250000', '086000', '083061'])
def test_impossible_bls_clock_is_not_published_as_event_time(clock):
    text = f'BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261113T{clock}\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR'
    event = parse_bls_ics(text)[0]
    assert event['date'] == '2026-11-13'
    assert event['time_et'] is None


@pytest.mark.parametrize('clock,expected', [('083000', '08:30'), ('000000', '00:00'), ('235959', '23:59')])
def test_valid_bls_clock_is_preserved(clock, expected):
    text = f'BEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261113T{clock}\nSUMMARY:Employment Situation\nEND:VEVENT'
    assert parse_bls_ics(text)[0]['time_et'] == expected


def test_bls_all_day_event_has_no_invented_clock():
    text = 'BEGIN:VEVENT\nDTSTART;VALUE=DATE:20261113\nSUMMARY:Consumer Price Index\nEND:VEVENT'
    assert parse_bls_ics(text) == [{'title': 'Consumer Price Index', 'date': '2026-11-13', 'time_et': None}]


def test_invalid_calendar_date_is_not_an_event():
    text = 'BEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261345T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT'
    assert parse_bls_ics(text) == []
