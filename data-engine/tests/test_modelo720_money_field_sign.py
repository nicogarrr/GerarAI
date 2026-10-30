"""Modelo 720: signo del importe tras redondear a céntimos (sin cero negativo)."""

from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.tax_modelo720_file import _money_field


def test_negative_amount_that_rounds_to_zero_has_no_sign():
    # -0,004 € se escribe 0,00: el signo "N" con importe cero es un cero negativo.
    assert _money_field(Decimal("-0.004")) == (" ", "0" * 14)
    assert _money_field(Decimal("-0.005")) == ("N", "0" * 13 + "1")


def test_zero_and_positive_have_blank_sign():
    assert _money_field(Decimal("0")) == (" ", "0" * 14)
    assert _money_field(Decimal("1234.565")) == (" ", "00000000123457")


@settings(max_examples=300, deadline=None, derandomize=True)
@given(
    st.decimals(
        min_value=Decimal("-999999999999.99"),
        max_value=Decimal("999999999999.99"),
        places=4,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_field_is_cents_half_up_and_sign_only_when_nonzero(value):
    sign, digits = _money_field(value)
    cents = int((abs(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    assert len(digits) == 14
    assert int(digits) == cents
    assert sign == ("N" if value < 0 and cents else " ")
