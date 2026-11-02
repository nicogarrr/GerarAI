"""Helper is_market_open_day: festivos reales de XMAD, XNYS y XLON."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services.market_calendar import is_market_open_day


@pytest.mark.parametrize(
    ("exchange", "day"),
    [
        # Madrid: Año Nuevo, Viernes Santo, Lunes de Pascua, 1 de mayo, Navidad, San Esteban.
        ("XMAD", date(2025, 1, 1)),
        ("XMAD", date(2025, 4, 18)),
        ("XMAD", date(2025, 4, 21)),
        ("XMAD", date(2025, 5, 1)),
        ("XMAD", date(2025, 12, 25)),
        ("XMAD", date(2025, 12, 26)),
        # Nueva York: Viernes Santo, 4 de julio, Acción de Gracias, Navidad.
        ("XNYS", date(2025, 4, 18)),
        ("XNYS", date(2025, 7, 4)),
        ("XNYS", date(2025, 11, 27)),
        ("XNYS", date(2025, 12, 25)),
        # Londres: Lunes de Pascua, bank holidays de mayo y agosto, Boxing Day.
        ("XLON", date(2025, 4, 21)),
        ("XLON", date(2025, 5, 5)),
        ("XLON", date(2025, 8, 25)),
        ("XLON", date(2025, 12, 26)),
        # Fin de semana en las tres.
        ("XMAD", date(2025, 11, 1)),
        ("XNYS", date(2025, 11, 2)),
        ("XLON", date(2025, 11, 1)),
    ],
)
def test_closed_days(exchange: str, day: date) -> None:
    assert is_market_open_day(exchange, day) is False


@pytest.mark.parametrize(
    ("exchange", "day"),
    [
        ("XMAD", date(2025, 1, 6)),  # Reyes: la Bolsa de Madrid abre.
        ("XMAD", date(2025, 7, 4)),
        ("XNYS", date(2025, 4, 21)),  # Lunes de Pascua: Nueva York abre.
        ("XNYS", date(2025, 12, 26)),
        ("XLON", date(2025, 7, 4)),
        ("XLON", date(2025, 11, 27)),
        ("XNYS", date(2026, 11, 2)),
    ],
)
def test_open_days(exchange: str, day: date) -> None:
    assert is_market_open_day(exchange, day) is True


def test_same_holiday_differs_by_exchange() -> None:
    day = date(2025, 7, 4)
    assert is_market_open_day("XNYS", day) is False
    assert is_market_open_day("XMAD", day) is True
    assert is_market_open_day("XLON", day) is True


def test_code_is_case_insensitive_and_datetime_uses_its_date() -> None:
    assert is_market_open_day(" xnys ", datetime(2025, 7, 4, 15, 30)) is False
    assert is_market_open_day("xlon", datetime(2025, 7, 4, 23, 59)) is True


@pytest.mark.parametrize("exchange", ["", "NASDAQ", "XETR", "BME"])
def test_unknown_exchange_raises(exchange: str) -> None:
    with pytest.raises(ValueError, match="no soportada"):
        is_market_open_day(exchange, date(2025, 7, 7))


@pytest.mark.parametrize("day", [date(1999, 12, 31), date(date.today().year + 3, 6, 15)])
def test_out_of_range_raises_instead_of_guessing(day: date) -> None:
    with pytest.raises(ValueError, match="fuera del calendario"):
        is_market_open_day("XMAD", day)
