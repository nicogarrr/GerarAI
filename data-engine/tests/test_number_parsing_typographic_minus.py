"""Typographic minus signs (U+2212 and its variants) keep the sign.

PDF, ESEF and CNMV text writes negatives with U+2212, not the ASCII hyphen.
On main "−3,2 %" parsed as +3,2, so a KPI the model reported with the wrong
sign (+0,032 organic growth for a document that says −3,2 %) was grounded
by the quote, and the correct −0,032 was rejected.
"""

from decimal import Decimal

import pytest

from app.services.kpi_extraction_service import KPIExtractionService, _value_token
from app.services.number_parsing import (
    find_number_tokens,
    find_number_tokens_with_units,
    parse_localized_number,
)


@pytest.mark.parametrize("minus", ["\u2212", "\ufe63", "\uff0d"])
def test_parse_keeps_typographic_minus(minus):
    assert parse_localized_number(f"{minus}1,5") == (Decimal("-1.5"), False)
    assert parse_localized_number(f"{minus}1.234,56") == (Decimal("-1234.56"), False)


def test_ascii_forms_unchanged():
    assert parse_localized_number("-1,5") == (Decimal("-1.5"), False)
    assert parse_localized_number("(1.250)") == (Decimal("-1250"), True)
    assert parse_localized_number("1,5") == (Decimal("1.5"), False)


def test_tokens_keep_typographic_minus_and_unit_window():
    assert find_number_tokens("caída orgánica del \u22123,2 % en 2024") == ["-3,2", "2024"]
    pairs = find_number_tokens_with_units("pérdida de \u22121.234,5 millones")
    assert pairs == [("-1.234,5", " millones")]


def test_value_token_keeps_sign():
    assert _value_token("\u22123,2%") == "-3,2"


def test_grounding_rejects_flipped_sign():
    figures = KPIExtractionService._quote_figures("El crecimiento orgánico fue del \u22123,2 %")
    assert KPIExtractionService._value_supported(Decimal("-0.032"), figures, "decimal")
    assert not KPIExtractionService._value_supported(Decimal("0.032"), figures, "decimal")
