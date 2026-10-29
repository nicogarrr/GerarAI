"""Ventana de frescura del último cierre (#2884: techo 24 h = «solo hoy»)."""

import pytest

from app.services.price_freshness import market_price_is_stale


@pytest.mark.parametrize("max_age_days", [0, 1, 3, 30])
def test_today_is_current_and_yesterday_is_not_for_any_setting(max_age_days):
    assert market_price_is_stale(0, max_age_days) is False
    assert market_price_is_stale(1, max_age_days) is True
    assert market_price_is_stale(5, max_age_days) is True
