"""Ventana de frescura del último cierre (#2884: techo 24 h = «solo hoy»)."""

import pytest

from app.services.price_freshness import market_price_is_stale


@pytest.mark.parametrize("max_age_days", [0, 1, 3, 30])
def test_today_is_current_and_yesterday_is_not_for_any_setting(max_age_days):
    assert market_price_is_stale(0, max_age_days) is False
    assert market_price_is_stale(1, max_age_days) is True
    assert market_price_is_stale(5, max_age_days) is True


# --- A8: 24 h desde el cierre de la bolsa, no desde la medianoche UTC -------------
# Valores derivados a mano: NASDAQ cierra a las 16:00 de Nueva York (EDT = UTC-4
# hasta el 1-nov-2026, EST = UTC-5 después); BME a las 17:30 de Madrid (CET = UTC+1
# desde el 25-oct-2026); LSE a las 16:30 de Londres (GMT = UTC desde el 25-oct).

from datetime import UTC, date, datetime  # noqa: E402

from app.services.price_freshness import close_is_stale, session_close_at  # noqa: E402


def _utc(*parts):
    return datetime(*parts, tzinfo=UTC)


def test_session_close_instants_derived_by_hand():
    assert session_close_at(date(2026, 10, 29), "NASDAQ") == _utc(2026, 10, 29, 20, 0)
    assert session_close_at(date(2026, 11, 2), "NYSE") == _utc(2026, 11, 2, 21, 0)  # tras el cambio de hora
    assert session_close_at(date(2026, 10, 29), "BME") == _utc(2026, 10, 29, 16, 30)
    assert session_close_at(date(2026, 10, 29), "LSE") == _utc(2026, 10, 29, 16, 30)
    assert session_close_at(date(2026, 10, 29), "TSE") is None  # Tokio o Toronto: ambiguo
    assert session_close_at(date(2026, 10, 29), None) is None


@pytest.mark.parametrize("max_age_days", [0, 1, 3])
def test_yesterdays_us_close_is_current_before_the_open(max_age_days):
    # Jueves 29-oct cierre NASDAQ (20:00 UTC). Viernes 09:00 en Madrid = 08:00 UTC:
    # 12 h después del cierre, antes de la apertura (13:30 UTC). Antes: «sin cotización».
    assert close_is_stale(date(2026, 10, 29), "NASDAQ", max_age_days, now=_utc(2026, 10, 30, 8, 0)) is False
    assert close_is_stale(date(2026, 10, 29), "NASDAQ", max_age_days, now=_utc(2026, 10, 30, 19, 59)) is False
    # 24 h después del cierre ya debería existir el del viernes: caduca (techo #2884).
    assert close_is_stale(date(2026, 10, 29), "NASDAQ", max_age_days, now=_utc(2026, 10, 30, 20, 0)) is True


def test_no_weekend_exception_friday_close_expires_on_saturday():
    friday = date(2026, 10, 30)
    assert close_is_stale(friday, "NASDAQ", 1, now=_utc(2026, 10, 31, 19, 0)) is False
    assert close_is_stale(friday, "NASDAQ", 1, now=_utc(2026, 10, 31, 20, 0)) is True
    assert close_is_stale(friday, "NASDAQ", 1, now=_utc(2026, 11, 2, 8, 0)) is True


def test_dst_change_uses_new_york_close():
    monday = date(2026, 11, 2)  # 16:00 EST = 21:00 UTC
    assert close_is_stale(monday, "NASDAQ", 1, now=_utc(2026, 11, 3, 20, 30)) is False
    assert close_is_stale(monday, "NASDAQ", 1, now=_utc(2026, 11, 3, 21, 0)) is True


def test_madrid_close_before_and_after_next_session():
    assert close_is_stale(date(2026, 10, 29), "BME", 1, now=_utc(2026, 10, 30, 7, 0)) is False
    assert close_is_stale(date(2026, 10, 29), "BME", 1, now=_utc(2026, 10, 30, 16, 30)) is True


def test_today_intraday_snapshot_is_current():
    assert close_is_stale(date(2026, 10, 30), "NASDAQ", 0, now=_utc(2026, 10, 30, 14, 0)) is False


def test_unknown_exchange_keeps_calendar_day_rule():
    assert close_is_stale(date(2026, 10, 29), "UNKNOWN", 1, now=_utc(2026, 10, 29, 23, 0)) is False
    assert close_is_stale(date(2026, 10, 29), "UNKNOWN", 1, now=_utc(2026, 10, 30, 8, 0)) is True
