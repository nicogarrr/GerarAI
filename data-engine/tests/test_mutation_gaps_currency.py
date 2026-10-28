"""Currency/FX asserts that mutation testing (mutmut) showed were missing.

``resolve_fx`` (the point-in-time FX behind every converted fair value and
margin of safety) and ``scale_per_share_outputs`` (the conversion of the
per-share values back to the listing currency) had no direct test: most of
their mutants survived. See docs/testing/mutation.md.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.valuation.currency import (
    FX_MAX_AGE_DAYS,
    FxQuote,
    fact_currency,
    listing_currency,
    listing_quote_unit,
    resolve_fx,
    scale_per_share_outputs,
)

ON = date(2026, 9, 30)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _rate(db, base, quote, rate, rate_date, source="ecb"):
    # quote amount x rate = base amount
    db.add(
        FXRate(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal(str(rate)),
            rate_date=rate_date,
            source=source,
        )
    )
    db.commit()


# --- resolve_fx ----------------------------------------------------------------


def test_same_currency_is_identity_case_insensitive(db):
    q = resolve_fx(db, "usd", "USD", ON)
    assert q == FxQuote("USD", "USD", 1.0, None, None, ("USD",))


def test_direct_rate_with_provenance(db):
    _rate(db, "USD", "CNY", "0.14", date(2026, 9, 29), "ecb")
    q = resolve_fx(db, "CNY", "USD", ON)
    assert q.rate == pytest.approx(0.14)
    assert q.rate_date == date(2026, 9, 29)
    assert q.source == "ecb"
    assert q.path == ("CNY", "USD")
    assert (q.from_currency, q.to_currency) == ("CNY", "USD")


def test_freshness_boundary_is_inclusive(db):
    _rate(db, "USD", "CNY", "0.14", date(2026, 9, 30 - FX_MAX_AGE_DAYS))
    assert resolve_fx(db, "CNY", "USD", ON) is not None
    assert resolve_fx(db, "CNY", "USD", date(2026, 10, 1)) is None
    assert resolve_fx(db, "CNY", "USD", ON, max_age_days=FX_MAX_AGE_DAYS - 1) is None


def test_future_rate_is_never_used(db):
    _rate(db, "USD", "CNY", "0.14", date(2026, 10, 1))
    assert resolve_fx(db, "CNY", "USD", ON) is None


def test_cross_rate_through_pivot_multiplies_and_keeps_oldest_date(db):
    _rate(db, "EUR", "CNY", "0.125", date(2026, 9, 27), "ecb")
    _rate(db, "USD", "EUR", "1.08", date(2026, 9, 29), "ecb")
    q = resolve_fx(db, "CNY", "USD", ON)
    assert q.rate == pytest.approx(0.125 * 1.08)
    assert q.rate_date == date(2026, 9, 27)
    assert q.source == "ecb"
    assert q.path == ("CNY", "EUR", "USD")


def test_cross_rate_names_both_sources_when_they_differ(db):
    _rate(db, "EUR", "CNY", "0.125", date(2026, 9, 29), "ecb")
    _rate(db, "USD", "EUR", "1.08", date(2026, 9, 29), "manual")
    assert resolve_fx(db, "CNY", "USD", ON).source == "ecb+manual"


def test_stale_direct_rate_falls_back_to_fresh_cross(db):
    _rate(db, "USD", "CNY", "0.50", date(2026, 1, 1))  # stale, wrong
    _rate(db, "EUR", "CNY", "0.125", date(2026, 9, 29))
    _rate(db, "USD", "EUR", "1.08", date(2026, 9, 29))
    q = resolve_fx(db, "CNY", "USD", ON)
    assert q.path == ("CNY", "EUR", "USD")
    assert q.rate == pytest.approx(0.135)


def test_cross_needs_both_legs_fresh(db):
    _rate(db, "EUR", "CNY", "0.125", date(2026, 1, 1))
    _rate(db, "USD", "EUR", "1.08", date(2026, 9, 29))
    assert resolve_fx(db, "CNY", "USD", ON) is None


def test_second_pivot_is_tried(db):
    _rate(db, "USD", "CNY", "0.14", date(2026, 9, 29))
    _rate(db, "HKD", "USD", "7.8", date(2026, 9, 29))
    q = resolve_fx(db, "CNY", "HKD", ON)
    assert q.path == ("CNY", "USD", "HKD")
    assert q.rate == pytest.approx(0.14 * 7.8)


def test_pivot_equal_to_an_endpoint_is_skipped(db):
    # EUR->USD has no direct rate; EUR is itself a pivot and must not be used
    # as EUR->EUR->USD (that would be a fake 1.0 leg).
    assert resolve_fx(db, "EUR", "USD", ON) is None


def test_zero_rate_is_rejected(db):
    _rate(db, "USD", "CNY", "0", date(2026, 9, 29))
    assert resolve_fx(db, "CNY", "USD", ON) is None


def test_as_trace_shape(db):
    _rate(db, "USD", "CNY", "0.14", date(2026, 9, 29), "ecb")
    assert resolve_fx(db, "CNY", "USD", ON).as_trace() == {
        "from": "CNY",
        "to": "USD",
        "rate": pytest.approx(0.14),
        "rate_date": "2026-09-29",
        "source": "ecb",
        "path": ["CNY", "USD"],
    }
    assert resolve_fx(db, "USD", "USD", ON).as_trace()["rate_date"] is None


# --- scale_per_share_outputs -------------------------------------------------


def test_scale_per_share_outputs_scales_every_per_share_amount_and_nothing_else():
    result = {
        "bear_value": 10.0,
        "base_value": 20.0,
        "bull_value": 30.0,
        "expected_value": 25,
        "margin_of_safety": 0.25,
        "wacc": 0.09,
        "implied_growth": 0.03,
        "listed_share_values": {"A": 10.0, "B": None},
        "sensitivity": {
            "rows": [{"values": [{"value_per_share": 5.0, "wacc": 0.08}, {"other": 1.0}]}, "junk"]
        },
        "reverse_dcf": {"market_price": 8.0, "solved_value_per_share": 9.0, "implied_growth": 0.04},
        "scenarios": {"bull": {"value_per_share": 40.0, "probability": 0.25}, "x": "y"},
        "flag": True,
        "missing": None,
    }
    scale_per_share_outputs(result, 2.0)
    assert result["bear_value"] == 20.0
    assert result["base_value"] == 40.0
    assert result["bull_value"] == 60.0
    assert result["expected_value"] == 50
    assert result["margin_of_safety"] == 0.25
    assert result["wacc"] == 0.09
    assert result["implied_growth"] == 0.03
    assert result["listed_share_values"] == {"A": 20.0, "B": None}
    cells = result["sensitivity"]["rows"][0]["values"]
    assert cells[0] == {"value_per_share": 10.0, "wacc": 0.08}
    assert cells[1] == {"other": 1.0}
    assert result["reverse_dcf"] == {
        "market_price": 16.0,
        "solved_value_per_share": 18.0,
        "implied_growth": 0.04,
    }
    assert result["scenarios"]["bull"] == {"value_per_share": 80.0, "probability": 0.25}
    assert result["flag"] is True  # bools are not amounts
    assert result["missing"] is None


def test_scale_per_share_outputs_tolerates_absent_sections():
    result = {"base_value": None, "sensitivity": {"rows": None}, "reverse_dcf": {}, "scenarios": None}
    scale_per_share_outputs(result, 3.0)
    assert result == {"base_value": None, "sensitivity": {"rows": None}, "reverse_dcf": {}, "scenarios": None}


# --- fact_currency / listing helpers ------------------------------------------


@pytest.mark.parametrize(
    "unit,expected",
    [
        ("CNY", "CNY"),
        ("usd/share", "USD"),
        ("USD/shares/day", "USD"),
        ("GBp", "GBP"),
        ("shares", None),
        ("pure", None),
        ("Percent", None),
        ("", None),
        (None, None),
        ("USDX", None),
        ("U1D", None),
    ],
)
def test_fact_currency(unit, expected):
    assert fact_currency(unit) == expected


def test_listing_quote_unit_suffix_uses_last_dot():
    # A share-class ticker on London: BT.A.L quotes in pence, not "A.L".
    assert listing_quote_unit("BT.A.L", "USD") == "GBX"
    assert listing_currency("BT.A.L") == "GBP"


def test_listing_quote_unit_declared_minor_unit_any_case_wins():
    assert listing_quote_unit("XYZ", "gbx") == "gbx"
    assert listing_quote_unit("SAN.MC", "GBp") == "GBp"


def test_listing_quote_unit_unknown_suffix_uses_declared_currency():
    assert listing_quote_unit("FOO.ZZ", "eur") == "EUR"
    assert listing_quote_unit("FOO", "cad") == "CAD"
    assert listing_quote_unit(None, None) == "USD"
    assert listing_currency(None) == "USD"
