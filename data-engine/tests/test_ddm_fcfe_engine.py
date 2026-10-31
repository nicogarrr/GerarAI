"""DDM / FCFE engines: the arithmetic is auditable, and the refusals are named.

The formula tests check hand-computed values written out as literals with the
arithmetic in the docstring, not the module's own output. The engine tests
exercise the full fact-resolution path with an in-memory database.

Refusals covered, each asserting the named ``missing_inputs`` entry:
``dividend_per_share_or_payout_ratio``, ``positive_shares_diluted``,
``cost_of_equity_above_dividend_growth`` (``ke <= g``),
``cost_of_equity_above_minus_one`` (``ke <= -1``),
``growth_below_return_on_equity`` (``g >= roe``),
``payout_ratio_not_above_one``, ``retention_ratio_in_zero_one``,
``non_negative_stage1_years``, ``adr_ratio``.

Monotonicity properties asserted: higher ``ke`` ⇒ not more value; higher
growth ⇒ not less value, up to the clamps that saturate it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.dividend_equity import (
    MIN_COST_OF_EQUITY_SPREAD,
    STAGE1_GROWTH_CEILING,
    STAGE1_GROWTH_FLOOR,
    STAGE2_GROWTH_CEILING,
    DdmInputError,
    DdmInputs,
    FcfeInputs,
    fcfe_bridge,
    gordon_value,
    reconcile_dividend_model,
    reconcile_fcfe_against_dividend_model,
    run_ddm,
    run_fcfe,
    solve_required_dividend_growth,
)
from app.valuation.engines.ddm_fcfe import (
    DividendDiscountEngine,
    FreeCashFlowToEquityEngine,
)

PERIOD = "FY2025"
FY = 2025


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker, *, company_type="utility", valuation_model="dividend_discount", tags=None):
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


def _facts(db, company, values, *, period=PERIOD, fiscal_year=FY, source_type="ddm_test"):
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


def _price(db, company, price, *, day=None):
    from datetime import date

    db.add(
        MarketPrice(
            company_id=company.id,
            date=day or date(2025, 12, 31),
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            source="ddm_test",
        )
    )
    db.commit()


def _ddm_inputs(**overrides) -> DdmInputs:
    base = dict(
        dividend_per_share=1.80,
        cost_of_equity=0.09,
        stage1_growth=0.06,
        stage1_years=3,
        stage2_growth=0.03,
        payout_ratio=0.60,
        eps=3.00,
        return_on_equity=0.12,
        shares_diluted=100.0,
    )
    base.update(overrides)
    return DdmInputs(**base)


# ---------------------------------------------------------------------------
# 1. The DDM value equals the hand-computed schedule
# ---------------------------------------------------------------------------


def test_multi_stage_ddm_equals_the_hand_computed_schedule():
    """D0=1.80, ke=9%, d1=6% for 3 years, then g2=3% forever.

    Hand arithmetic:
      D1 = 1.80*1.06 = 1.908      PV = 1.908   / 1.09^1 = 1.75045872
      D2 = 2.02248                PV = 2.02248 / 1.09^2 = 1.70228095
      D3 = 2.1438288              PV = 2.1438288/ 1.09^3 = 1.65542918
      D4 = 2.1438288*1.03 = 2.208143664
      TV = D4/(ke-g2) = 2.208143664/0.06 = 36.80239440
      PV(TV) = 36.80239440/1.295029 = 28.41820098
      total = 1.75045872+1.70228095+1.65542918+28.41820098 = 33.52636983
    """
    result = run_ddm(_ddm_inputs())
    assert result.value_per_share == pytest.approx(33.526369834189, abs=1e-9)
    assert result.trace["pv_explicit_dividends"] == pytest.approx(5.108168851817, abs=1e-9)
    assert result.trace["pv_terminal_value"] == pytest.approx(28.418200982372, abs=1e-9)
    assert result.trace["terminal_value"] == pytest.approx(36.8023944, abs=1e-9)
    assert result.equity_value == pytest.approx(3352.6369834189, abs=1e-6)
    assert [row["dividend_per_share"] for row in result.forecast] == pytest.approx(
        [1.908, 2.02248, 2.1438288]
    )


def test_single_stage_ddm_is_the_gordon_price():
    """n1 = 0 is a legal DDM: D0*(1+g)/(ke-g) = 1.80*1.03/0.06 = 30.90."""
    result = run_ddm(_ddm_inputs(stage1_years=0, stage1_growth=0.03))
    assert result.value_per_share == pytest.approx(30.90, abs=1e-12)
    assert result.trace["single_stage"] is True
    assert result.forecast == []
    assert result.value_per_share == pytest.approx(gordon_value(1.80, 0.09, 0.03))


def test_ddm_never_subtracts_net_debt():
    """FCFE/DDM are equity methods: the trace says so and the maths has no
    net-debt term to remove."""
    ddm_trace = run_ddm(_ddm_inputs()).trace
    assert ddm_trace["no_net_debt_subtracted"] is True
    fcfe_trace = run_fcfe(_fcfe_inputs()).trace
    assert fcfe_trace["no_net_debt_subtracted"] is True
    assert "net_debt" not in fcfe_trace["inputs"]


# ---------------------------------------------------------------------------
# 2. The reconciliation: Gordon vs justified P/E
# ---------------------------------------------------------------------------


def test_reconciliation_shows_gordon_and_justified_pe_are_the_same_number():
    """D1 = 1.80*1.03 = 1.854 and EPS1*payout = 3.09*0.60 = 1.854, exactly.

    So P = D1/(ke-g) = 1.854/0.06 = 30.90 and P/E1 = payout/(ke-g) = 10.0, and
    the residual is zero to floating point.
    """
    reconciliation = reconcile_dividend_model(
        dividend_per_share=1.80,
        cost_of_equity=0.09,
        terminal_growth=0.03,
        payout_ratio=0.60,
        eps=3.00,
        return_on_equity=0.12,
    )
    assert reconciliation["dividend_per_share_d1"] == pytest.approx(1.854)
    assert reconciliation["dividend_implied_by_payout"] == pytest.approx(1.854)
    assert reconciliation["gordon_perpetuity_value"] == pytest.approx(30.90)
    assert reconciliation["justified_forward_pe"] == pytest.approx(10.0)
    assert reconciliation["eps_implied_value"] == pytest.approx(30.90)
    assert reconciliation["residual_per_share"] == pytest.approx(0.0, abs=1e-9)
    assert reconciliation["reconciles"] is True
    # Sustainable growth at a 60% payout on a 12% ROE is 4.8%, not the 3% used.
    assert reconciliation["sustainable_growth_at_payout"] == pytest.approx(0.048)


def test_reconciliation_isolates_the_dividend_policy_gap():
    """A dividend below EPS*payout is a policy choice, and the gap is exactly
    (D1 - EPS1*payout)/(ke-g) with ke and g cancelled out.

    D0 = 1.20, payout 0.60, EPS0 = 3.00 => D1 = 1.236 vs EPS1*payout = 1.854.
    gap = (1.236 - 1.854)/0.06 = -10.30.
    """
    reconciliation = reconcile_dividend_model(
        dividend_per_share=1.20,
        cost_of_equity=0.09,
        terminal_growth=0.03,
        payout_ratio=0.60,
        eps=3.00,
    )
    assert reconciliation["reconciles"] is False
    assert reconciliation["reconciliation_status"] == "divergent"
    assert reconciliation["dividend_policy_gap"] == pytest.approx(1.236 - 1.854)
    assert reconciliation["residual_per_share"] == pytest.approx(-10.30, abs=1e-9)


def test_reconciliation_declines_to_claim_an_identity_without_a_payout():
    reconciliation = reconcile_dividend_model(
        dividend_per_share=1.80,
        cost_of_equity=0.09,
        terminal_growth=0.03,
    )
    assert reconciliation["reconciliation_status"] == "not_available"
    assert reconciliation["eps_implied_value"] is None
    assert reconciliation["reconciles"] is None
    assert reconciliation["reconciliation_note"]


def test_reconciliation_keeps_the_gordon_leg_and_the_explicit_stage_apart():
    """The multi-stage premium is what the d1/n1 forecast bought over the
    perpetuity: 33.52636983 - 30.90 = 2.62636983."""
    reconciliation = _engine_reconciliation()
    assert reconciliation["gordon_perpetuity_value"] == pytest.approx(30.90)
    assert reconciliation["multi_stage_value"] == pytest.approx(33.526369834189, abs=1e-9)
    assert reconciliation["multi_stage_premium_over_gordon"] == pytest.approx(
        2.626369834189, abs=1e-9
    )


def _engine_reconciliation() -> dict:
    from app.valuation.engines.ddm_fcfe import _ddm_reconciliation

    return _ddm_reconciliation(
        dividend=1.80,
        cost_of_equity=0.09,
        terminal=0.03,
        payout=0.60,
        eps=3.00,
        roe=0.12,
        multi_stage_value=run_ddm(_ddm_inputs()).value_per_share,
    )


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,missing",
    [
        ({"cost_of_equity": 0.03}, "cost_of_equity_above_dividend_growth"),
        ({"cost_of_equity": 0.09, "stage2_growth": 0.09}, "cost_of_equity_above_dividend_growth"),
        ({"cost_of_equity": -1.0, "stage2_growth": -0.05}, "cost_of_equity_above_minus_one"),
        ({"cost_of_equity": 0.0304, "stage2_growth": 0.03}, "cost_of_equity_spread_above_floor"),
        ({"stage2_growth": 0.12, "return_on_equity": 0.12}, "growth_below_return_on_equity"),
        ({"stage1_growth": 0.13, "return_on_equity": 0.12}, "growth_below_return_on_equity"),
        ({"payout_ratio": 1.20}, "payout_ratio_not_above_one"),
        ({"shares_diluted": 0.0}, "positive_shares_diluted"),
        ({"stage1_years": -1}, "non_negative_stage1_years"),
        ({"dividend_per_share": 0.0}, "positive_dividend_per_share"),
    ],
)
def test_ddm_refuses_economically_impossible_inputs(overrides, missing):
    with pytest.raises(DdmInputError) as excinfo:
        run_ddm(_ddm_inputs(**overrides))
    assert excinfo.value.missing_input == missing


def test_ddm_refuses_a_company_that_pays_no_dividend():
    with pytest.raises(DdmInputError) as excinfo:
        run_ddm(_ddm_inputs(dividend_per_share=0.0))
    assert excinfo.value.missing_input == "positive_dividend_per_share"
    assert "invention" in excinfo.value.reason


def test_ddm_clamps_growth_and_publishes_the_clamp():
    result = run_ddm(
        _ddm_inputs(stage1_growth=0.30, stage2_growth=0.06, return_on_equity=None)
    )
    assert result.trace["stage1_growth_clamped_from"] == 0.30
    assert result.trace["stage2_growth_clamped_from"] == 0.06
    assert result.trace["inputs"]["stage1_growth"] == STAGE1_GROWTH_CEILING
    assert result.trace["inputs"]["stage2_growth"] == STAGE2_GROWTH_CEILING
    assert len(result.trace["clamp_notes"]) == 2
    assert STAGE1_GROWTH_FLOOR < 0 < STAGE1_GROWTH_CEILING


def test_ddm_clamps_a_dividend_cut_too():
    result = run_ddm(
        _ddm_inputs(stage1_growth=-0.50, stage2_growth=-0.50, return_on_equity=None)
    )
    assert result.trace["inputs"]["stage1_growth"] == STAGE1_GROWTH_FLOOR
    assert result.trace["inputs"]["stage2_growth"] >= -0.05


# ---------------------------------------------------------------------------
# 4. Monotonicity
# ---------------------------------------------------------------------------


def test_higher_cost_of_equity_never_raises_the_ddm_value():
    previous = None
    for cost in (0.07, 0.08, 0.09, 0.10, 0.12):
        value = run_ddm(_ddm_inputs(cost_of_equity=cost)).value_per_share
        if previous is not None:
            assert value < previous, (cost, value, previous)
        previous = value


def test_higher_growth_never_lowers_the_ddm_value_until_it_saturates():
    values = [
        run_ddm(_ddm_inputs(stage2_growth=growth, return_on_equity=None)).value_per_share
        for growth in (0.0, 0.01, 0.02, 0.03, 0.04, 0.05)
    ]
    assert values == sorted(values)
    # Saturates at the clamp rather than diverging: any raw g above the 5%
    # ceiling but still below ke prices the same model, so a reader who typed
    # 8% and a reader who typed 5% get the same number and the same note.
    assert run_ddm(
        _ddm_inputs(stage2_growth=0.06, return_on_equity=None)
    ).value_per_share == pytest.approx(
        run_ddm(_ddm_inputs(stage2_growth=0.08, return_on_equity=None)).value_per_share
    )
    assert pytest.approx(0.05) == STAGE2_GROWTH_CEILING


def test_wider_spread_is_a_lower_price():
    previous = None
    for cost in (0.07, 0.09, 0.11):
        result = run_ddm(_ddm_inputs(cost_of_equity=cost, stage2_growth=0.03))
        assert result.trace["cost_of_equity_minus_terminal_growth"] == pytest.approx(
            cost - 0.03
        )
        if previous is not None:
            assert result.value_per_share < previous
        previous = result.value_per_share
    assert pytest.approx(0.005) == MIN_COST_OF_EQUITY_SPREAD


# ---------------------------------------------------------------------------
# 5. Reverse DDM
# ---------------------------------------------------------------------------


def test_reverse_ddm_solves_the_growth_the_price_requires():
    price = run_ddm(_ddm_inputs()).value_per_share
    solved = solve_required_dividend_growth(
        market_price=price,
        dividend_per_share=1.80,
        cost_of_equity=0.09,
        stage2_growth=0.03,
        stage1_years=3,
        payout_ratio=0.60,
    )
    assert solved["status"] == "ok"
    assert solved["out_of_bounds"] is False
    # The explicit stage grew at 6% while the terminal grew at 3%; the solved
    # number is the single growth that reproduces the price, between the two.
    assert 0.03 <= solved["required_stage1_growth"] <= 0.06


def test_reverse_ddm_withholds_a_number_the_price_cannot_reach():
    solved = solve_required_dividend_growth(
        market_price=500.0,
        dividend_per_share=1.80,
        cost_of_equity=0.09,
        stage2_growth=0.03,
    )
    assert solved["out_of_bounds"] is True
    assert solved["required_stage1_growth"] is None
    assert "ceiling" in solved["reason"]


# ---------------------------------------------------------------------------
# 6. FCFE
# ---------------------------------------------------------------------------


def _fcfe_inputs(**overrides) -> FcfeInputs:
    base = dict(
        net_income=200.0,
        capex=80.0,
        depreciation_amortization=40.0,
        retention_ratio=0.30,
        cost_of_equity=0.10,
        stage1_growth=0.05,
        stage1_years=0,
        stage2_growth=0.03,
        delta_total_debt=20.0,
        delta_working_capital=5.0,
        shares_diluted=100.0,
        return_on_equity=0.14,
    )
    base.update(overrides)
    return FcfeInputs(**base)


def test_fcfe_bridge_is_term_by_term():
    """FCFE = NI - (capex - D&A) + Δdeuda - ΔWC = 200 - 40 + 20 - 5 = 175.

    La reinversión neta se resta entera: la parte financiada con deuda ya entra
    por Δdeuda. Con el antiguo factor (1 - b) salía 187 (CFA L2, FCFE).
    """
    bridge = fcfe_bridge(
        net_income=200.0,
        capex=80.0,
        depreciation_amortization=40.0,
        retention_ratio=0.30,
        delta_total_debt=20.0,
        delta_working_capital=5.0,
    )
    assert bridge["net_reinvestment_capex_less_depreciation"] == pytest.approx(40.0)
    assert bridge["net_reinvestment_subtracted"] == pytest.approx(40.0)
    assert bridge["fcfe"] == pytest.approx(175.0)


def test_fcfe_bridge_does_not_scale_reinvestment_by_retention():
    """El ratio de retención no cambia el FCFE de un ejercicio.

    NI 100, capex 50, D&A 20, sin deuda ni ΔWC: FCFE = 100 - 30 = 70 con
    cualquier b. Antes: b=0,6 daba 88 y b=1 daba 100 (reinversión ignorada).
    """
    for retention in (0.0, 0.6, 1.0):
        bridge = fcfe_bridge(
            net_income=100.0,
            capex=50.0,
            depreciation_amortization=20.0,
            retention_ratio=retention,
            delta_total_debt=0.0,
            delta_working_capital=0.0,
        )
        assert bridge["fcfe"] == pytest.approx(70.0)


def test_fcfe_value_is_the_gordon_price_of_the_own_stream():
    """175*(1+0.03) = 180.25; 180.25/(0.10-0.03) = 180.25/0.07 = 2575.0"""
    result = run_fcfe(_fcfe_inputs())
    assert result.fcfe == pytest.approx(175.0)
    assert result.value_per_share == pytest.approx(2575.0, abs=1e-9)
    assert result.equity_value == pytest.approx(257500.0, abs=1e-6)


def test_fcfe_collapses_onto_the_gordon_price_when_nothing_is_retained_or_financed():
    """b=0, Δdebt=0, ΔWC=0 ⇒ FCFE = NI ⇒ the FCFE price is the Gordon price."""
    result = run_fcfe(
        _fcfe_inputs(
            retention_ratio=0.0,
            delta_total_debt=0.0,
            delta_working_capital=0.0,
            capex=40.0,
            depreciation_amortization=40.0,
        )
    )
    reconciliation = result.trace["reconciliation"]
    assert reconciliation["identity_holds"] is True
    assert reconciliation["fcfe_minus_net_income"] == pytest.approx(0.0)
    assert reconciliation["fcfe_per_share_perpetuity"] == pytest.approx(
        reconciliation["net_income_gordon_price"]
    )


def test_fcfe_reconciliation_names_the_bridge_that_makes_it_differ():
    reconciliation = run_fcfe(_fcfe_inputs()).trace["reconciliation"]
    assert reconciliation["identity_holds"] is False
    assert reconciliation["fcfe_minus_net_income"] == pytest.approx(-25.0)
    assert reconciliation["bridge_gap_per_share"] < 0


def test_fcfe_reconciliation_attributes_the_gap_to_ke_and_g_not_the_debt():
    """The bridge gap scales with 1/(ke - g) and with the size of the
    reinvestment/financing terms, never with the debt balance: that is the
    proof the debt is priced once, in ke."""
    kwargs = dict(
        fcfe=187.0,
        net_income=200.0,
        retention_ratio=0.30,
        delta_total_debt=20.0,
        delta_working_capital=5.0,
        cost_of_equity=0.10,
        terminal_growth=0.03,
    )
    base = reconcile_fcfe_against_dividend_model(**kwargs)
    wider_spread = reconcile_fcfe_against_dividend_model(
        **{**kwargs, "terminal_growth": 0.02}
    )
    assert base["fcfe_minus_net_income"] == pytest.approx(-13.0)
    assert base["net_income_gordon_price"] == pytest.approx(200.0 * 1.03 / 0.07)
    assert base["fcfe_per_share_perpetuity"] == pytest.approx(187.0 * 1.03 / 0.07)
    # A wider spread shrinks the gap by exactly the ratio of spreads.
    assert base["bridge_gap_per_share"] == pytest.approx(-13.0 * 1.03 / 0.07)
    assert wider_spread["bridge_gap_per_share"] == pytest.approx(
        -13.0 * 1.02 / 0.08
    )
    assert abs(wider_spread["bridge_gap_per_share"]) < abs(base["bridge_gap_per_share"])
    assert base["identity_conditions"] == {
        "retention_ratio_is_zero": False,
        "delta_total_debt_is_zero": False,
        "delta_working_capital_is_zero": False,
    }
    assert "priced once" in base["identity_note"]


def test_fcfe_value_does_not_move_with_the_disclosed_debt_balance():
    """total_debt/net_debt are disclosure: the same cash flow at the same ke
    gives the same value whatever the debt balance is."""
    lean = run_fcfe(_fcfe_inputs(total_debt=100.0, net_debt=0.0))
    levered = run_fcfe(_fcfe_inputs(total_debt=4000.0, net_debt=3800.0))
    assert lean.value_per_share == pytest.approx(levered.value_per_share)
    assert levered.trace["net_debt_disclosure_only"] == 3800.0


def test_fcfe_refuses_growth_above_the_return_on_equity():
    with pytest.raises(DdmInputError) as excinfo:
        run_fcfe(_fcfe_inputs(stage2_growth=0.15, return_on_equity=0.14))
    assert excinfo.value.missing_input == "growth_below_return_on_equity"


def test_fcfe_refuses_an_out_of_range_retention_ratio():
    with pytest.raises(DdmInputError) as excinfo:
        run_fcfe(_fcfe_inputs(retention_ratio=1.4))
    assert excinfo.value.missing_input == "retention_ratio_in_zero_one"


def test_fcfe_higher_cost_of_equity_never_raises_the_value():
    previous = None
    for cost in (0.08, 0.09, 0.10, 0.12):
        value = run_fcfe(_fcfe_inputs(cost_of_equity=cost)).value_per_share
        if previous is not None:
            assert value < previous
        previous = value


# ---------------------------------------------------------------------------
# 7. Engine end to end
# ---------------------------------------------------------------------------

DDM_FACTS = {
    "dividend_per_share": 1.80,
    "net_income": 300.0,
    "payout_ratio": 0.60,
    "cost_of_equity": 0.09,
    "dividend_growth": 0.03,
    "eps": 3.00,
    "roe": 0.12,
    "shares_diluted": 100.0,
}

FCFE_FACTS = {
    "net_income": 300.0,
    "capex": -120.0,
    "depreciation_amortization": 60.0,
    "delta_total_debt": 15.0,
    "delta_working_capital": 8.0,
    "payout_ratio": 0.70,
    "cost_of_equity": 0.10,
    "dividend_growth": 0.03,
    "roe": 0.15,
    "shares_diluted": 100.0,
    "total_debt": 900.0,
    "net_debt": 700.0,
}


def test_ddm_engine_publishes_the_reconciliation_and_an_ordered_range(db):
    """With one ``dividend_growth`` fact, d1 and g2 are the same rate, so the
    multi-stage schedule is the first three terms of an infinite series whose
    sum is exactly the Gordon price — and the engine proves it.

      D1 = 1.80*1.03 = 1.854
      Gordon = D1/(ke-g) = 1.854/0.06 = 30.90
      and Σ_{t>=1} D0*1.03^t/1.09^t = D0*1.03/(1.09-1.03) = 1.854/0.06
    """
    company = _company(db, "DDMHAPPY")
    _facts(db, company, DDM_FACTS)
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "ok"
    assert result["publishable"] is True
    assert result["bear_value"] <= result["base_value"] <= result["bull_value"]
    assert result["bear_value"] <= result["expected_value"] <= result["bull_value"]
    assert result["base_value"] == pytest.approx(30.90, abs=1e-9)
    assert result["margin_of_safety"] == pytest.approx(
        (result["expected_value"] - 30.0) / result["expected_value"]
    )
    reconciliation = result["ddm"]["reconciliation"]
    assert reconciliation["gordon_perpetuity_value"] == pytest.approx(30.90)
    assert reconciliation["reconciles"] is True
    # The audit property: d1 == g2 means the explicit stage adds nothing.
    assert reconciliation["multi_stage_premium_over_gordon"] == pytest.approx(
        0.0, abs=1e-9
    )
    base_trace = result["trace"]["scenarios"]["base"]["trace"]
    assert base_trace["no_net_debt_subtracted"] is True
    assert base_trace["pv_explicit_dividends"] == pytest.approx(4.8270207076, abs=1e-9)
    assert base_trace["pv_terminal_value"] == pytest.approx(26.0729792924, abs=1e-9)
    assert result["trace"]["assumptions"]["growth_source"] == "financial_facts"
    assert result["trace"]["assumptions"]["payout_source"] == "financial_facts"
    assert result["publication_blockers"] == []
    assert len(result["sensitivity"]["rows"]) == 3
    assert result["reverse_dcf"]["status"] in ("ok", "out_of_bounds")
    assert result["trace"]["fact_ids"]["dividend_per_share"] is not None
    assert result["trace"]["periods"]["dividend_per_share"] == PERIOD
    assert result["value_per_share_basis"] == "ordinary_share"
    assert result["trace"]["no_net_debt_subtracted"] is True


def test_ddm_engine_honours_a_zero_forecast_years_fact(db):
    company = _company(db, "DDMSINGLE")
    _facts(db, company, {**DDM_FACTS, "dividend_forecast_years": 0})
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    # A pure Gordon DDM IS the perpetuity, so the engine says out loud that
    # the explicit forecast is not the driver of the value.
    assert "forecast_is_not_the_driver" in result["publication_blockers"]
    assert result["status"] == "partial"
    assert result["base_value"] == pytest.approx(30.90, abs=1e-9)
    assert result["trace"]["assumptions"]["stage1_years"] == 0
    assert result["trace"]["assumptions"]["stage1_years_source"] == "financial_facts"
    assert result["trace"]["scenarios"]["base"]["trace"]["single_stage"] is True


def test_ddm_engine_blockers_when_the_inputs_are_defaults(db):
    company = _company(db, "DDMDEFAULTS")
    _facts(
        db,
        company,
        {
            "dividend_per_share": 1.80,
            "shares_diluted": 100.0,
            "payout_ratio": 0.60,
            "eps": 3.00,
        },
    )
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    assert "dividend_growth_source" in result["publication_blockers"]
    assert "cost_of_equity_source" in result["publication_blockers"]
    assert result["publishable"] is False
    assert result["status"] == "partial"
    assert result["trace"]["notice"]
    assert result["expected_value"] is not None


def test_ddm_engine_refuses_a_company_that_pays_no_dividend(db):
    company = _company(db, "DDMNOPAY")
    _facts(db, company, {"shares_diluted": 100.0, "net_income": 200.0})
    _price(db, company, 12.0)
    context = DividendDiscountEngine().build_context(db, company, 12.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["dividend_per_share_or_payout_ratio"]
    assert result["base_value"] is None
    assert result["trace"]["dividend_input_contract"]
    assert result["publishable"] is False


def test_ddm_engine_refuses_when_cost_of_equity_does_not_clear_growth(db):
    company = _company(db, "DDMSPREAD")
    _facts(db, company, {**DDM_FACTS, "cost_of_equity": 0.02, "dividend_growth": 0.03})
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["cost_of_equity_above_dividend_growth"]


def test_ddm_engine_refuses_growth_above_the_return_on_equity(db):
    company = _company(db, "DDMROE")
    _facts(db, company, {**DDM_FACTS, "dividend_growth": 0.14, "roe": 0.12})
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["growth_below_return_on_equity"]


def test_ddm_engine_refuses_an_adr_without_a_ratio(db):
    company = _company(db, "DDMADR", tags=["adr"])
    _facts(db, company, DDM_FACTS)
    _price(db, company, 300.0)
    context = DividendDiscountEngine().build_context(db, company, 300.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["adr_ratio"]


def test_ddm_engine_converts_to_the_listed_share_for_an_adr_with_a_ratio(db):
    company = _company(db, "DDMADR8", tags=["adr:8"])
    _facts(db, company, DDM_FACTS)
    _price(db, company, 8.0 * 33.526369834189)
    context = DividendDiscountEngine().build_context(db, company, 8.0 * 33.526369834189)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "ok"
    assert result["adr_ratio"] == 8.0
    assert result["value_per_share_basis"] == "ordinary_share"
    assert result["listed_share_values"]["base"] == pytest.approx(
        result["base_value"] * 8.0
    )
    # The margin of safety is computed against the ORDINARY-share price.
    assert result["margin_of_safety"] == pytest.approx((result["expected_value"] - 33.526369834189) / result["expected_value"])


def test_fcfe_engine_publishes_the_bridge_and_never_subtracts_net_debt(db):
    company = _company(
        db, "FCFEHAPPY", company_type="insurer", valuation_model="fcfe_equity_value"
    )
    _facts(db, company, FCFE_FACTS)
    _price(db, company, 20.0)
    context = FreeCashFlowToEquityEngine().build_context(db, company, 20.0)
    result = FreeCashFlowToEquityEngine().value(context)
    # A retention derived from the payout is a weaker input than a stated
    # retention, so the valuation is computed but not publishable.
    assert "payout_ratio_source" in result["publication_blockers"]
    assert result["status"] == "partial"
    assert result["publishable"] is False
    bridge = result["fcfe"]["bridge"]
    # 300 - (120-60) + 15 - 8 = 300 - 60 + 7 = 247
    assert bridge["fcfe"] == pytest.approx(247.0)
    assert bridge["net_reinvestment_subtracted"] == pytest.approx(60.0)
    assert result["fcfe"]["no_net_debt_subtracted"] is True
    sign_block = result["trace"]["assumptions"]["sign_normalisation"]
    assert sign_block["applied"] is True
    assert sign_block["capex_raw"] == -120.0
    assert sign_block["capex_used"] == 120.0
    assert result["bear_value"] <= result["base_value"] <= result["bull_value"]
    assert len(result["sensitivity"]["rows"]) == 3
    assert result["trace"]["no_net_debt_subtracted"] is True
    assert result["trace"]["assumptions"]["retention_source"] == "derived_from_payout"
    assert result["trace"]["assumptions"]["roe"] == 0.15
    assert result["reverse_dcf"] == {}


def test_fcfe_engine_names_every_missing_bridge_term(db):
    company = _company(db, "FCFEMISS")
    _facts(db, company, {"net_income": 300.0, "shares_diluted": 100.0})
    _price(db, company, 20.0)
    context = FreeCashFlowToEquityEngine().build_context(db, company, 20.0)
    result = FreeCashFlowToEquityEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == [
        "capex",
        "depreciation_amortization",
        "delta_total_debt_or_total_debt_pair",
        "delta_working_capital_or_working_capital_pair",
    ]
    assert result["trace"]["fcfe_input_contract"]["formula"].startswith("FCFE =")


def test_fcfe_engine_needs_a_retention_policy(db):
    company = _company(db, "FCFERET")
    _facts(
        db,
        company,
        {key: value for key, value in FCFE_FACTS.items() if key not in ("payout_ratio",)},
    )
    _price(db, company, 20.0)
    context = FreeCashFlowToEquityEngine().build_context(db, company, 20.0)
    result = FreeCashFlowToEquityEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["retention_ratio_or_payout_ratio"]


def test_fcfe_engine_derives_the_debt_delta_from_two_balance_sheet_instants(db):
    """Providers report the two readings more often than the difference.

    total_debt 900 (FY2025) and 850 (FY2024) is Δdebt = +50, the same number a
    stored ``delta_total_debt`` fact would carry, and the trace says which
    route was taken.
    """
    company = _company(db, "FCFEDERIVE")
    facts = {
        key: value
        for key, value in FCFE_FACTS.items()
        if key not in ("delta_total_debt", "delta_working_capital")
    }
    _facts(db, company, facts)
    _facts(db, company, {"total_debt_prior_period": 850.0}, period="FY2024", fiscal_year=2024)
    _facts(
        db,
        company,
        {"working_capital": 120.0, "working_capital_prior_period": 100.0},
    )
    _facts(
        db,
        company,
        {"working_capital_prior_period": 100.0},
        period="FY2024",
        fiscal_year=2024,
    )
    _price(db, company, 20.0)
    context = FreeCashFlowToEquityEngine().build_context(db, company, 20.0)
    result = FreeCashFlowToEquityEngine().value(context)
    assumptions = result["trace"]["assumptions"]
    assert assumptions["delta_total_debt"] == pytest.approx(50.0)
    assert assumptions["delta_total_debt_source"] == "derived_from_two_instants"
    assert assumptions["delta_working_capital"] == pytest.approx(20.0)
    assert assumptions["delta_working_capital_source"] == "derived_from_two_instants"


def test_fcfe_engine_uses_a_sourced_traceable_wacc_when_there_is_one(db):
    company = _company(db, "FCFETRACE")
    _facts(db, company, FCFE_FACTS)
    _price(db, company, 20.0)
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric="wacc",
            value=Decimal("0.11"),
            unit="decimal",
            period=f"{FY}-12-31:FY",
            fiscal_year=FY,
            status="ok",
            definition_version="WACC_STANDARD_V1",
            formula="x",
        )
    )
    db.commit()
    context = FreeCashFlowToEquityEngine().build_context(db, company, 20.0)
    result = FreeCashFlowToEquityEngine().value(context)
    # A persisted WACC is the WACC, not a cost of equity fact: this engine
    # prefers the explicit cost_of_equity fact, so the WACC must NOT leak in.
    assert result["trace"]["assumptions"]["cost_of_equity"] == 0.10
    assert "cost_of_equity_source" not in result["publication_blockers"]


def test_fcfe_engine_negates_the_cash_flow_change_in_working_capital(db):
    """``change_in_working_capital`` se guarda en signo de flujo de caja
    (FMP ``changeInWorkingCapital``: −8 = el circulante absorbió 8 de caja).
    El puente FCFE resta un AUMENTO del circulante (+8), así que el hecho se
    niega antes de entrar: mismo FCFE que con ``delta_working_capital`` = 8.

        300 - (120 - 60) + 15 - 8 = 247
    """
    company = _company(
        db, "FCFECFWC", company_type="insurer", valuation_model="fcfe_equity_value"
    )
    facts = {key: value for key, value in FCFE_FACTS.items() if key != "delta_working_capital"}
    facts["change_in_working_capital"] = -8.0
    _facts(db, company, facts)
    _price(db, company, 20.0)
    context = FreeCashFlowToEquityEngine().build_context(db, company, 20.0)
    result = FreeCashFlowToEquityEngine().value(context)

    assert result["fcfe"]["bridge"]["fcfe"] == pytest.approx(247.0)
    assumptions = result["trace"]["assumptions"]
    assert assumptions["delta_working_capital"] == pytest.approx(8.0)
    assert assumptions["delta_working_capital_source"] == "negated_cash_flow_change_in_working_capital"


def test_ddm_derives_dps_from_dividends_paid_over_shares_traceably(db):
    """Sin hecho dividend_per_share: DPS = abs(dividends_paid)/shares_diluted.

    Derivacion trazable: la fuente queda marcada como derivada, la traza
    publica la formula y los dos componentes con su hecho, y la publicacion
    queda bloqueada (derivado, no declarado), igual que el payout derivado.
    dividends_paid = 180 USD y 100 acciones -> DPS 1,80, el mismo camino
    feliz que el D0 declarado: base 30,90 (aritmetica del test happy-path).
    """
    facts = {k: v for k, v in DDM_FACTS.items() if k != "dividend_per_share"}
    facts["dividends_paid"] = 180.0
    company = _company(db, "DDMDERIVED")
    _facts(db, company, facts)
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    # Con la derivacion la cifra sale igual, pero el estado ya no es "ok"
    # limpio: hay bloqueo de publicacion (derivado, no declarado).
    assert result["status"] == "partial"
    assert result["base_value"] == pytest.approx(30.90, abs=1e-9)
    assumptions = result["trace"]["assumptions"]
    assert assumptions["dividend_per_share_d0"] == pytest.approx(1.80)
    assert assumptions["dividend_source"] == "derived_dividends_paid_over_shares"
    derivation = assumptions["dividend_per_share_derivation"]
    assert derivation["formula"] == "abs(dividends_paid) / shares_diluted"
    assert derivation["dividends_paid"] is not None
    assert derivation["shares_diluted"] is not None
    assert "dividend_per_share_source" in result["publication_blockers"]
    assert result["publishable"] is False


def test_ddm_derives_dps_from_negative_cashflow_dividends(db):
    """El cash-flow SEC reporta dividendos pagados en negativo: abs()."""
    facts = {k: v for k, v in DDM_FACTS.items() if k != "dividend_per_share"}
    facts["dividends_paid"] = -180.0
    company = _company(db, "DDMDERNEG")
    _facts(db, company, facts)
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "partial"
    assert result["trace"]["assumptions"]["dividend_per_share_d0"] == pytest.approx(1.80)
    assert result["trace"]["assumptions"]["dividend_source"] == "derived_dividends_paid_over_shares"


def test_ddm_without_dividend_fact_nor_derivation_stays_insufficient(db):
    """Ni dividend_per_share ni dividends_paid: el rechazo de siempre."""
    facts = {k: v for k, v in DDM_FACTS.items() if k != "dividend_per_share"}
    company = _company(db, "DDMNODIV")
    _facts(db, company, facts)
    _price(db, company, 30.0)
    context = DividendDiscountEngine().build_context(db, company, 30.0)
    result = DividendDiscountEngine().value(context)

    assert result["status"] == "insufficient_data"
    assert "dividend_per_share_or_payout_ratio" in result["missing_inputs"]
