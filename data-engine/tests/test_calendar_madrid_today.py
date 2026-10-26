"""El rango por defecto del calendario usa el dia de Madrid, no el del contenedor (UTC)."""

from datetime import UTC, date, datetime

from app.api.routes import calendar as calendar_route


def test_madrid_today_crosses_midnight_before_utc():
    # 23:30 UTC del 25-oct-2026 ya es 00:30 del 26 en Madrid (CET, UTC+1).
    assert calendar_route._madrid_today(datetime(2026, 10, 25, 23, 30, tzinfo=UTC)) == date(2026, 10, 26)
    # Verano (CEST, UTC+2): 22:30 UTC del 10-jul ya es el 11 en Madrid.
    assert calendar_route._madrid_today(datetime(2026, 7, 10, 22, 30, tzinfo=UTC)) == date(2026, 7, 11)
    # Mediodia: mismo dia.
    assert calendar_route._madrid_today(datetime(2026, 7, 10, 12, 0, tzinfo=UTC)) == date(2026, 7, 10)


def test_default_range_starts_on_madrid_day(monkeypatch):
    monkeypatch.setattr(calendar_route, "_madrid_today", lambda now=None: date(2026, 10, 26))
    start, end = calendar_route._resolve_range(None, None)
    assert start == date(2026, 10, 26) and end == date(2026, 11, 2)
