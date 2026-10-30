"""Un separador unico que no puede ser de miles es decimal (en-US y es-ES).

Un grupo de miles tiene exactamente 3 cifras y el primero de 1 a 3, asi que
"1,2345" (tipo de cambio es-ES) y "1234,567" (es-ES sin agrupar) se leian como
12345 y 1234567: errores x10.000 y x1.000.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.number_parsing import parse_localized_number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,2345", Decimal("1.2345")),  # tipo de cambio EUR/USD es-ES
        ("12,3456", Decimal("12.3456")),  # precio con 4 decimales es-ES
        ("-1,0845", Decimal("-1.0845")),
        ("(1,2345)", Decimal("-1.2345")),
        ("1234,567", Decimal("1234.567")),  # es-ES sin agrupar, 3 decimales
        ("12345,678", Decimal("12345.678")),
        ("1234.567", Decimal("1234.567")),  # en-US sin agrupar, 3 decimales
        ("1 234,5678", Decimal("1234.5678")),
    ],
)
def test_single_separator_that_cannot_group_is_decimal(raw, expected):
    parsed = parse_localized_number(raw)
    assert parsed is not None, raw
    assert parsed[0] == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234", Decimal("1234")),
        ("1.250", Decimal("1250")),
        ("(1.250)", Decimal("-1250")),
        ("123,456", Decimal("123456")),
        ("1.234.567", Decimal("1234567")),
        ("1,234,567", Decimal("1234567")),
        ("0,250", Decimal("0.250")),
    ],
)
def test_real_thousands_grouping_is_unchanged(raw, expected):
    parsed = parse_localized_number(raw)
    assert parsed is not None, raw
    assert parsed[0] == expected


def _group(integer: str, sep: str) -> str:
    head, rest = integer[: len(integer) % 3 or 3], integer[len(integer) % 3 or 3 :]
    return sep.join([head] + [rest[i : i + 3] for i in range(0, len(rest), 3)])


@settings(max_examples=400, deadline=None)
@given(
    integer=st.integers(min_value=0, max_value=10**9),
    decimals=st.integers(min_value=1, max_value=6),
    frac=st.integers(min_value=0, max_value=999_999),
    locale=st.sampled_from(["es", "en"]),
    grouped=st.booleans(),
)
def test_formatted_number_round_trips(integer, decimals, frac, locale, grouped):
    fraction = str(frac % 10**decimals).zfill(decimals)
    thousands, decimal_sep = (".", ",") if locale == "es" else (",", ".")
    integer_text = _group(str(integer), thousands) if grouped else str(integer)
    text = f"{integer_text}{decimal_sep}{fraction}"
    single_separator = thousands not in integer_text
    # Unica ambiguedad documentada: un separador unico, 3 decimales y parte
    # entera de 1-3 cifras distinta de 0 ("1,234") se lee como miles.
    if single_separator and decimals == 3 and 0 < integer < 1000:
        return
    parsed = parse_localized_number(text)
    assert parsed is not None, text
    assert parsed[0] == Decimal(f"{integer}.{fraction}"), text
