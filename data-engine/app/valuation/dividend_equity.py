"""Pure dividend-discount (DDM) and free-cash-flow-to-equity (FCFE) primitives.

No DB, no company, no engine: every function here is a function of its
arguments, so a test can check the formula against a value computed by hand
instead of against the module's own output.

Why a module of its own
-----------------------

**FCFE already IS the equity value.** ``FCFE`` is cash flow *after* interest,
*after* net borrowing and *after* the reinvestment the payout policy dictates,
so the present value of the FCFE stream is the value of the **equity**
directly. Subtracting net debt from it is the classic double count: the debt
was already paid out of the flow (``Δdebt`` enters the bridge) and is already
in the ``ke`` discount rate. ``run_fcfe`` therefore returns
``equity_value`` and never accepts a net-debt bridge at all; it accepts
``total_debt`` only as a disclosure, and
``reconcile_fcfe_against_dividend_model`` proves the point: with retention
``b = 0``, ``Δdebt = 0`` and ``ΔWC = 0`` the FCFE value collapses exactly onto
``D1/(ke - g)``, the Gordon price.

The arithmetic the module is built around
-----------------------------------------

In a permanent regime the Gordon growth model is

    P = D1 / (ke - g)                                              (1)

and the earnings side of the *same* statement is the justified forward P/E

    P/E1 = payout / (ke - g)   , valid only while g = ROE * (1 - payout)  (2)

(2) is not a free-standing valuation: it is (1) rewritten. With book value
growing at ``g`` (``g = ROE * (1 - payout)``), ``EPS1 = BV1 * ROE`` and
``BV1 = EPS1 / (ROE * (1 + g))`` give

    P = BV1 * (ROE - g)/(ke - g)
      = EPS1 * (ROE - g)/ROE / ((1 + g) * (ke - g))
      = EPS1 * payout / (ke - g)                                   (3)

using ``payout = 1 - g/ROE = (ROE - g)/ROE``. So (1) and (3) are the same
number, and the two ways disagree **only** when the observed dividend is not
``EPS1 * payout`` (a company paying out more or less than its policy) or when
``g > ROE`` (which no firm can do: growing the equity base faster than the
return on it is arithmetically impossible).

That disagreement is the product of this module. ``reconcile_dividend_model``
returns both legs, the residual, and the growth that *would* reconcile them,
so "my DDM says 42" can be audited into "my DDM says 42 because the dividend
is 1.80 growing 3% against a 9% ke — and if the payout were the company's
verifiable 60% of 3.00 EPS, it would say 37.50, and the 4.50 gap is the
dividend policy, not the discount rate".

Clamps
------

``ke - g`` is the whole model, so it is never repaired by clamping. ``ke <= g``
is refused, not fixed: the alternative is a perpetuity whose price is
infinite, negative, or a division by a number near zero, and all three are
numbers a reader would take seriously. What *is* clamped is the growth
assumption itself, which is a policy guess:

* ``d1`` (explicit-stage dividend growth) to ``[-0.10, +0.25]`` — above 25% a
  "dividend" is a new issue, and below -10% the company is cutting.
* ``g2`` (perpetual dividend growth) to a ``0.05`` ceiling — no perpetuity
  grows faster than long-run nominal GDP forever, and the floor is a
  dividend cut, not a decline. Every clamp applied is returned in the trace.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Explicit-stage dividend growth band. A dividend can be cut (negative d1) but
# a -10% annual cut for years is a liquidation, not a policy; above +25% the
# stream is not a dividend policy at all.
STAGE1_GROWTH_FLOOR = -0.10
STAGE1_GROWTH_CEILING = 0.25
# Perpetual dividend growth ceiling: above long-run nominal GDP forever is an
# assumption with no referent, not a forecast.
STAGE2_GROWTH_CEILING = 0.05
STAGE2_GROWTH_FLOOR = -0.05
# The minimum (ke - g2) spread. Below ~50bp the perpetuity is a coin flip
# multiplied by a number that happens to be large; the module refuses rather
# than reporting a value that is a rounding artifact of the spread.
MIN_COST_OF_EQUITY_SPREAD = 0.005
# A payout above 100% is not sustainable forever (earnings are finite); it is
# accepted for the explicit stage and refused as a steady-state policy.
MAX_STEADY_STATE_PAYOUT = 1.05


class DdmInputError(ValueError):
    """An input that makes the model meaningless, carrying the name to fix.

    The engines translate this into ``insufficient_data`` with
    ``missing_inputs=[err.missing_input]``; the primitive never returns a
    number it cannot stand behind.
    """

    def __init__(self, missing_input: str, reason: str) -> None:
        super().__init__(reason)
        self.missing_input = missing_input
        self.reason = reason


@dataclass(frozen=True)
class DdmInputs:
    """Inputs of a multi-stage dividend discount model, per ordinary share.

    ``dividend_per_share`` is ``D0``, the last **declared annual** dividend per
    ordinary share. ``stage1_years == 0`` is a legal single-stage (pure
    Gordon) DDM, not a degenerate case: for a mature utility or a bank with
    no explicit forecast there is no stage 1 to project.
    """

    dividend_per_share: float
    cost_of_equity: float
    stage1_growth: float
    stage1_years: int
    stage2_growth: float
    payout_ratio: float | None = None
    eps: float | None = None
    return_on_equity: float | None = None
    shares_diluted: float = 0.0


@dataclass(frozen=True)
class DdmResult:
    value_per_share: float
    equity_value: float
    forecast: list[dict]
    trace: dict = field(default_factory=dict)


def clamp_stage1_growth(growth: float) -> tuple[float, bool]:
    raw = growth
    clamped = max(min(growth, STAGE1_GROWTH_CEILING), STAGE1_GROWTH_FLOOR)
    return clamped, clamped != raw


def clamp_stage2_growth(growth: float) -> tuple[float, bool]:
    raw = growth
    clamped = max(min(growth, STAGE2_GROWTH_CEILING), STAGE2_GROWTH_FLOOR)
    return clamped, clamped != raw


def gordon_value(dividend: float, cost_of_equity: float, growth: float) -> float:
    """``P = D1 / (ke - g)`` — the single-stage dividend discount model.

    This is the anchor every multi-stage DDM is measured against in
    ``trace``: it answers "what would this dividend be worth growing forever
    at ``g`` with nothing else changing", which is the one thing a reader can
    recompute on paper.
    """
    if cost_of_equity <= growth:
        raise DdmInputError(
            "cost_of_equity_above_dividend_growth",
            f"cost of equity {cost_of_equity:.4f} is not above dividend growth "
            f"{growth:.4f}: D/(ke - g) has no finite value (it is infinite at "
            "equality and negative above it).",
        )
    if 1 + cost_of_equity <= 0:
        raise DdmInputError(
            "cost_of_equity_above_minus_one",
            f"cost of equity {cost_of_equity:.4f} <= -1 makes (1 + ke) ** t "
            "alternate in sign, so the discount factors are not a discount.",
        )
    return dividend * (1 + growth) / (cost_of_equity - growth)


def reconcile_dividend_model(
    *,
    dividend_per_share: float,
    cost_of_equity: float,
    terminal_growth: float,
    payout_ratio: float | None = None,
    eps: float | None = None,
    return_on_equity: float | None = None,
) -> dict:
    """Expose the Gordon/justified-P-E identity, both legs and the residual.

    Returns a dict with the two derivations of the same steady-state price, the
    gap between them, and the growth rate that would make them agree. A reader
    can check every number here with a calculator, which is the whole point:
    the reconciliation is the audit trail, not a decorative field.
    """
    gordon = gordon_value(dividend_per_share, cost_of_equity, terminal_growth)
    dividend_next_year = dividend_per_share * (1 + terminal_growth)
    leg: dict = {
        "dividend_per_share_d0": dividend_per_share,
        "dividend_per_share_d1": dividend_next_year,
        "gordon_formula": "P = D1 / (ke - g)",
        "gordon_perpetuity_value": gordon,
        "cost_of_equity": cost_of_equity,
        "terminal_growth": terminal_growth,
        "cost_of_equity_minus_growth": cost_of_equity - terminal_growth,
    }
    if payout_ratio is None or eps is None:
        return {
            **leg,
            "justified_pe_formula": "P/E1 = payout / (ke - g), valid only while g = ROE * (1 - payout)",
            "payout_ratio": payout_ratio,
            "eps": eps,
            "justified_forward_pe": None,
            "eps_implied_value": None,
            "residual_per_share": None,
            "reconciles": None,
            "reconciliation_status": "not_available",
            "reconciliation_note": (
                "A verifiable payout ratio and EPS are required to rewrite the "
                "Gordon price as a justified P/E; without them the dividend leg "
                "is published alone and the identity is not claimed."
            ),
        }

    justified_pe = payout_ratio / (cost_of_equity - terminal_growth)
    eps_next_year = eps * (1 + terminal_growth)
    eps_implied = eps_next_year * justified_pe
    residual = gordon - eps_implied
    dividend_implied = eps_next_year * payout_ratio
    reconciliation_growth = (
        return_on_equity * (1 - payout_ratio) if return_on_equity is not None else None
    )
    return {
        **leg,
        "justified_pe_formula": "P/E1 = payout / (ke - g), valid only while g = ROE * (1 - payout)",
        "payout_ratio": payout_ratio,
        "eps": eps,
        "eps_next_year": eps_next_year,
        "justified_forward_pe": justified_pe,
        "eps_implied_value": eps_implied,
        "residual_per_share": residual,
        # The identity is exact, not approximate: with a constant ROE, a
        # constant payout and g = ROE * (1 - payout), both legs are the same
        # number. Anything left over is a policy gap, so the tolerance is
        # relative and tight.
        "reconciles": abs(residual) <= 1e-9 * max(1.0, abs(gordon)),
        "reconciliation_status": "ok" if abs(residual) <= 1e-9 * max(1.0, abs(gordon)) else "divergent",
        "sustainable_growth_at_payout": reconciliation_growth,
        "sustainable_growth_gap": (
            terminal_growth - reconciliation_growth
            if reconciliation_growth is not None
            else None
        ),
        "dividend_implied_by_payout": dividend_implied,
        "dividend_policy_gap": dividend_next_year - dividend_implied,
        "residual_decomposition": {
            "source": (
                "The Gordon price uses the observed dividend; the justified-P/E "
                "price uses EPS * payout. The gap is entirely the dividend "
                "policy difference and is independent of ke and g, which cancel."
            ),
            "formula": "residual = (D1 - EPS1 * payout) / (ke - g)",
        },
    }


def _validate_ddm(
    inputs: DdmInputs, growth: float, terminal: float, *, raw_growth: float, raw_terminal: float
) -> None:
    """Refusals, ordered from the most specific diagnosis to the arithmetic.

    The raw (unclamped) growth is what the spread is checked against: a clamp
    must never be able to rescue a case that is economically impossible, or
    ``ke = 9%`` with a ``g = 20%`` request would quietly become a valid model
    at ``g = 5%`` and the reader would never learn that the input they gave
    was not the input used. The order is deliberate:

    1. ``1 + ke <= 0`` — the discount factors are not a discount at all, and
       ``ke <= g`` would be true for every negative ``ke``, so this has to be
       seen first or every other message is wrong.
    2. ``g >= roe`` — growing the equity base faster than the return on it is
       arithmetically impossible, and it is a more useful message than "your
       spread is negative".
    3. ``ke <= g`` — the perpetuity is infinite or negative.
    4. the 50bp spread floor.
    5. the payout, and last the share count.
    """
    if 1 + inputs.cost_of_equity <= 0:
        raise DdmInputError(
            "cost_of_equity_above_minus_one",
            f"cost of equity {inputs.cost_of_equity:.4f} <= -1 makes (1 + ke) ** t "
            "alternate in sign, so the discount factors are not a discount.",
        )
    if inputs.return_on_equity is not None and raw_growth >= inputs.return_on_equity:
        raise DdmInputError(
            "growth_below_return_on_equity",
            f"stage-1 dividend growth {raw_growth:.4f} is not below return on equity "
            f"{inputs.return_on_equity:.4f}: the equity base cannot compound "
            "faster than the return on it.",
        )
    if inputs.return_on_equity is not None and raw_terminal >= inputs.return_on_equity:
        raise DdmInputError(
            "growth_below_return_on_equity",
            f"terminal dividend growth {raw_terminal:.4f} is not below return on equity "
            f"{inputs.return_on_equity:.4f}: growing the book value faster than "
            "its return on equity is arithmetically impossible, and dividing by "
            "the difference instead of refusing is how these models end up "
            "quoting a P/E of 400x as if it were information.",
        )
    if inputs.cost_of_equity <= raw_terminal:
        raise DdmInputError(
            "cost_of_equity_above_dividend_growth",
            f"cost of equity {inputs.cost_of_equity:.4f} is not above terminal "
            f"dividend growth {raw_terminal:.4f}: the perpetuity D/(ke - g) is not "
            "a finite price. The growth is not clamped to rescue this, because "
            "a clamp would hide that the input asked for is not the input used.",
        )
    if inputs.cost_of_equity <= terminal:
        raise DdmInputError(
            "cost_of_equity_above_dividend_growth",
            f"cost of equity {inputs.cost_of_equity:.4f} is not above terminal "
            f"dividend growth {terminal:.4f} after clamping.",
        )
    if inputs.cost_of_equity - terminal < MIN_COST_OF_EQUITY_SPREAD:
        raise DdmInputError(
            "cost_of_equity_spread_above_floor",
            f"cost of equity {inputs.cost_of_equity:.4f} minus terminal growth "
            f"{terminal:.4f} is below the {MIN_COST_OF_EQUITY_SPREAD:.3f} floor: "
            "the price would be a rounding artifact of the spread, not a value.",
        )
    if inputs.dividend_per_share <= 0:
        raise DdmInputError(
            "positive_dividend_per_share",
            f"dividend per share is {inputs.dividend_per_share}: a dividend "
            "discount model over a non-dividend-paying company is an invention, "
            "not a valuation.",
        )
    if inputs.stage1_years < 0:
        raise DdmInputError(
            "non_negative_stage1_years",
            f"stage1_years must be >= 0 (0 is a legal single-stage DDM), got {inputs.stage1_years}.",
        )
    if inputs.payout_ratio is not None and inputs.payout_ratio <= 0:
        raise DdmInputError(
            "positive_payout_ratio",
            f"payout ratio is {inputs.payout_ratio}: a non-positive payout cannot "
            "be reconciled against the dividend stream.",
        )
    if inputs.payout_ratio is not None and inputs.payout_ratio > MAX_STEADY_STATE_PAYOUT:
        raise DdmInputError(
            "payout_ratio_not_above_one",
            f"payout ratio {inputs.payout_ratio:.4f} is above "
            f"{MAX_STEADY_STATE_PAYOUT:.2f}: it is not a sustainable steady-state "
            "policy, so the perpetuity leg is not defined.",
        )
    if inputs.shares_diluted <= 0:
        raise DdmInputError(
            "positive_shares_diluted",
            f"shares_diluted is {inputs.shares_diluted}: there is no per-share value.",
        )


def run_ddm(inputs: DdmInputs) -> DdmResult:
    """Multi-stage dividend discount, per ordinary share.

    Stage 1 projects the declared dividend for ``stage1_years`` years at
    ``stage1_growth``; the perpetuity from the first dividend after that grows
    at ``stage2_growth``. ``stage1_years == 0`` degenerates cleanly to
    ``D0 * (1 + g2) / (ke - g2)``, the Gordon price, and the trace says so.
    """
    growth, growth_clamped = clamp_stage1_growth(inputs.stage1_growth)
    terminal, terminal_clamped = clamp_stage2_growth(inputs.stage2_growth)
    _validate_ddm(
        inputs,
        growth,
        terminal,
        raw_growth=inputs.stage1_growth,
        raw_terminal=inputs.stage2_growth,
    )

    schedule: list[dict] = []
    dividend = inputs.dividend_per_share
    present_value = 0.0
    for year in range(1, inputs.stage1_years + 1):
        dividend *= 1 + growth
        discount_factor = (1 + inputs.cost_of_equity) ** year
        pv = dividend / discount_factor
        present_value += pv
        schedule.append(
            {
                "year": year,
                "dividend_per_share": dividend,
                "discount_factor": discount_factor,
                "pv_dividend": pv,
                "stage": "explicit",
            }
        )

    next_dividend = dividend * (1 + terminal) if schedule else inputs.dividend_per_share * (1 + terminal)
    terminal_value = next_dividend / (inputs.cost_of_equity - terminal)
    terminal_discount = (1 + inputs.cost_of_equity) ** inputs.stage1_years
    pv_terminal = terminal_value / terminal_discount
    present_value += pv_terminal

    total = present_value
    equity_value = total * inputs.shares_diluted
    clamp_notes: list[str] = []
    if growth_clamped:
        clamp_notes.append(
            f"stage1_growth {inputs.stage1_growth:.4f} clamped to [{STAGE1_GROWTH_FLOOR}, "
            f"{STAGE1_GROWTH_CEILING}] -> {growth:.4f}"
        )
    if terminal_clamped:
        clamp_notes.append(
            f"stage2_growth {inputs.stage2_growth:.4f} clamped to [{STAGE2_GROWTH_FLOOR}, "
            f"{STAGE2_GROWTH_CEILING}] -> {terminal:.4f}"
        )

    return DdmResult(
        value_per_share=total,
        equity_value=equity_value,
        forecast=schedule,
        trace={
            "method": "multi_stage_dividend_discount",
            "inputs": {
                "dividend_per_share": inputs.dividend_per_share,
                "cost_of_equity": inputs.cost_of_equity,
                "stage1_growth": growth,
                "stage1_years": inputs.stage1_years,
                "stage2_growth": terminal,
                "payout_ratio": inputs.payout_ratio,
                "eps": inputs.eps,
                "return_on_equity": inputs.return_on_equity,
                "shares_diluted": inputs.shares_diluted,
            },
            "stage1_growth_clamped_from": inputs.stage1_growth if growth_clamped else None,
            "stage2_growth_clamped_from": inputs.stage2_growth if terminal_clamped else None,
            "clamp_notes": clamp_notes,
            "single_stage": inputs.stage1_years == 0,
            "terminal_dividend": next_dividend,
            "terminal_value": terminal_value,
            "pv_terminal_value": pv_terminal,
            "pv_explicit_dividends": present_value - pv_terminal,
            "pv_terminal_share_of_value": pv_terminal / total if total > 0 else None,
            "cost_of_equity_minus_terminal_growth": inputs.cost_of_equity - terminal,
            "gordon_value_same_growth": gordon_value(
                inputs.dividend_per_share, inputs.cost_of_equity, terminal
            ),
            "multi_stage_premium_over_gordon": (
                total - gordon_value(inputs.dividend_per_share, inputs.cost_of_equity, terminal)
            ),
            "no_net_debt_subtracted": True,
            "net_debt_note": (
                "FCFE and a dividend discount model both discount cash flow that "
                "is already after interest and net borrowing, so the result IS "
                "the equity value. Subtracting net debt here would count the debt "
                "twice."
            ),
        },
    )


@dataclass(frozen=True)
class FcfeInputs:
    """Inputs of a free-cash-flow-to-equity model.

    ``capex`` and ``depreciation_amortization`` are the **flows of the period**
    being projected, not the balance of the asset base. They are stored as
    reported, so a provider that signs capex as an outflow yields a negative
    ``capex`` and the bridge below stays correct either way (the term is
    ``capex - depreciation`` and flipping both signs flips nothing
    only if they share a convention — which is exactly why the engine refuses
    when only one of them is present).
    """

    net_income: float
    capex: float
    depreciation_amortization: float
    retention_ratio: float
    cost_of_equity: float
    stage1_growth: float
    stage1_years: int
    stage2_growth: float
    delta_total_debt: float = 0.0
    delta_working_capital: float = 0.0
    shares_diluted: float = 0.0
    total_debt: float | None = None
    net_debt: float | None = None
    return_on_equity: float | None = None


@dataclass(frozen=True)
class FcfeResult:
    equity_value: float
    value_per_share: float
    fcfe: float
    forecast: list[dict]
    trace: dict = field(default_factory=dict)


def fcfe_bridge(
    *,
    net_income: float,
    capex: float,
    depreciation_amortization: float,
    retention_ratio: float,
    delta_total_debt: float,
    delta_working_capital: float,
) -> dict:
    """``FCFE = NI - (capex - D&A) + Δdebt - ΔWC``, term by term.

    Definición estándar (CFA L2, «Free Cash Flow Valuation»: FCFE = NI + NCC -
    FCInv - WCInv + net borrowing). La reinversión neta se resta ENTERA: la
    parte financiada con deuda ya entra por ``Δdebt``. Antes se multiplicaba
    por ``(1 - b)`` con ``b`` = ratio de retención, lo que mezclaba la forma de
    Damodaran con ratio de DEUDA (que entonces no suma Δdebt) con la política
    de dividendos: con b = 1 la reinversión desaparecía y el FCFE salía igual
    al beneficio neto. ``retention_ratio`` se conserva solo como dato de
    traza; no cambia el FCFE de un ejercicio.

    Returned as a dict rather than a float so the engine can publish the whole
    bridge in the trace: the value of an FCFE model is entirely in the sign
    convention of its reinvestment and financing terms, and a single number
    hides it.
    """
    net_reinvestment = capex - depreciation_amortization
    fcfe = net_income - net_reinvestment + delta_total_debt - delta_working_capital
    return {
        "net_income": net_income,
        "capex": capex,
        "depreciation_amortization": depreciation_amortization,
        "net_reinvestment_capex_less_depreciation": net_reinvestment,
        "retention_ratio": retention_ratio,
        "net_reinvestment_subtracted": net_reinvestment,
        "delta_total_debt": delta_total_debt,
        "delta_working_capital": delta_working_capital,
        "fcfe": fcfe,
        "formula": "FCFE = NI - (capex - D&A) + delta_total_debt - delta_working_capital",
    }


def reconcile_fcfe_against_dividend_model(
    *,
    fcfe: float,
    net_income: float,
    retention_ratio: float,
    delta_total_debt: float,
    delta_working_capital: float,
    cost_of_equity: float,
    terminal_growth: float,
    net_reinvestment_capex_less_depreciation: float | None = None,
) -> dict:
    """Show that FCFE is the Gordon model plus a reinvestment/financing bridge.

    With ``capex = D&A``, ``Δdebt = 0`` and ``ΔWC = 0`` the FCFE stream equals
    net income, so the FCFE value must equal ``D1/(ke - g)``. (La condición
    ``retention_ratio_is_zero`` se mantiene por compatibilidad de la traza; la
    que de verdad cuenta es ``net_reinvestment_capex_less_depreciation == 0``.)
    Every deviation of the real inputs from those conditions is a named,
    quantified reason the two engines disagree — which is the answer to "why
    do my DDM and my FCFE say different things", instead of two numbers with
    no relation between them.
    """
    fcfe_price = gordon_value(fcfe, cost_of_equity, terminal_growth)
    pure_ddm_price = gordon_value(net_income, cost_of_equity, terminal_growth)
    bridge_gap = fcfe - net_income
    conditions = {
        "retention_ratio_is_zero": retention_ratio == 0,
        "delta_total_debt_is_zero": delta_total_debt == 0,
        "delta_working_capital_is_zero": delta_working_capital == 0,
    }
    return {
        "fcfe_per_share_perpetuity": fcfe_price,
        "net_income_gordon_price": pure_ddm_price,
        "bridge_gap_per_share": fcfe_price - pure_ddm_price,
        "fcfe_minus_net_income": bridge_gap,
        "bridge_formula": "FCFE - NI = -(capex - D&A) + delta_total_debt - delta_working_capital",
        "net_reinvestment_capex_less_depreciation": net_reinvestment_capex_less_depreciation,
        "identity_conditions": conditions,
        "identity_holds": all(conditions.values()),
        "identity_note": (
            "FCFE collapses onto the Gordon dividend price when nothing is "
            "retained and nothing is financed: b = 0, Δdebt = 0, ΔWC = 0. The "
            "engine discounts at ke because the stream is after interest, so "
            "the debt is priced once (in ke), never subtracted again."
        ),
    }


def _validate_fcfe(
    inputs: FcfeInputs, growth: float, terminal: float, *, raw_growth: float, raw_terminal: float
) -> None:
    """Same refusal order as ``_validate_ddm``; see that docstring."""
    if 1 + inputs.cost_of_equity <= 0:
        raise DdmInputError(
            "cost_of_equity_above_minus_one",
            f"cost of equity {inputs.cost_of_equity:.4f} <= -1 makes the discount "
            "factors alternate in sign.",
        )
    if inputs.return_on_equity is not None:
        # The same impossibility as in the DDM: a growing equity base cannot
        # compound faster than the return it earns on itself. For FCFE the
        # stream is the cash left after that return, so an unachievable
        # growth rate is a claim about a business that does not exist.
        if raw_growth >= inputs.return_on_equity:
            raise DdmInputError(
                "growth_below_return_on_equity",
                f"stage-1 FCFE growth {raw_growth:.4f} is not below return on equity "
                f"{inputs.return_on_equity:.4f}: the equity base cannot compound "
                "faster than the return on it.",
            )
        if raw_terminal >= inputs.return_on_equity:
            raise DdmInputError(
                "growth_below_return_on_equity",
                f"terminal FCFE growth {raw_terminal:.4f} is not below return on equity "
                f"{inputs.return_on_equity:.4f}: the book value cannot grow "
                "faster than its own return, and dividing by the difference "
                "instead of refusing is how these models end up quoting a P/E "
                "of 400x as if it were information.",
            )
    if inputs.cost_of_equity <= raw_terminal:
        raise DdmInputError(
            "cost_of_equity_above_dividend_growth",
            f"cost of equity {inputs.cost_of_equity:.4f} is not above terminal "
            f"growth {raw_terminal:.4f}: the FCFE perpetuity is not a finite price. "
            "The growth is not clamped to rescue this.",
        )
    if inputs.cost_of_equity <= terminal:
        raise DdmInputError(
            "cost_of_equity_above_dividend_growth",
            f"cost of equity {inputs.cost_of_equity:.4f} is not above terminal "
            f"growth {terminal:.4f} after clamping.",
        )
    if inputs.cost_of_equity - terminal < MIN_COST_OF_EQUITY_SPREAD:
        raise DdmInputError(
            "cost_of_equity_spread_above_floor",
            f"cost of equity {inputs.cost_of_equity:.4f} minus terminal growth "
            f"{terminal:.4f} is below the {MIN_COST_OF_EQUITY_SPREAD:.3f} floor.",
        )
    if not 0 <= inputs.retention_ratio <= 1:
        raise DdmInputError(
            "retention_ratio_in_zero_one",
            f"retention ratio is {inputs.retention_ratio}: it is a share of "
            "earnings, so it must be in [0, 1].",
        )
    if inputs.stage1_years < 0:
        raise DdmInputError(
            "non_negative_stage1_years",
            f"stage1_years must be >= 0, got {inputs.stage1_years}.",
        )
    if inputs.shares_diluted <= 0:
        raise DdmInputError(
            "positive_shares_diluted",
            f"shares_diluted is {inputs.shares_diluted}: there is no per-share value.",
        )


def run_fcfe(inputs: FcfeInputs) -> FcfeResult:
    """FCFE model. The result is the **equity** value; net debt is never subtracted."""
    growth, growth_clamped = clamp_stage1_growth(inputs.stage1_growth)
    terminal, terminal_clamped = clamp_stage2_growth(inputs.stage2_growth)
    _validate_fcfe(
        inputs,
        growth,
        terminal,
        raw_growth=inputs.stage1_growth,
        raw_terminal=inputs.stage2_growth,
    )

    bridge = fcfe_bridge(
        net_income=inputs.net_income,
        capex=inputs.capex,
        depreciation_amortization=inputs.depreciation_amortization,
        retention_ratio=inputs.retention_ratio,
        delta_total_debt=inputs.delta_total_debt,
        delta_working_capital=inputs.delta_working_capital,
    )
    base_fcfe = float(bridge["fcfe"])

    schedule: list[dict] = []
    fcfe = base_fcfe
    present_value = 0.0
    for year in range(1, inputs.stage1_years + 1):
        fcfe *= 1 + growth
        discount_factor = (1 + inputs.cost_of_equity) ** year
        pv = fcfe / discount_factor
        present_value += pv
        schedule.append(
            {
                "year": year,
                "fcfe": fcfe,
                "discount_factor": discount_factor,
                "pv_fcfe": pv,
                "stage": "explicit",
            }
        )

    terminal_fcfe = fcfe * (1 + terminal) if schedule else base_fcfe * (1 + terminal)
    terminal_value = terminal_fcfe / (inputs.cost_of_equity - terminal)
    terminal_discount = (1 + inputs.cost_of_equity) ** inputs.stage1_years
    pv_terminal = terminal_value / terminal_discount
    present_value += pv_terminal

    reconciliation = reconcile_fcfe_against_dividend_model(
        fcfe=base_fcfe,
        net_income=inputs.net_income,
        retention_ratio=inputs.retention_ratio,
        delta_total_debt=inputs.delta_total_debt,
        delta_working_capital=inputs.delta_working_capital,
        cost_of_equity=inputs.cost_of_equity,
        terminal_growth=terminal,
        net_reinvestment_capex_less_depreciation=bridge["net_reinvestment_capex_less_depreciation"],
    )

    clamp_notes: list[str] = []
    if growth_clamped:
        clamp_notes.append(
            f"stage1_growth {inputs.stage1_growth:.4f} clamped to {growth:.4f}"
        )
    if terminal_clamped:
        clamp_notes.append(
            f"stage2_growth {inputs.stage2_growth:.4f} clamped to {terminal:.4f}"
        )

    return FcfeResult(
        equity_value=present_value * inputs.shares_diluted,
        value_per_share=present_value,
        fcfe=base_fcfe,
        forecast=schedule,
        trace={
            "method": "free_cash_flow_to_equity",
            "inputs": {
                "net_income": inputs.net_income,
                "capex": inputs.capex,
                "depreciation_amortization": inputs.depreciation_amortization,
                "retention_ratio": inputs.retention_ratio,
                "cost_of_equity": inputs.cost_of_equity,
                "stage1_growth": growth,
                "stage1_years": inputs.stage1_years,
                "stage2_growth": terminal,
                "delta_total_debt": inputs.delta_total_debt,
                "delta_working_capital": inputs.delta_working_capital,
                "shares_diluted": inputs.shares_diluted,
                "return_on_equity": inputs.return_on_equity,
            },
            "bridge": bridge,
            "stage1_growth_clamped_from": inputs.stage1_growth if growth_clamped else None,
            "stage2_growth_clamped_from": inputs.stage2_growth if terminal_clamped else None,
            "clamp_notes": clamp_notes,
            "single_stage": inputs.stage1_years == 0,
            "terminal_fcfe": terminal_fcfe,
            "terminal_value": terminal_value,
            "pv_terminal_value": pv_terminal,
            "pv_explicit_fcfe": present_value - pv_terminal,
            "pv_terminal_share_of_value": pv_terminal / present_value
            if present_value > 0
            else None,
            "cost_of_equity_minus_terminal_growth": inputs.cost_of_equity - terminal,
            "equity_value": present_value * inputs.shares_diluted,
            "no_net_debt_subtracted": True,
            "net_debt_disclosure_only": inputs.net_debt,
            "total_debt_disclosure_only": inputs.total_debt,
            "net_debt_note": (
                "The FCFE stream is after interest and net borrowing, so its "
                "present value is already the equity value. net_debt / "
                "total_debt are carried as disclosure only; subtracting them "
                "would count the debt twice."
            ),
            "reconciliation": reconciliation,
        },
    )


def equity_method_sensitivity(
    *,
    dividend_or_fcfe: float,
    cost_of_equity: float,
    terminal_growth: float,
    growth_values: list[float] | None = None,
) -> dict:
    """Two-point-per-axis sensitivity for the single-stage (Gordon) leg.

    Rows are ``ke`` variations, columns are terminal-growth variations, each
    cell being the perpetuity price ``D1/(ke - g)``. Cells where ``ke <= g``
    are returned as ``None`` with ``"error": "cell_out_of_range"`` instead of
    being clamped: a cell that would need ``ke > g`` to exist must say so, the
    same way ``sensitivity_grid`` isolates a broken cell.
    """
    growths = growth_values or [
        max(terminal_growth - 0.01, STAGE2_GROWTH_FLOOR),
        terminal_growth,
        min(terminal_growth + 0.01, STAGE2_GROWTH_CEILING),
    ]
    costs = [cost_of_equity - 0.01, cost_of_equity, cost_of_equity + 0.01]
    rows: list[dict] = []
    for cost in costs:
        cells: list[dict] = []
        for growth in growths:
            if cost <= growth or 1 + cost <= 0:
                cells.append(
                    {
                        "terminal_growth": growth,
                        "value_per_share": None,
                        "error": "cell_out_of_range",
                    }
                )
                continue
            cells.append(
                {
                    "terminal_growth": growth,
                    "value_per_share": gordon_value(dividend_or_fcfe, cost, growth),
                }
            )
        rows.append({"cost_of_equity": cost, "values": cells})
    return {"rows": rows, "trace": {"method": "equity_method_gordon_sensitivity"}}


def ddm_sensitivity_rows(
    *,
    dividend_per_share: float,
    cost_of_equity: float,
    terminal_growth: float,
    payout_ratio: float,
    stage1_years: int = 0,
) -> dict:
    """3-row 1-D table on ``ke`` (-100bp / base / +100bp) of the full model.

    ``ke`` is the input a reader wants to stress: the dividend and the growth
    policy are facts or explicit assumptions, but the cost of equity is the
    discount rate that turns them into a price. Each row carries its spread
    ``ke - g`` so a 96x blow-up between two adjacent rows is visible.
    """
    rows: list[dict] = []
    for label, cost in (
        ("low_cost_of_equity", cost_of_equity - 0.01),
        ("base_cost_of_equity", cost_of_equity),
        ("high_cost_of_equity", cost_of_equity + 0.01),
    ):
        try:
            value = run_ddm(
                DdmInputs(
                    dividend_per_share=dividend_per_share,
                    cost_of_equity=cost,
                    stage1_growth=terminal_growth,
                    stage1_years=stage1_years,
                    stage2_growth=terminal_growth,
                    payout_ratio=payout_ratio,
                    shares_diluted=1.0,
                )
            ).value_per_share
            rows.append(
                {
                    "scenario": label,
                    "cost_of_equity": cost,
                    "cost_of_equity_minus_growth": cost - terminal_growth,
                    "value_per_share": value,
                }
            )
        except DdmInputError as err:
            rows.append(
                {
                    "scenario": label,
                    "cost_of_equity": cost,
                    "cost_of_equity_minus_growth": cost - terminal_growth,
                    "value_per_share": None,
                    "error": err.missing_input,
                }
            )
    return {"rows": rows, "trace": {"method": "ddm_cost_of_equity_sensitivity"}}


def fcfe_sensitivity_rows(
    *,
    fcfe: float,
    cost_of_equity: float,
    terminal_growth: float,
) -> dict:
    """3-row 1-D table on ``ke`` of the FCFE perpetuity leg."""
    rows: list[dict] = []
    for label, cost in (
        ("low_cost_of_equity", cost_of_equity - 0.01),
        ("base_cost_of_equity", cost_of_equity),
        ("high_cost_of_equity", cost_of_equity + 0.01),
    ):
        try:
            rows.append(
                {
                    "scenario": label,
                    "cost_of_equity": cost,
                    "cost_of_equity_minus_growth": cost - terminal_growth,
                    "value_per_share": gordon_value(fcfe, cost, terminal_growth),
                }
            )
        except DdmInputError as err:
            rows.append(
                {
                    "scenario": label,
                    "cost_of_equity": cost,
                    "cost_of_equity_minus_growth": cost - terminal_growth,
                    "value_per_share": None,
                    "error": err.missing_input,
                }
            )
    return {"rows": rows, "trace": {"method": "fcfe_cost_of_equity_sensitivity"}}


def is_finite(value: float | None) -> bool:
    """Guard used by the engines before publishing a scenario value."""
    return value is not None and math.isfinite(value)


def solve_required_dividend_growth(
    *,
    market_price: float,
    dividend_per_share: float,
    cost_of_equity: float,
    stage2_growth: float,
    stage1_years: int = 0,
    payout_ratio: float | None = None,
    low: float = STAGE1_GROWTH_FLOOR,
    high: float = STAGE1_GROWTH_CEILING,
    iterations: int = 60,
) -> dict:
    """Reverse DDM: the dividend growth the current price requires.

    The product-level question behind every DDM is "what has to be true for
    this price?", and the honest answer is often "nothing a dividend can do" —
    so the search is bounded by the same growth band the model clamps to and
    saturates into ``out_of_bounds`` instead of reporting a growth rate that
    the clamp would never have accepted.
    """

    def price_at(growth: float) -> float | None:
        try:
            return run_ddm(
                DdmInputs(
                    dividend_per_share=dividend_per_share,
                    cost_of_equity=cost_of_equity,
                    stage1_growth=growth,
                    stage1_years=stage1_years,
                    stage2_growth=stage2_growth,
                    payout_ratio=payout_ratio,
                    shares_diluted=1.0,
                )
            ).value_per_share
        except DdmInputError:
            return None

    low_price = price_at(low)
    high_price = price_at(high)
    if low_price is None or high_price is None:
        return {
            "status": "not_computable",
            "out_of_bounds": True,
            "required_stage1_growth": None,
            "reason": (
                f"The growth band [{low}, {high}] is not valueable at this cost "
                f"of equity ({cost_of_equity}) and terminal growth ({stage2_growth})."
            ),
            "trace": {"method": "reverse_ddm", "low": low, "high": high},
        }
    if market_price > high_price:        return {
            "status": "out_of_bounds",
            "out_of_bounds": True,
            "required_stage1_growth": None,
            "reason": (
                f"The price {market_price:.4f} is above the {high_price:.4f} the "
                f"model reaches at its {high:.0%} growth ceiling: no dividend "
                "growth inside the modelled band reproduces it."
            ),
            "trace": {
                "method": "reverse_ddm",
                "low": low,
                "high": high,
                "value_at_low_growth": low_price,
                "value_at_high_growth": high_price,
            },
        }
    if market_price < low_price:
        return {
            "status": "out_of_bounds",
            "out_of_bounds": True,
            "required_stage1_growth": None,
            "reason": (
                f"The price {market_price:.4f} is below the {low_price:.4f} the "
                f"model reaches at its {low:.0%} growth floor: it implies "
                "dividend decline beyond anything the band models."
            ),
            "trace": {
                "method": "reverse_ddm",
                "low": low,
                "high": high,
                "value_at_low_growth": low_price,
                "value_at_high_growth": high_price,
            },
        }
    lo, hi = low, high
    for _ in range(iterations):
        mid = (lo + hi) / 2
        # Inside the validated band every growth is valueable, so a None here
        # would be a bug rather than an out-of-range input; skipping it keeps
        # the bisection moving towards the boundary instead of stalling.
        mid_price = price_at(mid)
        if mid_price is None or mid_price < market_price:
            lo = mid
        else:
            hi = mid
    return {
        "status": "ok",
        "out_of_bounds": False,
        "required_stage1_growth": (lo + hi) / 2,
        "required_growth_gap_vs_model_growth": (lo + hi) / 2 - stage2_growth,
        "trace": {
            "method": "reverse_ddm",
            "low": low,
            "high": high,
            "iterations": iterations,
            "value_at_low_growth": low_price,
            "value_at_high_growth": high_price,
        },
    }

