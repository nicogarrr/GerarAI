"""Double-taxation (art. 80 LIRPF) asserts that mutation testing showed were missing.

Turning any ``continue`` of the per-block loop into ``break`` (one skipped
block silently dropping every later country) and overwriting instead of
summing the totals survived the suite: every existing test used one block.
See docs/testing/mutation.md.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_irpf_filing import build_double_taxation


def _div(ticker, gross, withheld, **extra):
    row = {
        "ticker": ticker,
        "dividends_base": gross,
        "withholding_base": withheld,
        "missing_fx": False,
        "payments": [],
    }
    row.update(extra)
    return row


def test_multiple_blocks_skipped_ones_do_not_drop_later_countries_and_totals_add_up():
    dividends = [
        _div("FXLESS", 50.0, 10.0, missing_fx=True),  # manual review, skipped
        _div("EMPTY", 0, 0),  # nothing to do, skipped
        _div("NOCTRY", 40.0, 6.0),  # unknown country, skipped
        _div("SAN", 100.0, 19.0),  # Spain: domestic, 0597
        _div("BBVA", 50.0, 9.5),  # Spain again: must add up
        _div("KO", 100.0, 30.0),  # US 15 % cap
        _div("JNJ", 100.0, 15.0),  # US exactly at cap
        _div("BN", 200.0, 50.0),  # Canada 15 % cap
    ]
    countries = {
        "FXLESS": "US",
        "EMPTY": "US",
        "NOCTRY": None,
        "SAN": "ES",
        "BBVA": "ES",
        "KO": "US",
        "JNJ": "US",
        "BN": "CA",
    }
    result = build_double_taxation(dividends, countries, 2025, tme=Decimal("0.19"))
    by_country = {row["country"]: row for row in result["countries"]}
    assert set(by_country) == {"US", "CA"}
    us, ca = by_country["US"], by_country["CA"]
    assert us["gross_base"] == 200.0
    assert us["withheld_base"] == 45.0
    assert us["treaty_cap_base"] == 30.0  # 15 % x 100 + 15 % x 100
    assert us["excess_reclaimable_base"] == 15.0  # only KO is over the cap
    assert us["deduction_base"] == 30.0
    assert ca["deduction_base"] == 30.0
    # Blocks under manual review make the total partial: never a final number.
    assert result["partial"] is True
    assert result["total_deduction_base"] is None
    # A block of unknown country might be Spanish: the 0597 total is not verifiable.
    assert result["spanish_withholding_base"]["amount"] is None
    tickers_in_review = {row["ticker"] for row in result["manual_review"]}
    assert {"FXLESS", "NOCTRY"} <= tickers_in_review
    assert "EMPTY" not in tickers_in_review


def test_withholding_exactly_at_cap_has_no_excess():
    result = build_double_taxation([_div("JNJ", 100.0, 15.0)], {"JNJ": "US"}, 2025, tme=Decimal("0.19"))
    (us,) = result["countries"]
    assert us["excess_reclaimable_base"] == 0.0
    assert us["deduction_base"] == 15.0


def test_zero_withholding_country_gets_no_row_and_tme_status_is_named():
    result = build_double_taxation(
        [_div("ZERO", 100.0, 0.0), _div("KO", 100.0, 30.0)],
        {"ZERO": "US", "KO": "US"},
        2025,
        tme=Decimal("0.10"),
    )
    (us,) = result["countries"]
    # tme 10 % of gross (200) = 20 < cap 15? no: cap = 15 % x 100 (KO) + min(0, 15) = 15
    assert us["deduction_base"] == 15.0
    assert us["status"] == "calculada_con_tme_manual"
    assert result["basis"] == "art-80-lirpf"


def test_total_deduction_sums_every_country_when_nothing_is_pending():
    dividends = [
        _div("EMPTY", 0, 0),
        _div("KO", 100.0, 30.0),
        _div("SAN", 100.0, 19.0),
        _div("BBVA", 50.0, 9.5),
        _div("BN", 200.0, 50.0),
    ]
    countries = {"EMPTY": "US", "KO": "US", "SAN": "ES", "BBVA": "ES", "BN": "CA"}
    result = build_double_taxation(dividends, countries, 2025, tme=Decimal("0.19"))
    assert result["partial"] is False
    assert result["total_deduction_base"] == 45.0  # US 15 + CA 30
    assert result["spanish_withholding_base"]["amount"] == 28.5
    assert result["manual_review"] == []
