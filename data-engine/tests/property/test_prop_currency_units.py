"""Subunidades (GBp/ZAc/ILa): /100 exactamente una vez por cualquier camino."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from app.services.connectors import ecb_history
from app.services.portfolio_fx_service import PortfolioFXService, currency_key
from app.services.price_units import price_in_currency
from app.valuation.currency import (
    MINOR_UNITS,
    canonical_currency_code,
    normalize_currency,
    to_major_units,
)

MINOR = sorted(MINOR_UNITS)
MAJOR = ["EUR", "USD", "GBP", "ZAR", "ILS", "CHF", "JPY"]
code = st.sampled_from(MINOR + MAJOR + [c.lower() for c in MAJOR] + ["gbx", "zac", "ila", " GBp ", ""])
amount = st.integers(min_value=-10**9, max_value=10**9).map(lambda c: Decimal(c) / 100)


@given(code)
def test_canonical_code_keeps_the_unit(raw):
    assert normalize_currency(canonical_currency_code(raw)) == normalize_currency(raw)
    # idempotente: guardar dos veces no vuelve a dividir
    assert canonical_currency_code(canonical_currency_code(raw)) == canonical_currency_code(raw)


@given(st.sampled_from(MINOR), amount)
def test_minor_to_major_divides_by_100_exactly_once(raw, value):
    major, divisor = normalize_currency(raw)
    assert divisor == 100
    converted = to_major_units(value, raw)
    assert converted is not None and converted.currency == major
    assert abs(Decimal(str(converted.value)) - value / 100) <= abs(value) * Decimal("1e-15") + Decimal("1e-12")
    # el resultado ya esta en unidad principal: convertirlo otra vez no cambia nada
    again = to_major_units(converted.value, converted.currency)
    assert again is not None and again.value == converted.value


@given(st.sampled_from(MINOR), amount)
def test_price_in_currency_round_trip(raw, value):
    major, _ = normalize_currency(raw)
    company = SimpleNamespace(ticker="X.L", currency=major)
    in_major = price_in_currency(value, quote_currency=raw, target_currency=major, company=company)
    assert in_major == value / 100
    back = price_in_currency(in_major, quote_currency=major, target_currency=raw, company=company)
    assert back == value


@given(code, code)
def test_currency_key_is_injective_on_units(a, b):
    if normalize_currency(a) != normalize_currency(b):
        assert currency_key(a) != currency_key(b)


@given(st.sampled_from(MINOR))
def test_ecb_backfill_derives_every_minor_unit_like_the_valuation_layer(raw):
    """El backfill BCE debe reconocer las mismas subunidades que normalize_currency:
    si no, pide al BCE un codigo inexistente y el informe fiscal queda sin tipo."""
    normalized = ecb_history._normalize(raw)
    major, divisor = ecb_history.MINOR_UNITS.get(normalized, (normalized, Decimal("1")))
    assert (major, int(divisor)) == normalize_currency(raw)


@given(
    st.sampled_from(MINOR + MAJOR),
    st.sampled_from(["EUR", "USD", "GBP"]),
    st.lists(st.tuples(st.integers(0, 40), st.integers(1, 10_000)), min_size=1, max_size=6),
    st.integers(0, 45),
)
def test_table_rate_has_the_subunit_factor_exactly_once(quote, base, rows, as_of_offset):
    start = date(2025, 1, 1)
    q_major, q_div = normalize_currency(quote)
    table = {}
    if q_major != base:
        table[(base, q_major)] = sorted({(start + timedelta(days=d), Decimal(r) / 1000) for d, r in rows})
    as_of = start + timedelta(days=as_of_offset)
    rate = PortfolioFXService.rate_from_table(table, quote_currency=quote, base_currency=base, as_of=as_of)
    major_rate = PortfolioFXService.rate_from_table(table, quote_currency=q_major, base_currency=base, as_of=as_of)
    if major_rate is None:
        assert rate is None
    else:
        assert rate == major_rate / q_div
