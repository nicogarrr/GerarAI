"""Asserts that mutation testing (mutmut) showed were missing.

Each test pins a branch whose mutants survived the existing suite: the code
could be broken there and no test would notice. See docs/testing/mutation.md.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.units import is_from_percent, to_fraction
from app.models import Company
from app.services.fx_attribution import split_unrealized_pnl
from app.services.price_units import price_in_currency


def _company(ticker: str, currency: str | None):
    # Real (unsaved) ORM row: price_in_currency reads .ticker and .currency.
    return Company(ticker=ticker, currency=currency)


# --- price_in_currency: legacy rows without quote_currency -------------------


def test_legacy_row_on_major_unit_listing_is_kept_when_listing_matches_target():
    value = price_in_currency(
        Decimal("123.45"),
        quote_currency=None,
        target_currency="USD",
        company=_company("AAPL", "USD"),
    )
    assert value == Decimal("123.45")


def test_legacy_row_on_euro_listing_uses_ticker_suffix_not_company_default():
    # Enrichment creates companies with currency USD by default; the .MC
    # suffix says the listing quotes in EUR, so a USD target is refused.
    assert (
        price_in_currency(
            Decimal("10"),
            quote_currency=None,
            target_currency="USD",
            company=_company("SAN.MC", "USD"),
        )
        is None
    )
    assert price_in_currency(
        Decimal("10"),
        quote_currency=None,
        target_currency="EUR",
        company=_company("SAN.MC", "USD"),
    ) == Decimal("10")


def test_legacy_row_on_pence_listing_is_never_guessed():
    # A .L listing quotes in pence: a legacy row with no unit could be pence
    # or pounds, so it must not be converted either way (x100 risk).
    for target in ("GBP", "GBp", "GBX"):
        assert (
            price_in_currency(
                Decimal("4255"),
                quote_currency=None,
                target_currency=target,
                company=_company("CGEO.L", "GBP"),
            )
            is None
        )


def test_legacy_row_with_declared_minor_currency_is_refused():
    assert (
        price_in_currency(
            Decimal("4255"),
            quote_currency="",
            target_currency="GBP",
            company=_company("CGEO", "GBX"),
        )
        is None
    )


def test_legacy_row_is_refused_when_target_is_a_minor_unit():
    assert (
        price_in_currency(
            Decimal("1"),
            quote_currency=None,
            target_currency="GBp",
            company=_company("AAPL", "USD"),
        )
        is None
    )


def test_legacy_row_in_other_major_currency_is_refused():
    assert (
        price_in_currency(
            Decimal("100"),
            quote_currency=None,
            target_currency="EUR",
            company=_company("AAPL", "USD"),
        )
        is None
    )


def test_explicit_pence_quote_converts_to_pounds_exactly_once():
    assert price_in_currency(
        Decimal("4255"),
        quote_currency="GBp",
        target_currency="GBP",
        company=_company("CGEO.L", "GBP"),
    ) == Decimal("42.55")


def test_explicit_quote_in_other_currency_is_refused_not_fx_converted():
    assert (
        price_in_currency(
            Decimal("100"),
            quote_currency="USD",
            target_currency="EUR",
            company=_company("SAN.MC", "EUR"),
        )
        is None
    )


# --- to_fraction / is_from_percent -------------------------------------------


@pytest.mark.parametrize("raw", [4.25, "4.25", 4])
def test_to_fraction_accepts_non_decimal_inputs(raw):
    value, method = to_fraction(raw, "percent")
    assert isinstance(value, Decimal)
    assert value == Decimal(str(raw)) / Decimal("100")
    assert method == "explicit_percent"


def test_to_fraction_float_input_is_converted_via_str_not_binary_float():
    value, _ = to_fraction(0.1, "fraction")
    assert value == Decimal("0.1")


def test_to_fraction_bps_method_name():
    value, method = to_fraction(Decimal("25"), "bps")
    assert value == Decimal("0.0025")
    assert method == "explicit_bps"
    assert is_from_percent(method) is True


def test_to_fraction_heuristic_boundaries():
    # exactly 1 stays a fraction (100 %): the heuristic is 1 < x <= 100.
    assert to_fraction(Decimal("1")) == (Decimal("1"), "heuristic_fraction")
    # exactly 100 is a percentage (100 % = 1).
    assert to_fraction(Decimal("100")) == (Decimal("1"), "heuristic_percent")
    assert to_fraction(Decimal("100.01")) == (Decimal("100.01"), "heuristic_fraction")
    assert to_fraction(Decimal("1.01"))[1] == "heuristic_percent"


def test_to_fraction_unknown_unit_falls_back_to_heuristic():
    assert to_fraction(Decimal("4.25"), "USD") == (Decimal("0.0425"), "heuristic_percent")
    assert to_fraction(Decimal("0.0425"), None) == (Decimal("0.0425"), "heuristic_fraction")


@pytest.mark.parametrize(
    "method,expected",
    [
        ("explicit_percent", True),
        ("explicit_bps", True),
        ("heuristic_percent", True),
        ("explicit_fraction", False),
        ("heuristic_fraction", False),
    ],
)
def test_is_from_percent(method, expected):
    assert is_from_percent(method) is expected


# --- split_unrealized_pnl ------------------------------------------------------


def test_split_unrealized_pnl_zero_rate_returns_unknown():
    assert split_unrealized_pnl(
        unrealized_native=Decimal("10"),
        unrealized_base=Decimal("9"),
        fx_rate_now=0,
    ) == (None, None)


def test_split_unrealized_pnl_sums_to_base():
    price, fx = split_unrealized_pnl(
        unrealized_native=Decimal("10"),
        unrealized_base=Decimal("12"),
        fx_rate_now=Decimal("0.9"),
    )
    assert price == pytest.approx(9.0)
    assert fx == pytest.approx(3.0)
