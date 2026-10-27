"""Pure regulated-asset (DASR) primitives for rate-regulated utilities.

No DB, no company, no engine. Everything below is a function of its arguments
so a test can check the identity with a hand calculation.

The framework and its derivation
--------------------------------

A rate-regulated utility is paid ``allowed_roe`` on a **regulatory rate base**
by a regulator, not a customer, so its earnings are a *function of the rate
base*, not of a demand curve. In permanent equilibrium:

* the regulator lets the company earn ``E = RB * allowed_roe`` on the
  **invested claim** ``B`` (see ``ALLOWED_ROE_CONVENTIONS`` for what ``B`` is:
  the whole base, or only its equity slice);
* the base is financed ``equity_ratio`` equity / ``(1 - equity_ratio)`` debt,
  so the *enterprise* capital requirement of the base is ``RB`` itself and the
  equity slice is ``RB * equity_ratio``; equivalently the enterprise capital
  requirement per unit of equity is ``1 / equity_ratio``. Writing ``EV`` for
  the enterprise requirement and ``Equity`` for the market value of the equity
  slice::

      EV  = RB / equity_ratio
      Equity = EV * equity_ratio = RB

  i.e. **the equity market value is not the book equity**: it is the book
  equity ``B`` plus the present value of the economic profit the allowed
  return earns over the cost of that equity;
* economic profit in period ``t`` is ``EP_t = (allowed_roe - ke) * B_{t-1}``,
  so with ``B`` growing at ``g``::

      V = B + Σ_{t>=1} EP_t / (1+ke)^t
        = B + (allowed_roe - ke) * B / (ke - g)                     (E)
        = B * (1 + (allowed_roe - ke) / (ke - g))

  At ``g = 0`` this collapses to ``B * allowed_roe / ke``, which is the
  "earnings capitalised at the cost of equity" form the utility literature
  quotes. **Both are the same statement**; (E) is the general one and the
  reader gets the ``g = 0`` special case in the trace.

**The convention is worth a factor of ``equity_ratio``.** Under
``whole_rate_base`` (``B = RB``) and ``equity_slice``
(``B = RB * equity_ratio``) the identity (E) is linear in ``B``, so the two
readings of the same rate case differ by exactly ``equity_ratio`` — two to
three times for a typical utility. The convention is therefore a required,
published input (``ALLOWED_ROE_CONVENTIONS``,
``CONVENTION_VALUE_RATIO_NOTE``) and is never inferred from the data.

The dividend cross-check
------------------------

The same equity value has to be reachable from the dividend, because that is
how the value is actually distributed: ``V = D1 / (ke - g)`` with
``D1 = B * allowed_roe * payout`` (``B`` is the OPENING book: year-1 earnings
are ``allowed_roe * B``, the same base the residual income ``(allowed_roe -
ke) * B`` of (E) is measured on; Penman, *Financial Statement Analysis and
Security Valuation*, residual income ``RI_t = E_t - ke * B_{t-1}``; CFA
Level II, Residual Income Valuation). Clean surplus with ``B`` growing at
``g`` gives ``D1 = E1 - g * B = B * (allowed_roe - g)``. Setting (E) equal to
the dividend leg gives

    payout = (allowed_roe - g) / allowed_roe = 1 - g / allowed_roe     (P)

which at ``g = 0`` is ``payout = 1`` and is exactly the sustainable-growth
condition ``g = (1 - payout) * allowed_roe``. ``P`` is
*not* an assumption to be satisfied: it is a diagnostic. A utility paying 70%
with a 2% allowed-ROE growth assumption is mis-modelled by exactly the
difference, and ``reconcile_regulated_asset_model`` returns that difference
instead of hiding it inside a single number.

The two legs also answer "why is the excess-return value the headline": the
dividend leg prices the payout policy and drops the retained earnings that
fund the rate base the value is supposed to grow with, so it is systematically
*different* from (E) unless (P) holds. Both are returned, reconciled, and the
residual is published.

The earning-power shortfall
---------------------------

The company earns ``allowed_roe`` on the **regulatory** base, never on its
accounting one. The whole reason a rate-case model exists is the gap between
the two: a company whose book equity is 40% of its rate base is levered
against a regulated return, and a company that books regulatory assets at
cost reports an accounting ROE unrelated to what the regulator actually
allows. ``earning_power_shortfall`` returns, term by term, the allowed
earnings, the reported earnings, and the difference — the product of the
engine, not a footnote.

Edge cases this module refuses instead of repairing
----------------------------------------------------

* ``allowed_roe < ke``: the regulated return does not cover the cost of the
  equity the base is financed with. The correct answer is a **negative** equity
  value (the base destroys the capital invested in it). The module returns it
  negative and flags it; it does not clamp to zero, because a zero would
  assert "worth exactly nothing" where the arithmetic says "worth less than
  the equity in it".
* ``equity_ratio`` outside ``(0, 1]``: not a capital structure.
* ``capex > depreciation`` while the rate base is frozen: the company is
  investing into a base the regulator is not letting it earn on. Value does
  not stagnate by accident — it stagnates *arithmetically*, because the model
  has no growth in the base. That is the warning this engine exists to raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Perpetual rate-base growth ceiling. A rate base compounding above long-run
# nominal GDP forever is not a regulatory outcome, it is a typo.
RATE_BASE_GROWTH_CEILING = 0.06
RATE_BASE_GROWTH_FLOOR = -0.03
# The perpetual leg needs a positive (ke - g) spread, with a floor: a 20bp
# spread turns a 1pp change in allowed ROE into a 6x change in value.
MIN_COST_OF_EQUITY_SPREAD = 0.005
# A payout must be a share of earnings.
MAX_PAYOUT = 1.05
# Regulatory lag is a share of the allowed return lost to under-recovery
# while a case is litigated; it is bounded because a permanent 100% under-
# recovery is a withdrawal of the licence, not a lag.
MAX_REGULATORY_LAG = 1.0
# Transition length cap, in years. Longer transitions than the rate case
# cycle are not a transition.
MAX_TRANSITION_YEARS = 20

ALLOWED_ROE_CONVENTIONS = {
    "whole_rate_base": (
        "allowed_roe is the allowed return on the WHOLE rate base, so the "
        "identity is run on the whole base: B = RB and E = RB * allowed_roe. "
        "The base is treated as the invested claim. Module default."
    ),
    "equity_slice": (
        "allowed_roe is the allowed return ON THE EQUITY SLICE (the US "
        "'allowed ROE' convention), so the identity is run on the equity "
        "slice only: B = RB * equity_ratio and E = RB * equity_ratio * "
        "allowed_roe."
    ),
}

#: The two conventions above describe the same regulator with two different
#: units, and the value per share differs between them by **exactly**
#: ``equity_ratio`` — a factor of two to three in a typical utility. That is
#: why the convention is a required, published input and never inferred.
CONVENTION_VALUE_RATIO_NOTE = (
    "V(equity_slice) = V(whole_rate_base) * equity_ratio exactly, because the "
    "identity V = B + (E - ke*B)/(ke - g) is linear in the book equity B and "
    "both B and E scale by equity_ratio. Choosing the wrong convention is "
    "therefore not a rounding error but a 2-3x valuation error, which is why "
    "it is an explicit input and is published in trace['allowed_roe_convention']."
)


class RegulatedAssetError(ValueError):
    """A regulated-asset input that makes the model meaningless, with its name."""

    def __init__(self, missing_input: str, reason: str) -> None:
        super().__init__(reason)
        self.missing_input = missing_input
        self.reason = reason


@dataclass(frozen=True)
class RegulatedAssetInputs:
    """Inputs of the rate-base model, all in absolute currency units.

    ``regulatory_base_growth`` is the growth the regulator is assumed to grant
    (rate cases plus growth in demand), and it is compared against what the
    company is actually spending: those two numbers agreeing is the condition
    under which the perpetual leg is not a fiction.
    """

    rate_base: float
    allowed_roe: float
    equity_ratio: float
    cost_of_equity: float
    shares_diluted: float
    payout_ratio: float
    regulatory_base_growth: float = 0.02
    book_rate_base: float | None = None
    transition_years: int = 0
    regulatory_lag: float = 0.0
    depreciation_rate: float | None = None
    depreciation_amortization: float | None = None
    capex: float | None = None
    rate_case_year: int | None = None
    allowed_roe_convention: str = "whole_rate_base"
    reported_net_income: float | None = None


@dataclass(frozen=True)
class RegulatedAssetResult:
    equity_value: float
    value_per_share: float
    enterprise_value: float
    book_equity: float
    allowed_earnings: float
    excess_return_pv: float
    forecast: list[dict]
    trace: dict = field(default_factory=dict)


def clamp_base_growth(growth: float) -> tuple[float, bool]:
    raw = growth
    clamped = max(min(growth, RATE_BASE_GROWTH_CEILING), RATE_BASE_GROWTH_FLOOR)
    return clamped, clamped != raw


def earning_power_shortfall(
    *,
    rate_base: float,
    equity_ratio: float,
    allowed_roe: float,
    reported_net_income: float | None,
    convention: str = "whole_rate_base",
) -> dict:
    """Allowed earnings vs reported earnings: the gap the rate case creates.

    This is the reason the engine exists. A company is allowed to earn
    ``allowed_roe`` on the **regulatory** base; what it actually reports is
    whatever its accounting base and its one-offs produce. The difference is
    either a catch-up (regulatory assets booked, deferred costs being
    recovered) or a permanent haircut, and the model needs to know which,
    because the perpetuity prices the *allowed* number while the investor pays
    today for the *reported* one.
    """
    equity_scale = 1.0 if convention == "whole_rate_base" else equity_ratio
    allowed_earnings = rate_base * allowed_roe * equity_scale
    if reported_net_income is None:
        return {
            "status": "not_available",
            "convention": convention,
            "allowed_earnings": allowed_earnings,
            "reported_net_income": None,
            "shortfall": None,
            "shortfall_pct_of_allowed": None,
            "reason": "No reported net income fact: the earning-power gap cannot be measured.",
        }
    shortfall = allowed_earnings - reported_net_income
    return {
        "status": "ok",
        "convention": convention,
        "allowed_roe": allowed_roe,
        "rate_base": rate_base,
        "equity_scale": equity_scale,
        "allowed_earnings": allowed_earnings,
        "reported_net_income": reported_net_income,
        "shortfall": shortfall,
        "shortfall_pct_of_allowed": shortfall / allowed_earnings if allowed_earnings else None,
        "formula": "allowed earnings = rate_base * allowed_roe * (1 if convention=whole_rate_base else equity_ratio)",
        "note": (
            "Positive shortfall = the company is earning less than the "
            "regulator allows (under-recovery, regulatory lag, prudence "
            "write-offs). Negative = it is ahead of the allowed return, which "
            "is temporary by construction: the next rate case claws it back."
        ),
    }


def excess_return_equity_value(
    *,
    book_equity: float,
    allowed_roe: float,
    cost_of_equity: float,
    growth: float,
) -> dict:
    """The (E) identity: book equity + PV of the excess return over ke.

    ``V = B * (1 + (allowed_roe - ke) / (ke - g))``. At ``g = 0`` this is
    ``B * allowed_roe / ke``, the "earnings capitalised at the cost of equity"
    form. Returns the two components separately so the trace can show which
    part of the price is the money already invested and which part is the
    regulator's promise.
    """
    if cost_of_equity <= growth:
        raise RegulatedAssetError(
            "cost_of_equity_above_base_growth",
            f"cost of equity {cost_of_equity:.4f} is not above rate-base growth "
            f"{growth:.4f}: the perpetuity has no finite value.",
        )
    spread = cost_of_equity - growth
    excess = (allowed_roe - cost_of_equity) * book_equity
    excess_pv = excess / spread
    total = book_equity + excess_pv
    return {
        "book_equity": book_equity,
        "excess_return_per_period": excess,
        "excess_return_pv": excess_pv,
        "equity_value": total,
        "cost_of_equity_minus_growth": spread,
        "value_creating": allowed_roe >= cost_of_equity,
        "formula": "V = book_equity + (allowed_roe - ke) * book_equity / (ke - g)",
        "gordon_special_case": (
            book_equity * allowed_roe / cost_of_equity if growth == 0 else None
        ),
    }


def reconcile_regulated_asset_model(
    *,
    rate_base: float,
    allowed_roe: float,
    equity_ratio: float,
    cost_of_equity: float,
    payout_ratio: float,
    growth: float,
    convention: str = "whole_rate_base",
) -> dict:
    """Excess-return leg vs dividend leg of the same equity value.

    ``(E)`` says ``V = B * (1 + (allowed_roe - ke)/(ke - g))``; Gordon on the
    distributed dividend says ``V = B * allowed_roe * payout / (ke - g)``
    (``D1`` is year-1 earnings on the opening book times the payout: no extra
    ``(1 + g)``). They are the same number **iff**
    ``payout = (allowed_roe - g) / allowed_roe``. The residual is
    returned explicitly, together with that reconciling payout, so a reader
    can tell a modelled utility from a mis-modelled one.
    """
    equity_scale = 1.0 if convention == "whole_rate_base" else equity_ratio
    book_equity = rate_base * equity_scale
    excess = excess_return_equity_value(
        book_equity=book_equity,
        allowed_roe=allowed_roe,
        cost_of_equity=cost_of_equity,
        growth=growth,
    )
    dividend_next = book_equity * allowed_roe * payout_ratio
    dividend_value = dividend_next / (cost_of_equity - growth)
    residual = excess["equity_value"] - dividend_value
    reconciling_payout = (
        (allowed_roe - growth) / allowed_roe if allowed_roe > 0 else None
    )
    return {
        "excess_return_leg": excess,
        "dividend_next_year": dividend_next,
        "dividend_leg_value": dividend_value,
        "dividend_leg_formula": "V = book_equity * allowed_roe * payout / (ke - g)",
        "residual": residual,
        "residual_pct_of_excess_leg": (
            residual / excess["equity_value"] if excess["equity_value"] else None
        ),
        "reconciling_payout": reconciling_payout,
        "actual_payout": payout_ratio,
        "payout_gap": payout_ratio - reconciling_payout if reconciling_payout is not None else None,
        "reconciles": abs(residual) <= 1e-9 * max(1.0, abs(excess["equity_value"])),
        "reconciliation_status": (
            "ok" if abs(residual) <= 1e-9 * max(1.0, abs(excess["equity_value"])) else "divergent"
        ),
        "note": (
            "payout = (allowed_roe - g) / allowed_roe is the only "
            "payout at which the regulatory promise and the distributed "
            "dividend are the same claim on the same cash. A utility that "
            "pays less is funding the rate base with retained earnings, and "
            "the gap is the growth it is actually buying."
        ),
    }


def validate_inputs(inputs: RegulatedAssetInputs, growth: float) -> None:
    if inputs.rate_base <= 0:
        raise RegulatedAssetError(
            "positive_rate_base",
            f"rate base is {inputs.rate_base}: a regulated asset base must be positive.",
        )
    if not 0 < inputs.equity_ratio <= 1:
        raise RegulatedAssetError(
            "equity_ratio_in_range",
            f"equity_ratio is {inputs.equity_ratio}: the capital structure "
            "share financed with equity must be in (0, 1].",
        )
    if inputs.shares_diluted <= 0:
        raise RegulatedAssetError(
            "positive_shares_diluted",
            f"shares_diluted is {inputs.shares_diluted}: there is no per-share value.",
        )
    if inputs.allowed_roe <= -1:
        raise RegulatedAssetError(
            "allowed_roe_above_minus_one",
            f"allowed_roe is {inputs.allowed_roe}: it is a return on capital, "
            "it cannot be at or below -100%.",
        )
    if inputs.cost_of_equity <= 0:
        raise RegulatedAssetError(
            "positive_cost_of_equity",
            f"cost of equity is {inputs.cost_of_equity}: a discount rate must be positive.",
        )
    if inputs.cost_of_equity <= growth:
        raise RegulatedAssetError(
            "cost_of_equity_above_base_growth",
            f"cost of equity {inputs.cost_of_equity:.4f} is not above rate-base "
            f"growth {growth:.4f}: the excess-return perpetuity is not finite.",
        )
    if inputs.cost_of_equity - growth < MIN_COST_OF_EQUITY_SPREAD:
        raise RegulatedAssetError(
            "cost_of_equity_spread_above_floor",
            f"cost of equity {inputs.cost_of_equity:.4f} minus base growth "
            f"{growth:.4f} is below the {MIN_COST_OF_EQUITY_SPREAD:.3f} floor: "
            "a spread that thin turns the value into a multiple of the spread.",
        )
    if not 0 < inputs.payout_ratio <= MAX_PAYOUT:
        raise RegulatedAssetError(
            "payout_ratio_in_range",
            f"payout_ratio is {inputs.payout_ratio}: it is a share of earnings "
            f"and must be in (0, {MAX_PAYOUT}].",
        )
    if not 0 <= inputs.regulatory_lag <= MAX_REGULATORY_LAG:
        raise RegulatedAssetError(
            "regulatory_lag_in_range",
            f"regulatory_lag is {inputs.regulatory_lag}: it is a share of the "
            "allowed return lost to under-recovery and must be in [0, "
            f"{MAX_REGULATORY_LAG}].",
        )
    if not 0 <= inputs.transition_years <= MAX_TRANSITION_YEARS:
        raise RegulatedAssetError(
            "transition_years_in_range",
            f"transition_years is {inputs.transition_years}: a convergence "
            f"path longer than {MAX_TRANSITION_YEARS} years is not a transition.",
        )
    if inputs.allowed_roe_convention not in ALLOWED_ROE_CONVENTIONS:
        raise RegulatedAssetError(
            "known_allowed_roe_convention",
            f"allowed_roe_convention {inputs.allowed_roe_convention!r} is not "
            f"one of {sorted(ALLOWED_ROE_CONVENTIONS)}.",
        )
    if inputs.book_rate_base is not None and inputs.book_rate_base <= 0:
        raise RegulatedAssetError(
            "positive_book_rate_base",
            f"book_rate_base is {inputs.book_rate_base}: the accounting asset "
            "base cannot be zero or negative while a rate base exists.",
        )


def frozen_base_warning(
    *,
    rate_base: float,
    capex: float | None,
    depreciation_rate: float | None,
    depreciation_amortization: float | None,
    growth: float,
) -> dict:
    """Flag a rate base that cannot physically grow at the modelled ``g``.

    A utility spending more on capex than it depreciates while the regulator
    holds the base flat is investing into assets it is not being paid to own.
    The model does not silently shrink ``g`` to match: the point of the
    warning is that the value stagnates and the reader has to decide whether
    the next rate case will grant the base or not.
    """
    if capex is None and depreciation_amortization is None and depreciation_rate is None:
        return {
            "status": "not_available",
            "warning": False,
            "reason": "No capex / depreciation fact: the base-growth assumption is unverifiable.",
        }
    capex_abs = abs(capex) if capex is not None else None
    depreciation = (
        depreciation_amortization
        if depreciation_amortization is not None
        else (rate_base * depreciation_rate if depreciation_rate is not None else None)
    )
    if capex_abs is None or depreciation is None:
        return {
            "status": "partial",
            "warning": False,
            "reason": (
                "capex without depreciation (or the reverse): the net investment "
                "in the base cannot be measured, so no growth warning is claimed."
            ),
        }
    net_investment = capex_abs - depreciation
    implied_growth = net_investment / rate_base
    warning = capex_abs > depreciation and implied_growth > growth
    return {
        "status": "ok",
        "warning": warning,
        "capex": capex_abs,
        "depreciation": depreciation,
        "net_investment_in_base": net_investment,
        "implied_base_growth": implied_growth,
        "modelled_base_growth": growth,
        "formula": "implied base growth = (capex - depreciation) / rate_base",
        "note": (
            "The company is reinvesting more than the regulator is letting its "
            "base grow at: the modelled value stagnates until a rate case "
            "grants the base. This is the warning the engine exists to raise."
        )
        if warning
        else "Reinvestment is consistent with (or below) the modelled base growth.",
    }


def run_regulated_asset(inputs: RegulatedAssetInputs) -> RegulatedAssetResult:
    """Rate-base model: allowed earnings on the regulatory base, priced at ``ke``.

    The headline value is the **excess-return (RAV) leg** of the (E) identity
    computed on the regulatory base, not the dividend leg, for one reason: the
    dividend leg prices the payout policy and silently drops the retained
    earnings that fund the rate base the value is supposed to grow with. Both
    legs are returned and reconciled, and the residual is the difference
    between them.

    Structure of the value, in this order, all of it in the trace:

    1. **Book equity** ``B0 = book_rate_base * convention_scale`` — the money
       already in the business.
    2. **Transition** (0 to ``transition_years`` years): the attainable book
       equity interpolates linearly from ``B0`` to the regulated book equity,
       and the allowed return is haircut by ``regulatory_lag``, decaying to
       zero at the end of the transition. The economic profit of year ``t`` is
       ``(roe_t - ke) * B_{t-1}``. The lag is an explicit input because that is
       what it is: under-recovery recovered with a delay, and the delay is the
       single most mispriced item in a utility model.
    3. **Perpetuity**: ``(allowed_roe - ke) * B_reg / (ke - g)`` discounted
       ``transition_years``, on the fully converged base.
    4. **Enterprise value** ``RB / equity_ratio``, whose ``equity_ratio`` share
       is the equity value above. The identity is published, not assumed.
    """
    growth, growth_clamped = clamp_base_growth(inputs.regulatory_base_growth)
    validate_inputs(inputs, growth)

    equity_scale = 1.0 if inputs.allowed_roe_convention == "whole_rate_base" else inputs.equity_ratio
    book_base = inputs.book_rate_base if inputs.book_rate_base is not None else inputs.rate_base
    book_equity_start = book_base * equity_scale
    book_equity_regulated = inputs.rate_base * equity_scale
    enterprise_requirement = inputs.rate_base / inputs.equity_ratio

    years = inputs.transition_years
    schedule: list[dict] = []
    pv_explicit_profit = 0.0
    previous_book = book_equity_start
    for year in range(1, years + 1):
        progress = year / years if years else 1.0
        base = book_base + (inputs.rate_base - book_base) * progress
        book_equity = base * equity_scale
        effective_roe = inputs.allowed_roe * (1 - inputs.regulatory_lag * (1 - progress))
        allowed = base * effective_roe
        economic_profit = (effective_roe - inputs.cost_of_equity) * previous_book
        discount = (1 + inputs.cost_of_equity) ** year
        pv = economic_profit / discount
        pv_explicit_profit += pv
        schedule.append(
            {
                "year": year,
                "convergence_progress": progress,
                "effective_earning_base": base,
                "effective_book_equity": book_equity,
                "effective_allowed_roe": effective_roe,
                "allowed_earnings": allowed,
                "economic_profit": economic_profit,
                "discount_factor": discount,
                "pv_economic_profit": pv,
                "stage": "transition",
            }
        )
        previous_book = book_equity

    converged_profit_per_period = (
        inputs.allowed_roe - inputs.cost_of_equity
    ) * book_equity_regulated
    terminal_excess_pv = converged_profit_per_period / (inputs.cost_of_equity - growth)
    pv_terminal = terminal_excess_pv / ((1 + inputs.cost_of_equity) ** years)
    equity_value = book_equity_start + pv_explicit_profit + pv_terminal
    value_per_share = equity_value / inputs.shares_diluted

    converged_earnings = inputs.rate_base * inputs.allowed_roe * equity_scale
    converged_dividend = converged_earnings * inputs.payout_ratio
    terminal_dividend = converged_dividend * (1 + growth)

    reconciliation = reconcile_regulated_asset_model(
        rate_base=inputs.rate_base,
        allowed_roe=inputs.allowed_roe,
        equity_ratio=inputs.equity_ratio,
        cost_of_equity=inputs.cost_of_equity,
        payout_ratio=inputs.payout_ratio,
        growth=growth,
        convention=inputs.allowed_roe_convention,
    )
    # The (E) identity is the price of the converged base with no transition.
    # Published separately so the trace never implies the two are the same
    # number, and so the cost of waiting for the rate case is visible.
    converged_value = reconciliation["excess_return_leg"]["equity_value"]
    shortfall = earning_power_shortfall(
        rate_base=inputs.rate_base,
        equity_ratio=inputs.equity_ratio,
        allowed_roe=inputs.allowed_roe,
        reported_net_income=inputs.reported_net_income,
        convention=inputs.allowed_roe_convention,
    )
    base_warning = frozen_base_warning(
        rate_base=inputs.rate_base,
        capex=inputs.capex,
        depreciation_rate=inputs.depreciation_rate,
        depreciation_amortization=inputs.depreciation_amortization,
        growth=growth,
    )
    value_destroying = inputs.allowed_roe < inputs.cost_of_equity
    negative_equity = equity_value < 0

    clamp_notes: list[str] = []
    if growth_clamped:
        clamp_notes.append(
            f"regulatory_base_growth {inputs.regulatory_base_growth:.4f} clamped to "
            f"[{RATE_BASE_GROWTH_FLOOR}, {RATE_BASE_GROWTH_CEILING}] -> {growth:.4f}"
        )

    return RegulatedAssetResult(
        equity_value=equity_value,
        value_per_share=value_per_share,
        enterprise_value=enterprise_requirement,
        book_equity=book_equity_start,
        allowed_earnings=converged_earnings,
        excess_return_pv=pv_explicit_profit + pv_terminal,
        forecast=schedule,
        trace={
            "method": "regulated_asset_dasr",
            "inputs": {
                "rate_base": inputs.rate_base,
                "allowed_roe": inputs.allowed_roe,
                "equity_ratio": inputs.equity_ratio,
                "cost_of_equity": inputs.cost_of_equity,
                "shares_diluted": inputs.shares_diluted,
                "payout_ratio": inputs.payout_ratio,
                "regulatory_base_growth": growth,
                "book_rate_base": book_base,
                "book_rate_base_source": "financial_facts"
                if inputs.book_rate_base is not None
                else "assumed_equal_to_rate_base",
                "transition_years": inputs.transition_years,
                "regulatory_lag": inputs.regulatory_lag,
                "depreciation_rate": inputs.depreciation_rate,
                "depreciation_amortization": inputs.depreciation_amortization,
                "capex": inputs.capex,
                "rate_case_year": inputs.rate_case_year,
                "allowed_roe_convention": inputs.allowed_roe_convention,
            },
            "allowed_roe_convention": ALLOWED_ROE_CONVENTIONS[inputs.allowed_roe_convention],
            "equity_value": equity_value,
            "value_per_share": value_per_share,
            "value_composition": {
                "book_equity": book_equity_start,
                "pv_transition_economic_profit": pv_explicit_profit,
                "pv_perpetuity_economic_profit": pv_terminal,
                "sum": book_equity_start + pv_explicit_profit + pv_terminal,
                "formula": (
                    "V = B0 + Σ_t (roe_t - ke) * B_{t-1} / (1+ke)^t + "
                    "(allowed_roe - ke) * B_reg / (ke - g) / (1+ke)^T"
                ),
            },
            "enterprise_value": enterprise_requirement,
            "enterprise_value_formula": "EV = rate_base / equity_ratio",
            "equity_value_identity": "Equity = EV * equity_ratio = rate_base * convention_scale",
            "book_equity": book_equity_start,
            "book_equity_start": book_equity_start,
            "book_equity_regulated": book_equity_regulated,
            "equity_slice_of_capital": inputs.rate_base * inputs.equity_ratio,
            "debt_slice_of_capital": inputs.rate_base * (1 - inputs.equity_ratio),
            "allowed_earnings_converged": converged_earnings,
            "allowed_earnings_formula": "allowed earnings = rate_base * allowed_roe * convention_scale",
            "dividend_converged": converged_dividend,
            "terminal_dividend": terminal_dividend,
            "excess_return_per_period_converged": converged_profit_per_period,
            "excess_return_pv_total": pv_explicit_profit + pv_terminal,
            "pv_terminal_value": pv_terminal,
            "pv_transition_economic_profit": pv_explicit_profit,
            "pv_terminal_share_of_value": (
                pv_terminal / equity_value if equity_value > 0 else None
            ),
            "cost_of_equity_minus_growth": inputs.cost_of_equity - growth,
            "regulatory_base_growth_clamped_from": (
                inputs.regulatory_base_growth if growth_clamped else None
            ),
            "clamp_notes": clamp_notes,
            "transition_years": years,
            "regulatory_lag_applied": inputs.regulatory_lag if years else 0.0,
            "regulatory_lag_note": (
                "Explicit input, not a hidden adjustment: the allowed return is "
                "haircut by regulatory_lag * (1 - progress) while the earning "
                "base converges, and is fully allowed once it has."
            ),
            "value_destroying_allowed_roe": value_destroying,
            "value_below_book_equity": value_destroying and equity_value < book_equity_start,
            "negative_equity_value": negative_equity,
            "negative_value_handling": (
                "reported_unclamped: when the allowed return does not cover the "
                "cost of the equity, or is negative outright, the excess-return "
                "identity returns a value at or below the equity invested and "
                "the model publishes it as it is. It is NOT clamped to zero, "
                "because zero would claim the regulated base is worth exactly "
                "the money in it when the arithmetic says it is worth less. "
                "See ReitValuationEngine's max(0, ...) for the case where a "
                "zero floor is genuine (an unlevered building cannot be worth "
                "less than nothing to equity while the debt is serviced); a "
                "regulated equity slice has no such floor."
            ),
            "excess_return_reconciliation": reconciliation,
            "converged_base_value": converged_value,
            "transition_value_uplift": equity_value - converged_value,
            "earning_power_shortfall": shortfall,
            "frozen_base_warning": base_warning,
            "forecast": schedule,
        },
    )


def regulated_asset_sensitivity(
    *,
    rate_base: float,
    allowed_roe: float,
    equity_ratio: float,
    cost_of_equity: float,
    shares_diluted: float,
    payout_ratio: float,
    growth: float,
    book_rate_base: float | None = None,
    transition_years: int = 0,
    regulatory_lag: float = 0.0,
    allowed_roe_convention: str = "whole_rate_base",
) -> dict:
    """3-row 1-D table on ``allowed_roe`` (-100bp / base / +100bp).

    ``allowed_roe`` is the input the whole model hangs on and the one a rate
    case moves: the 100bp cut in a downturn is the single most common reason a
    utility's value halves. Rows keep everything else at base, and each row
    carries its own sign of value creation so a negative row is self-labelling.
    """
    clamped_growth, _ = clamp_base_growth(growth)
    rows: list[dict] = []
    for label, roe in (
        ("allowed_roe_cut_100bp", allowed_roe - 0.01),
        ("base_allowed_roe", allowed_roe),
        ("allowed_roe_raised_100bp", allowed_roe + 0.01),
    ):
        try:
            result = run_regulated_asset(
                RegulatedAssetInputs(
                    rate_base=rate_base,
                    allowed_roe=roe,
                    equity_ratio=equity_ratio,
                    cost_of_equity=cost_of_equity,
                    shares_diluted=shares_diluted,
                    payout_ratio=payout_ratio,
                    regulatory_base_growth=clamped_growth,
                    book_rate_base=book_rate_base,
                    transition_years=transition_years,
                    regulatory_lag=regulatory_lag,
                    allowed_roe_convention=allowed_roe_convention,
                )
            )
            rows.append(
                {
                    "scenario": label,
                    "allowed_roe": roe,
                    "allowed_roe_minus_cost_of_equity": roe - cost_of_equity,
                    "value_creating": roe >= cost_of_equity,
                    "value_per_share": result.value_per_share,
                }
            )
        except RegulatedAssetError as err:
            rows.append(
                {
                    "scenario": label,
                    "allowed_roe": roe,
                    "value_per_share": None,
                    "error": err.missing_input,
                }
            )
    return {"rows": rows, "trace": {"method": "regulated_asset_allowed_roe_sensitivity"}}


def is_finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)
