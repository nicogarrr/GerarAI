"""Regulated-asset (DASR) engine: the (E) identity, audited term by term.

The formula tests check hand-computed values, not the module's own output. The
identity under test is

    V = B + (allowed_roe - ke) * B / (ke - g)

which at ``g = 0`` collapses to ``B * allowed_roe / ke`` — the form the utility
literature quotes — and the dividend cross-check is

    V = B * allowed_roe * payout * (1 + g) / (ke - g)

equal to (E) only at ``payout = (allowed_roe - g) / (allowed_roe * (1 + g))``.

Refusals covered, each asserting the named ``missing_inputs`` entry:
``rate_base``, ``allowed_roe``, ``equity_ratio``, ``cost_of_equity``,
``payout_ratio``, ``shares_diluted``,
``cost_of_equity_above_base_growth`` (``ke <= g``),
``cost_of_equity_spread_above_floor``, ``equity_ratio_in_range``,
``allowed_roe_above_minus_one``, ``payout_ratio_in_range``,
``regulatory_lag_in_range``, ``transition_years_in_range``,
``known_allowed_roe_convention``, ``positive_rate_base``, ``adr_ratio``.

Monotonicity: higher ``ke`` ⇒ not more value; higher ``g`` and higher
``allowed_roe`` ⇒ not less value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.engines.utilities import ENGINE_PRECEDENCE_NOTE, RegulatedUtilityEngine
from app.valuation.regulated_asset import (
    ALLOWED_ROE_CONVENTIONS,
    CONVENTION_VALUE_RATIO_NOTE,
    RegulatedAssetError,
    RegulatedAssetInputs,
    earning_power_shortfall,
    excess_return_equity_value,
    frozen_base_warning,
    reconcile_regulated_asset_model,
    regulated_asset_sensitivity,
    run_regulated_asset,
)

PERIOD = "FY2025"
FY = 2025

BASE_INPUTS = dict(
    rate_base=1000.0,
    allowed_roe=0.095,
    equity_ratio=0.45,
    cost_of_equity=0.08,
    shares_diluted=100.0,
    payout_ratio=0.80,
    regulatory_base_growth=0.02,
)


def _inputs(**overrides) -> RegulatedAssetInputs:
    base = dict(BASE_INPUTS)
    base.update(overrides)
    return RegulatedAssetInputs(**base)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker, *, company_type="utility", valuation_model="regulated_asset_dasr", tags=None):
    row = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency="USD",
        sector="Utilities",
        industry="Regulated electric",
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=tags or [],
    )
    db.add(row)
    db.flush()
    return row


def _facts(db, company, values, *, period=PERIOD, fiscal_year=FY, source_type="dasr_test"):
    for metric, value in values.items():
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit="decimal" if abs(float(value)) < 1 else "USD",
                period=period,
                fiscal_year=fiscal_year,
                fiscal_quarter="FY",
                source_type=source_type,
                is_reported=True,
                confidence=Decimal("0.90"),
            )
        )
    db.commit()


def _price(db, company, price):
    from datetime import date

    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2025, 12, 31),
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            source="dasr_test",
        )
    )
    db.commit()


UTIL_FACTS = {
    "rate_base": 1000.0,
    "allowed_roe": 0.095,
    "equity_ratio": 0.45,
    "cost_of_equity": 0.08,
    "shares_diluted": 100.0,
    "payout_ratio": 0.80,
    "regulatory_base_growth": 0.02,
    "net_income": 60.0,
    "rate_case_year": 2024,
}

#: Adding capex/depreciation makes the rate base unable to grow as modelled,
#: which the engine must report (see the frozen-base test).
UTIL_FACTS_CAPEX = {**UTIL_FACTS, "capex": 150.0, "depreciation_rate": 0.05}


# ---------------------------------------------------------------------------
# 1. The identity
# ---------------------------------------------------------------------------


def test_zero_growth_full_payout_collapses_to_the_earnings_capitalised_form():
    """The special case the literature quotes, computed by hand.

    RB = 1000, allowed_roe = 9.5%, ke = 8%, g = 0, payout = 1:
      V = 1000 + (0.095 - 0.08)*1000/(0.08 - 0) = 1000 + 187.5 = 1187.5
      per share = 1187.5/100 = 11.875
    and the dividend leg agrees exactly: 1000*0.095*1/0.08 = 1187.5.
    """
    result = run_regulated_asset(
        _inputs(regulatory_base_growth=0.0, payout_ratio=1.0)
    )
    assert result.equity_value == pytest.approx(1187.5, abs=1e-9)
    assert result.value_per_share == pytest.approx(11.875, abs=1e-12)
    reconciliation = result.trace["excess_return_reconciliation"]
    assert reconciliation["excess_return_leg"]["gordon_special_case"] == pytest.approx(1187.5)
    assert reconciliation["reconciles"] is True
    assert reconciliation["residual"] == pytest.approx(0.0, abs=1e-9)


def test_excess_return_identity_is_book_equity_plus_the_present_value_of_the_spread():
    """RB = 1000, ke = 8%, g = 2%: V = 1000 + 15*1000/0.06 = 1250, i.e. 12.50/sh."""
    result = run_regulated_asset(_inputs())
    assert result.equity_value == pytest.approx(1250.0, abs=1e-9)
    assert result.value_per_share == pytest.approx(12.50, abs=1e-12)
    composition = result.trace["value_composition"]
    assert composition["book_equity"] == pytest.approx(1000.0)
    assert composition["pv_perpetuity_economic_profit"] == pytest.approx(250.0)
    assert composition["sum"] == pytest.approx(1250.0)


def test_enterprise_value_identity_is_published_not_assumed():
    """EV = RB/equity_ratio and Equity = EV*equity_ratio = RB*convention_scale."""
    result = run_regulated_asset(_inputs())
    assert result.enterprise_value == pytest.approx(1000.0 / 0.45)
    assert result.trace["enterprise_value_formula"] == "EV = rate_base / equity_ratio"
    assert result.trace["equity_value_identity"] == (
        "Equity = EV * equity_ratio = rate_base * convention_scale"
    )
    assert result.trace["equity_slice_of_capital"] == pytest.approx(450.0)
    assert result.trace["debt_slice_of_capital"] == pytest.approx(550.0)


def test_the_two_allowed_roe_conventions_differ_by_exactly_the_equity_ratio():
    """Same rate case, two units: the value differs by a factor of 2.2.

    whole_rate_base: B = 1000      ⇒ V = 1250  ⇒ 12.50 per share
    equity_slice:    B = 1000*0.45 = 450  ⇒ V = 562.5 ⇒  5.625 per share
    and 12.50 * 0.45 = 5.625 exactly, because (E) is linear in B.
    """
    whole = run_regulated_asset(_inputs(allowed_roe_convention="whole_rate_base"))
    slice_ = run_regulated_asset(_inputs(allowed_roe_convention="equity_slice"))
    assert whole.value_per_share == pytest.approx(12.50)
    assert slice_.value_per_share == pytest.approx(5.625)
    assert whole.value_per_share * 0.45 == pytest.approx(slice_.value_per_share)
    assert whole.allowed_earnings == pytest.approx(95.0)
    assert slice_.allowed_earnings == pytest.approx(42.75)
    assert whole.trace["allowed_roe_convention"] == ALLOWED_ROE_CONVENTIONS["whole_rate_base"]
    assert CONVENTION_VALUE_RATIO_NOTE


# ---------------------------------------------------------------------------
# 2. The dividend cross-check
# ---------------------------------------------------------------------------


def test_dividend_leg_publishes_the_reconciling_payout():
    """At g=2% the two legs agree only at payout = (0.095-0.02)/(0.095*1.02) = 77.40%."""
    reconciliation = reconcile_regulated_asset_model(
        rate_base=1000.0,
        allowed_roe=0.095,
        equity_ratio=0.45,
        cost_of_equity=0.08,
        payout_ratio=0.80,
        growth=0.02,
    )
    assert reconciliation["reconciling_payout"] == pytest.approx(0.7739938080495355)
    assert reconciliation["actual_payout"] == pytest.approx(0.80)
    assert reconciliation["reconciles"] is False
    # D1 = 1000*0.095*0.80*1.02 = 77.52; V = 77.52/0.06 = 1292 vs 1250 excess-return.
    assert reconciliation["dividend_next_year"] == pytest.approx(77.52)
    assert reconciliation["dividend_leg_value"] == pytest.approx(1292.0)
    assert reconciliation["residual"] == pytest.approx(-42.0)


def test_earning_power_shortfall_measures_the_regulatory_gap():
    """Allowed earnings on the regulatory base are 95; reported 60. The 35 gap
    is the product of the engine, not a footnote."""
    shortfall = earning_power_shortfall(
        rate_base=1000.0,
        equity_ratio=0.45,
        allowed_roe=0.095,
        reported_net_income=60.0,
    )
    assert shortfall["status"] == "ok"
    assert shortfall["allowed_earnings"] == pytest.approx(95.0)
    assert shortfall["shortfall"] == pytest.approx(35.0)
    assert shortfall["shortfall_pct_of_allowed"] == pytest.approx(35.0 / 95.0)


def test_earning_power_shortfall_declines_to_measure_without_reported_earnings():
    shortfall = earning_power_shortfall(
        rate_base=1000.0,
        equity_ratio=0.45,
        allowed_roe=0.095,
        reported_net_income=None,
    )
    assert shortfall["status"] == "not_available"
    assert shortfall["shortfall"] is None
    assert shortfall["allowed_earnings"] == pytest.approx(95.0)
    assert shortfall["reason"]


def test_frozen_base_warning_fires_when_capex_exceeds_the_growing_base():
    """capex 150 against depreciation 50 on a 1000 base implies 10% base growth,
    against a modelled 2%: the value is stagnating by construction."""
    warning = frozen_base_warning(
        rate_base=1000.0, capex=150.0, depreciation_rate=0.05, depreciation_amortization=None,
        growth=0.02,
    )
    assert warning["warning"] is True
    assert warning["implied_base_growth"] == pytest.approx(0.10)
    assert warning["modelled_base_growth"] == pytest.approx(0.02)
    assert "rate case" in warning["note"]


def test_frozen_base_warning_declines_to_claim_without_the_inputs():
    warning = frozen_base_warning(
        rate_base=1000.0, capex=None, depreciation_rate=None, depreciation_amortization=None,
        growth=0.02,
    )
    assert warning["status"] == "not_available"
    assert warning["warning"] is False
    assert warning["reason"]


# ---------------------------------------------------------------------------
# 3. Transition and regulatory lag
# ---------------------------------------------------------------------------


def test_transition_interpolates_the_base_and_decays_the_lag():
    """book base 700, regulatory 1000, T = 4, lag = 20%.

    Year t base = 700 + 300*t/4; roe_t = 9.5% * (1 - 0.20*(1 - t/4)):
      t=1: base 775, roe 8.075%, EP = (0.08075-0.08)*700  = 0.525
      t=2: base 850, roe 8.550%, EP = (0.08550-0.08)*775  = 4.2625
      t=3: base 925, roe 9.025%, EP = (0.09025-0.08)*850  = 8.7125
      t=4: base 1000, roe 9.500%, EP = (0.09500-0.08)*925  = 13.875
    perpetuity EP = (0.095-0.08)*1000/0.06 = 250, at t=4.
    V = 700 + Σ EP_t/1.08^t + 250/1.08^4 = 905.0127...
    """
    result = run_regulated_asset(
        _inputs(book_rate_base=700.0, transition_years=4, regulatory_lag=0.20)
    )
    schedule = result.forecast
    assert [row["effective_earning_base"] for row in schedule] == pytest.approx(
        [775.0, 850.0, 925.0, 1000.0]
    )
    assert [row["economic_profit"] for row in schedule] == pytest.approx(
        [0.525, 4.2625, 8.7125, 13.875]
    )
    # The lag is fully recovered by the end of the transition: roe_4 = allowed.
    assert schedule[-1]["effective_allowed_roe"] == pytest.approx(0.095)
    assert result.equity_value == pytest.approx(905.012783639, abs=1e-6)
    assert result.value_per_share == pytest.approx(9.05012783639, abs=1e-9)
    assert result.trace["regulatory_lag_applied"] == pytest.approx(0.20)


def test_a_longer_transition_costs_value_because_the_lag_is_being_paid_for():
    """Same converged base, more years under-recovered: strictly less value."""
    short = run_regulated_asset(_inputs(book_rate_base=700.0, transition_years=2, regulatory_lag=0.20))
    long = run_regulated_asset(_inputs(book_rate_base=700.0, transition_years=8, regulatory_lag=0.20))
    assert long.value_per_share < short.value_per_share
    assert long.trace["transition_value_uplift"] < short.trace["transition_value_uplift"]


# ---------------------------------------------------------------------------
# 4. Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,missing",
    [
        ({"rate_base": 0.0}, "positive_rate_base"),
        ({"rate_base": -10.0}, "positive_rate_base"),
        ({"equity_ratio": 0.0}, "equity_ratio_in_range"),
        ({"equity_ratio": 1.5}, "equity_ratio_in_range"),
        ({"equity_ratio": -0.3}, "equity_ratio_in_range"),
        ({"shares_diluted": 0.0}, "positive_shares_diluted"),
        ({"allowed_roe": -1.5}, "allowed_roe_above_minus_one"),
        ({"cost_of_equity": 0.0}, "positive_cost_of_equity"),
        ({"cost_of_equity": 0.05, "regulatory_base_growth": 0.08}, "cost_of_equity_above_base_growth"),
        ({"cost_of_equity": 0.0304, "regulatory_base_growth": 0.03}, "cost_of_equity_spread_above_floor"),
        ({"payout_ratio": 0.0}, "payout_ratio_in_range"),
        ({"payout_ratio": 1.4}, "payout_ratio_in_range"),
        ({"regulatory_lag": -0.2}, "regulatory_lag_in_range"),
        ({"regulatory_lag": 1.4}, "regulatory_lag_in_range"),
        ({"transition_years": -1}, "transition_years_in_range"),
        ({"transition_years": 40}, "transition_years_in_range"),
        ({"allowed_roe_convention": "made_up"}, "known_allowed_roe_convention"),
        ({"book_rate_base": 0.0}, "positive_book_rate_base"),
    ],
)
def test_regulated_asset_refuses_economically_impossible_inputs(overrides, missing):
    with pytest.raises(RegulatedAssetError) as excinfo:
        run_regulated_asset(_inputs(**overrides))
    assert excinfo.value.missing_input == missing


def test_allowed_roe_below_the_cost_of_equity_is_reported_below_book_not_clipped():
    """allowed_roe 6% against ke 8%: V = 1000 + (0.06-0.08)*1000/0.06 = 666.67.

    Below the 1000 of equity invested, positive, and flagged. Clamping to zero
    would claim the base is worth exactly nothing to the equity when the
    arithmetic says it is worth two thirds of what is in it.
    """
    result = run_regulated_asset(_inputs(allowed_roe=0.06))
    assert result.value_per_share == pytest.approx(6.6666666666666666, abs=1e-9)
    assert result.trace["value_destroying_allowed_roe"] is True
    assert result.trace["value_below_book_equity"] is True
    assert result.trace["negative_equity_value"] is False
    assert "NOT clamped to zero" in result.trace["negative_value_handling"]


def test_a_negative_allowed_return_produces_a_negative_value_and_says_so():
    """allowed_roe = -2% at ke = 8% and g = 0:
    V = 1000 + (-0.02-0.08)*1000/0.08 = 1000 - 1250 = -250, i.e. -2.50/share."""
    result = run_regulated_asset(_inputs(allowed_roe=-0.02, regulatory_base_growth=0.0))
    assert result.value_per_share == pytest.approx(-2.50, abs=1e-12)
    assert result.trace["negative_equity_value"] is True
    assert result.trace["value_below_book_equity"] is True
    assert result.trace["value_destroying_allowed_roe"] is True


def test_excess_return_helper_agrees_with_the_model():
    leg = excess_return_equity_value(
        book_equity=1000.0, allowed_roe=0.095, cost_of_equity=0.08, growth=0.02
    )
    assert leg["equity_value"] == pytest.approx(1250.0)
    assert leg["value_creating"] is True
    assert leg["excess_return_per_period"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 5. Monotonicity and sensitivity
# ---------------------------------------------------------------------------


def test_higher_cost_of_equity_never_raises_the_regulated_value():
    values = [
        run_regulated_asset(_inputs(cost_of_equity=cost)).value_per_share
        for cost in (0.07, 0.08, 0.09, 0.10)
    ]
    assert values == pytest.approx([15.0, 12.5, 10.714285714285714, 9.375])
    assert values == sorted(values, reverse=True)


def test_higher_base_growth_and_higher_allowed_roe_never_lower_the_value():
    growth_values = [
        run_regulated_asset(_inputs(regulatory_base_growth=growth)).value_per_share
        for growth in (0.0, 0.01, 0.02, 0.03)
    ]
    assert growth_values == sorted(growth_values)
    roe_values = [
        run_regulated_asset(_inputs(allowed_roe=roe)).value_per_share
        for roe in (0.085, 0.09, 0.095, 0.10)
    ]
    assert roe_values == sorted(roe_values)
    assert roe_values == pytest.approx([10.833333333333334, 11.666666666666666, 12.5, 13.333333333333334])


def test_base_growth_clamps_at_the_ceiling_and_publishes_it():
    result = run_regulated_asset(_inputs(regulatory_base_growth=0.25))
    assert result.trace["inputs"]["regulatory_base_growth"] == pytest.approx(0.06)
    assert result.trace["regulatory_base_growth_clamped_from"] == 0.25
    assert result.trace["clamp_notes"]


def test_allowed_roe_sensitivity_brackets_the_base_value():
    table = regulated_asset_sensitivity(
        **{key: value for key, value in BASE_INPUTS.items() if key != "regulatory_base_growth"},
        growth=BASE_INPUTS["regulatory_base_growth"],
    )
    values = [row["value_per_share"] for row in table["rows"]]
    assert len(values) == 3
    assert values == sorted(values)
    assert values[1] == pytest.approx(12.50, )
    assert [row["value_creating"] for row in table["rows"]] == [True, True, True]


# ---------------------------------------------------------------------------
# 6. Engine end to end
# ---------------------------------------------------------------------------


def _value(db, company):
    context = RegulatedUtilityEngine().build_context(db, company, None)
    return RegulatedUtilityEngine().value(context)


def test_utilities_engine_publishes_the_whole_arithmetic(db):
    company = _company(db, "UTILHAPPY")
    _facts(db, company, UTIL_FACTS)
    _price(db, company, 12.0)
    context = RegulatedUtilityEngine().build_context(db, company, 12.0)
    result = RegulatedUtilityEngine().value(context)

    assert result["status"] == "ok"
    assert result["base_value"] == pytest.approx(12.50, abs=1e-9)
    assert result["bear_value"] <= result["base_value"] <= result["bull_value"]
    assert result["margin_of_safety"] == pytest.approx((result["expected_value"] - 12.0) / result["expected_value"])
    assert result["trace"]["no_net_debt_subtracted"] is True
    assert result["trace"]["engine_precedence_note"] == ENGINE_PRECEDENCE_NOTE
    assert result["dasr"]["enterprise_value"] == pytest.approx(1000.0 / 0.45)
    assert result["dasr"]["allowed_earnings"] == pytest.approx(95.0)
    assert result["dasr"]["earning_power_shortfall"]["shortfall"] == pytest.approx(35.0)
    assert result["dasr"]["excess_return_reconciliation"]["reconciles"] is False
    assert result["trace"]["periods"]["rate_base"] == PERIOD
    assert result["trace"]["fact_ids"]["rate_base"] is not None
    assert len(result["sensitivity"]["rows"]) == 3
    assert result["reverse_dcf"] == {}
    assert result["publication_blockers"] == []


def test_utilities_engine_blocks_when_the_rate_base_cannot_grow(db):
    """capex 150 on a 1000 base against 2% modelled growth: the value is
    stagnating by arithmetic, and that is the warning the engine exists for."""
    company = _company(db, "UTILFROZEN")
    _facts(db, company, UTIL_FACTS_CAPEX)
    _price(db, company, 12.0)
    result = _value(db, company)

    assert "rate_base_frozen_below_capex" in result["publication_blockers"]
    assert result["publishable"] is False
    assert result["status"] == "partial"
    assert result["trace"]["frozen_base_warning"]["warning"] is True
    assert result["trace"]["notice"]


def test_utilities_engine_flags_a_value_destroying_allowed_roe(db):
    company = _company(db, "UTILDESTROY")
    _facts(db, company, {**UTIL_FACTS, "allowed_roe": 0.06})
    _price(db, company, 12.0)
    result = _value(db, company)

    assert "value_destroying_allowed_roe" in result["publication_blockers"]
    assert result["publishable"] is False
    assert result["trace"]["value_below_book_equity"] is True
    assert result["bear_value"] <= result["base_value"] <= result["bull_value"]


def test_utilities_engine_names_every_missing_regulatory_input(db):
    company = _company(db, "UTILMISS")
    _facts(db, company, {"shares_diluted": 100.0, "book_rate_base": 800.0})
    _price(db, company, 12.0)
    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == [
        "rate_base",
        "allowed_roe",
        "equity_ratio",
        "cost_of_equity",
        "payout_ratio",
    ]
    assert result["trace"]["dasr_input_contract"]["identity"].startswith("V = book_equity")
    assert result["publishable"] is False


def test_utilities_engine_refuses_a_regulator_that_costs_less_than_growth(db):
    company = _company(db, "UTILSPREAD")
    _facts(db, company, {**UTIL_FACTS, "cost_of_equity": 0.05, "regulatory_base_growth": 0.08})
    _price(db, company, 12.0)
    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["cost_of_equity_above_base_growth"]


def test_utilities_engine_refuses_an_adr_without_a_ratio(db):
    company = _company(db, "UTILADR", tags=["adr"])
    _facts(db, company, UTIL_FACTS)
    _price(db, company, 120.0)
    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["adr_ratio"]


def test_utilities_engine_converts_to_the_listed_share_for_an_adr_with_a_ratio(db):
    company = _company(db, "UTILADR2", tags=["adr:2"])
    _facts(db, company, UTIL_FACTS)
    _price(db, company, 2.0 * 12.50)
    context = RegulatedUtilityEngine().build_context(db, company, 2.0 * 12.50)
    result = RegulatedUtilityEngine().value(context)

    assert result["status"] == "ok"
    assert result["adr_ratio"] == 2.0
    assert result["value_per_share_basis"] == "ordinary_share"
    assert result["listed_share_values"]["base"] == pytest.approx(25.0)
    assert result["margin_of_safety"] == pytest.approx(
        (result["expected_value"] - 12.50) / result["expected_value"]
    )


def test_utilities_engine_publishes_the_regulatory_scenarios(db):
    """The bear is a REGULATORY bear: allowed ROE -100bp, ke +100bp, lag +15pp
    and two more years of under-recovery. Those are the four levers a rate case
    actually moves."""
    company = _company(db, "UTILSCEN")
    _facts(db, company, {**UTIL_FACTS, "regulatory_lag": 0.10, "book_rate_base": 900.0, "transition_years": 1})
    _price(db, company, 12.0)
    result = _value(db, company)

    bear = result["trace"]["scenarios"]["bear"]["definition"]["assumptions"]
    assert bear["allowed_roe"] == pytest.approx(0.085)
    assert bear["cost_of_equity"] == pytest.approx(0.09)
    assert bear["regulatory_lag"] == pytest.approx(0.25)
    assert bear["transition_years"] == 3
    assert "regulatory_downturn" in result["trace"]["scenarios"]["bear"]["definition"]["drivers"][0]
    assert result["trace"]["probabilities"]["bear"] + result["trace"]["probabilities"][
        "base"
    ] + result["trace"]["probabilities"]["bull"] == pytest.approx(1.0)


def test_utilities_engine_falls_back_to_a_tag_growth_and_says_so(db):
    company = _company(db, "UTILTAG")
    _facts(
        db,
        company,
        {key: value for key, value in UTIL_FACTS.items() if key != "regulatory_base_growth"},
    )
    _price(db, company, 12.0)
    result = _value(db, company)

    assert "regulatory_base_growth_source" in result["publication_blockers"]
    assert result["trace"]["assumptions"]["regulatory_base_growth_source"] == "tag_default"
    assert result["trace"]["assumptions"]["regulatory_base_growth"] == pytest.approx(0.03)
    # The tag default is also the fallback for the regulatory lag. With no
    # transition there is no haircut to apply, so it is a note, not a blocker.
    assert result["trace"]["assumptions"]["regulatory_lag"] == 0.0
    assert result["trace"]["assumptions"]["transition_years"] == 0
    assert "regulatory_lag_source" not in result["publication_blockers"]


def test_utilities_engine_blocks_on_a_default_lag_only_when_there_is_a_transition(db):
    company = _company(db, "UTILLAG")
    _facts(db, company, {**UTIL_FACTS, "book_rate_base": 800.0, "transition_years": 3})
    _price(db, company, 12.0)
    result = _value(db, company)

    assert "regulatory_lag_source" in result["publication_blockers"]
    assert result["trace"]["assumptions"]["regulatory_lag_source"] == "policy_default"
    assert result["trace"]["dasr"]["regulatory_lag_applied"] == 0.0
    assert result["publishable"] is False


def test_utilities_engine_runs_a_regime_with_no_transition_and_no_lag(db):
    company = _company(db, "UTILCONV")
    _facts(db, company, UTIL_FACTS)
    result = _value(db, company)
    assumptions = result["trace"]["assumptions"]
    assert assumptions["transition_years"] == 0
    assert assumptions["transition_years_source"] == "policy_default"
    assert assumptions["book_rate_base"] is None
    assert result["trace"]["dasr"]["inputs"]["book_rate_base_source"] == (
        "assumed_equal_to_rate_base"
    )
    # No transition and no lag: the model is exactly (E) on the regulated base.
    assert result["base_value"] == pytest.approx(12.50, abs=1e-9)
    assert result["trace"]["dasr"]["transition_value_uplift"] == pytest.approx(0.0, abs=1e-9)
