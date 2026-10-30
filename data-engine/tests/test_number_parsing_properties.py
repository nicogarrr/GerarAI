"""Property tests for ``number_parsing``: what a locale formats, the parser reads back.

Derived by hand from the module's rules: en-US groups with "," and decimals
with "."; es-ES groups with "." and decimals with ","; accounting parentheses
and a leading minus are the same negative. Cases are restricted to the
unambiguous shapes the docstring promises (two decimals, or grouped integers).
"""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.number_parsing import (
    find_number_tokens,
    find_number_tokens_with_units,
    parse_localized_number,
)

_cents = st.integers(min_value=-(10**14), max_value=10**14)


def _en(value: Decimal) -> str:
    return f"{value:,.2f}"


def _es(value: Decimal) -> str:
    return _en(value).replace(",", "_").replace(".", ",").replace("_", ".")


@settings(max_examples=300, deadline=None)
@given(_cents)
def test_two_decimal_amounts_round_trip_in_both_locales(cents):
    value = Decimal(cents) / 100
    for text in (_en(value), _es(value)):
        assert parse_localized_number(text) == (value, False), text


@settings(max_examples=300, deadline=None)
@given(st.integers(min_value=1000, max_value=10**15))
def test_grouped_integers_round_trip_in_both_locales(number):
    en = f"{number:,}"
    es = en.replace(",", ".")
    nbsp = en.replace(",", "\u00a0")
    for text in (en, es, nbsp):
        assert parse_localized_number(text) == (Decimal(number), False), text


@settings(max_examples=200, deadline=None)
@given(st.integers(min_value=1, max_value=10**12))
def test_parentheses_and_minus_are_the_same_negative(cents):
    value = Decimal(cents) / 100
    plain = _es(value)
    assert parse_localized_number(f"({plain})") == (-value, True)
    assert parse_localized_number(f"-{plain}") == (-value, False)
    assert parse_localized_number(f"\u2212{plain}") == (-value, False)


@settings(max_examples=200, deadline=None)
@given(_cents, _cents)
def test_two_figures_in_a_spanish_sentence_stay_two_tokens(a, b):
    first, second = _es(Decimal(a) / 100), _es(Decimal(b) / 100)
    tokens = find_number_tokens(f"ventas de {first} millones y margen de {second} %")
    assert [parse_localized_number(t)[0] for t in tokens] == [Decimal(a) / 100, Decimal(b) / 100]


def test_unit_window_never_borrows_the_next_figure():
    pairs = find_number_tokens_with_units("1.234,5 millones y 12,5 %", window=40)
    assert pairs == [("1.234,5", " millones y"), ("12,5", " %")]


def test_window_is_capped():
    assert find_number_tokens_with_units("7 " + "x" * 50, window=5) == [("7", " xxxx")]


def test_not_numbers():
    for text in (None, "", "   ", "abc", "1e5", "NaN", "()", "-", "+", "1-2"):
        assert parse_localized_number(text) is None, text
    assert find_number_tokens(None) == []
    assert find_number_tokens_with_units(None) == []


def test_zero_forms():
    assert parse_localized_number("0") == (Decimal(0), False)
    assert parse_localized_number("0,250") == (Decimal("0.250"), False)
    assert parse_localized_number("0.250") == (Decimal("0.250"), False)
    assert parse_localized_number("(0)") == (Decimal(0), True)
