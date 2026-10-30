from datetime import UTC, date, datetime, timedelta, timezone

from app.services.display_es import fecha_es


def test_datetime_utc_after_madrid_midnight_shows_madrid_day():
    # 30 oct 2026 23:30 UTC = 31 oct 00:30 CET (UTC+1, tras el cambio de hora).
    assert fecha_es(datetime(2026, 10, 30, 23, 30, tzinfo=UTC)) == "31 oct 2026"
    # Verano: 22:15 UTC = 00:15 CEST del día siguiente.
    assert fecha_es(datetime(2026, 7, 14, 22, 15, tzinfo=UTC)) == "15 jul 2026"


def test_naive_datetime_is_utc():
    assert fecha_es(datetime(2026, 12, 31, 23, 5)) == "1 ene 2027"
    assert fecha_es(datetime(2026, 12, 31, 22, 59)) == "31 dic 2026"


def test_aware_non_utc_datetime_converted():
    ny = timezone(timedelta(hours=-4))
    # 20:30 en NY (UTC-4) = 00:30 UTC = 02:30 CEST del día siguiente.
    assert fecha_es(datetime(2026, 9, 1, 20, 30, tzinfo=ny)) == "2 sept 2026"


def test_plain_date_and_iso_text_unchanged():
    assert fecha_es(date(2026, 10, 18)) == "18 oct 2026"
    assert fecha_es("2026-10-18T23:30:00Z") == "18 oct 2026"
    assert fecha_es("ayer") == "ayer"


def test_none_is_nd():
    assert fecha_es(None) == "N/D"
