"""A hyphen between two digits is a range or date separator, not a minus.

On main "crecimiento del 5-7 %" tokenised as "5" and "-7", and "2024-03-31"
as "2024", "-03", "-31": the KPI grounding then vouched for a reported -0,07
(or -31) that the quote never states, and could not ground the +7 % it does.
"""

from decimal import Decimal

from app.services.kpi_extraction_service import KPIExtractionService
from app.services.number_parsing import find_number_tokens, find_number_tokens_with_units


def test_range_hyphen_is_not_a_minus():
    assert find_number_tokens("crecimiento del 5-7 %") == ["5", "7"]
    assert find_number_tokens("ejercicio 2023-2024") == ["2023", "2024"]
    assert find_number_tokens("cierre 2024-03-31") == ["2024", "03", "31"]


def test_real_signs_are_kept():
    assert find_number_tokens("variación de -3,2 % y +1,5 %") == ["-3,2", "+1,5"]
    assert find_number_tokens("resultado (1.250) y -5") == ["(1.250)", "-5"]
    assert find_number_tokens("EBIT: -12,5 millones") == ["-12,5"]


def test_range_upper_bound_keeps_its_unit_and_sign():
    assert find_number_tokens_with_units("del 5-7 % anual")[-1] == ("7", " % anual")


def test_grounding_of_a_guidance_range():
    figures = KPIExtractionService._quote_figures("Guía de crecimiento orgánico del 5-7 %")
    assert KPIExtractionService._value_supported(Decimal("0.07"), figures, "decimal")
    assert not KPIExtractionService._value_supported(Decimal("-0.07"), figures, "decimal")
    dated = KPIExtractionService._quote_figures("a 2024-03-31")
    assert not KPIExtractionService._value_supported(Decimal("-31"), dated, "count")
