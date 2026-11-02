"""Telegram: la fecha de una noticia/documento se escribe en el día de Madrid.

NewsEvent.date se guarda en UTC. Un 8-K publicado a las 23:30 UTC del 28 oct
(00:30 del 29 en Madrid) llegaba por Telegram como «28/10/2025»; la app la
muestra en hora local. Ahora se pasa a Europe/Madrid antes de formatear.
"""

from datetime import UTC, datetime

import pytest

from app.services.notification_service import NotificationService


def _payload(event_date, **extra):
    return {
        "severity": "high", "title": "t", "message": "m", "company_name": "Visa", "ticker": "V",
        "type": "news_material_update", "source_headline": "V 8-K filed", "event_date": event_date,
        "event_date_source": "source", "source_url": "https://www.sec.gov/x", "alert_id": 1, "company_id": 1,
        **extra,
    }


@pytest.mark.parametrize("language", [None, "en"])
def test_late_utc_evening_is_next_day_in_madrid(language):
    extra = {"language": language} if language else {}
    text = NotificationService._telegram_text(_payload(datetime(2025, 10, 28, 23, 30, tzinfo=UTC), **extra))
    assert text.startswith("Visa · 8-K · 29/10/2025")


def test_naive_datetime_is_read_as_utc():
    text = NotificationService._telegram_text(_payload(datetime(2025, 10, 28, 23, 30)))
    assert text.startswith("Visa · 8-K · 29/10/2025")


def test_midday_keeps_its_day():
    text = NotificationService._telegram_text(_payload(datetime(2025, 10, 28, 12, 0, tzinfo=UTC)))
    assert text.startswith("Visa · 8-K · 28/10/2025")
