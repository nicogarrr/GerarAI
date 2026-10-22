from datetime import date

import pytest

from app.services.commitment_calendar import ANUNCIO_EMISOR, CALLS, UpcomingCall, next_calls
from app.services.commitment_coverage import coverage_with_checks


def test_official_vs_app_observed_never_mixed():
    cpt = next_calls("CPT", date(2026, 10, 22))[0]
    assert cpt["official_confirmation"] and cpt["date"] == "2026-11-06"
    kkr = next_calls("KKR", date(2026, 10, 22))[0]
    assert not kkr["official_confirmation"] and kkr["kind"] == "app_calendario_observado"


def test_past_dates_dropped_and_unknown_is_empty_not_no_call():
    assert next_calls("NAUT", date(2026, 10, 28)) == []
    assert next_calls("AAPL", date(2026, 10, 22)) == []


def test_official_requires_https_url_and_valid_date():
    with pytest.raises(ValueError):
        UpcomingCall("X", "2026-11-01", ANUNCIO_EMISOR, "e", None)
    with pytest.raises(ValueError):
        UpcomingCall("X", "2026-13-01", ANUNCIO_EMISOR, "e", "https://x.invalid")


def test_weekdays_match_announcements():
    wd = {c.ticker: date.fromisoformat(c.date).weekday() for c in CALLS if c.kind == ANUNCIO_EMISOR}
    assert wd == {"CPT": 4, "ABCL": 0, "NAUT": 1}  # vie, lun, mar


def test_coverage_rows_carry_next_calls():
    row = coverage_with_checks({}, ("CPT", "AAPL"), today=date(2026, 10, 22))
    assert row[0]["next_calls"][0]["source_url"].startswith("https://")
    assert row[1]["next_calls"] == []


def test_abcl_time_mismatch_preserved_and_flagged():
    c = next_calls("ABCL", date(2026, 10, 22))[0]
    assert c["time_source_inconsistent"] is True
    assert "3:00 p.m. Pacific Time (5:00 p.m. Eastern Time)" in c["detail"]
    assert next_calls("CPT", date(2026, 10, 22))[0]["time_source_inconsistent"] is False
