"""Regulated-asset (DASR) engine for rate-regulated utilities.

The framework, the derivation of the (E) identity and every clamp live in
``app/valuation/regulated_asset.py``; this module resolves facts, builds the
regulatory scenarios, and publishes the trace.

Why a sector engine and not a DDM
---------------------------------

A utility's earnings are set by a regulator on an asset base, so a dividend
discount model on it prices the *payout policy* and says nothing about whether
the regulator will keep allowing that return. What the investor is really
underwriting is ``allowed_roe`` against ``ke`` and whether the rate base grows,
and that is what this engine models. ``trace["engine_precedence_note"]``
carries that statement so a reader arriving from the registry knows which
method produced the number.

Contracts (FinancialFact metric names)
--------------------------------------

=============================  =================================================
``rate_base``                  required (alias: ``regulated_asset_base``).
``allowed_roe``                required. Allowed return; see the conventions
                               note below for what it is a return *on*.
``equity_ratio``               required, in (0, 1].
``cost_of_equity``             required.
``shares_diluted``             required.
``payout_ratio``               required. There is no "assume 100% payout"
                               default: the retained share is what funds the
                               rate base, so it is an input, not a convenience.
``regulatory_base_growth``     required-ish: alias ``growth_rate``/``g``; tag
                               terminal growth as a declared fallback.
``book_rate_base``             optional. The accounting base the earning base
                               converges *from*; assumed equal to the rate base
                               when absent (declared in the trace).
``transition_years``           optional, default 0 (already converged).
``regulatory_lag``             optional, default 0. Explicit under-recovery
                               haircut, decaying over the transition.
``depreciation_rate`` /        optional. Used to measure whether capex is
``depreciation_amortization``  consistent with the modelled base growth.
``capex``                      optional (alias ``capital_expenditure``).
``net_income``                 optional. Enables the earning-power shortfall.
``rate_case_year``             optional. Disclosed for the case clock.
=============================  =================================================

The ``allowed_roe`` convention, stated rather than assumed
----------------------------------------------------------

The US "allowed ROE" is a return **on the equity slice**; the UK/EU
"allowed return" is a return on the **whole rate base**. Both exist, both are
selectable, and the one in use is published in
``trace["allowed_roe_convention"]``. The default is ``whole_rate_base``
(``B = RB``, ``E = RB * allowed_roe``). Because the identity (E) is linear in
the book equity ``B``, the two conventions differ by **exactly**
``equity_ratio`` in value per share — a two-to-three-times error in a typical
utility. An engine that hid this would misstate a US utility by a factor of
its own equity ratio and nobody would notice, because both numbers look
plausible.

Negative and below-book values are not clipped
----------------------------------------------

Two distinct regimes, both published:

* ``allowed_roe < ke`` → the regulated return does not cover the cost of the
  equity the base is financed with. The value is **below the equity invested**
  and the model says so (``value_below_book_equity``,
  ``value_destroying_allowed_roe``).
* ``allowed_roe < 0`` (a rate case set below cost, a negative settlement) → the
  identity itself returns a **negative** equity value. It is reported as it is
  (``negative_equity_value``) and never clamped to zero, because zero would
  claim the regulated base is worth exactly the money in it when the
  arithmetic says it is worth less.

(``ReitValuationEngine`` uses ``max(0, ...)`` because a REIT's NAV genuinely
has a zero floor: a building cannot be worth less than nothing to equity while
its debt is serviced. A regulated equity slice has no such floor.) Both
choices are recorded in ``trace["negative_value_handling"]``.
"""

from __future__ import annotations

from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    adr_ratio,
    apply_publication_blockers,
    context_split_cutoff,
    default_terminal_growth,
    default_wacc,
    insufficient_result,
    is_adr_without_ratio,
    margin_of_safety,
)
from app.valuation.fact_reference import (
    SourcedFact,
    fact_ids_and_periods,
    latest_facts,
    mean_confidence,
    provenance_trace,
    resolve_aliases,
)
from app.valuation.moat_framework import empty_moat_framework
from app.valuation.regulated_asset import (
    RegulatedAssetError,
    RegulatedAssetInputs,
    regulated_asset_sensitivity,
    run_regulated_asset,
)
from app.valuation.scenario_definitions import evidence_weighted_probabilities
from app.valuation.scenario_model import Scenario, probability_weighted_value

MODEL_INPUT_METRICS = frozenset(
    {
        "rate_base",
        "regulated_asset_base",
        "allowed_roe",
        "equity_ratio",
        "cost_of_equity",
        "shares_diluted",
        "payout_ratio",
        "regulatory_base_growth",
        "book_rate_base",
        "transition_years",
        "regulatory_lag",
        "depreciation_rate",
        "depreciation_amortization",
        "capex",
        "net_income",
        "rate_case_year",
    }
)

# Regulatory scenarios. The bear is a *regulatory* bear, not a growth bear: an
# allowed-ROE cut plus under-recovery, which is what actually happens to a
# utility in a downturn (and why the allowed ROE, not the demand curve, is the
# input to stress).
ALLOWED_ROE_BEAR_DELTA = -0.010
ALLOWED_ROE_BULL_DELTA = 0.005
KE_BEAR_DELTA = 0.010
KE_BULL_DELTA = -0.005
LAG_BEAR_DELTA = 0.15
LAG_BULL_DELTA = -0.10
TRANSITION_BEAR_YEARS = 2
TRANSITION_BULL_YEARS = 0

DEFAULT_TRANSITION_YEARS = 0

INPUT_ALIASES = {
    "rate_base": ("rate_base", "regulated_asset_base", "regulatory_asset_base"),
    "allowed_roe": ("allowed_roe", "allowed_return_on_equity", "roe_allowed"),
    "equity_ratio": ("equity_ratio", "equity_ratio_allowed", "regulatory_equity_ratio"),
    "cost_of_equity": ("cost_of_equity", "cost_of_equity_capm", "ke"),
    "shares_diluted": ("shares_diluted",),
    "payout_ratio": ("payout_ratio", "dividend_payout_ratio", "payout"),
    "regulatory_base_growth": (
        "regulatory_base_growth",
        "rate_base_growth",
        "growth_rate",
        "g",
    ),
    "book_rate_base": ("book_rate_base", "book_asset_base", "net_ppe"),
    "transition_years": ("transition_years", "rate_base_convergence_years"),
    "regulatory_lag": ("regulatory_lag", "under_recovery_lag", "regulatory_lag_years"),
    "depreciation_rate": ("depreciation_rate", "regulatory_depreciation_rate"),
    "depreciation_amortization": (
        "depreciation_amortization",
        "depreciation_and_amortization",
        "depreciation",
    ),
    "capex": ("capex", "capital_expenditure", "capex_plan"),
    "net_income": ("net_income", "profit_loss", "net_profit"),
    "rate_case_year": ("rate_case_year", "last_rate_case_year"),
    "allowed_roe_convention": ("allowed_roe_convention", "roe_convention"),
}

ENGINE_PRECEDENCE_NOTE = (
    "Utilities is a SECTOR method (the regulator sets the return on the rate "
    "base); DDM/FCFE are VALUATION methods (the payout policy sets the cash). "
    "A regulated utility that pays a dividend could be routed to either. The "
    "registry gives utilities precedence when the rate-base inputs exist, "
    "because the regulated return is the economically binding assumption, and "
    "falls back to DDM when they do not. The engine that actually ran is named "
    "in trace['engine']; the reason is trace['engine_precedence_note']."
)


def _insufficient(
    context: ValuationContext, *, missing: list[str], reason: str, extra_trace: dict | None = None
) -> dict:
    result = insufficient_result(
        ticker=context.company.ticker,
        model_type=context.company.valuation_model,
        engine_key=context.engine_key,
        current_price=context.current_price,
        missing_inputs=missing,
        reason=reason,
        snapshot=context.snapshot,
        extra_trace=extra_trace,
    )
    result["moat"] = empty_moat_framework(
        context.company.company_type,
        context.company.factor_tags or [],
        context.company.special_risks or [],
    )
    return result


class RegulatedUtilityEngine(ValuationEngine):
    """Rate-regulated utilities: value the rate base, not the demand curve.

    Value per share = PV of dividends on a base that converges from the
    accounting rate base to the regulatory one over ``transition_years`` (with
    the ``regulatory_lag`` haircut decaying over the same window), plus the
    perpetuity on the converged base. Sensitivity: 1-D on ``allowed_roe``
    (-100bp / base / +100bp), the input a rate case actually moves.
    """

    key = "utilities"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        model_type = company.valuation_model or "regulated_asset_dasr"
        snapshot = context.snapshot

        if is_adr_without_ratio(company):
            return _insufficient(
                context,
                missing=["adr_ratio"],
                reason=(
                    f"{company.ticker} is quoted as an ADR but the "
                    "ordinary-shares-per-ADR ratio is unknown, so the per-share "
                    "value and the quoted price are not on the same basis."
                ),
                extra_trace={"model_type": model_type, "engine": self.key},
            )

        raw = latest_facts(
            context.db,
            company.id,
            sorted({alias for group in INPUT_ALIASES.values() for alias in group}),
            cutoff=context_split_cutoff(context),
        )
        rows = resolve_aliases(raw, INPUT_ALIASES)

        missing: list[str] = []
        for name in (
            "rate_base",
            "allowed_roe",
            "equity_ratio",
            "cost_of_equity",
            "shares_diluted",
            "payout_ratio",
        ):
            if rows.get(name) is None:
                missing.append(name)

        if missing:
            return _insufficient(
                context,
                missing=missing,
                reason=(
                    "A regulated-asset valuation needs the rate base, the "
                    "allowed ROE, the allowed equity ratio, the cost of equity, "
                    "the payout ratio and diluted shares. None of them can be "
                    "assumed: an assumed allowed ROE is the whole valuation."
                ),
                extra_trace={
                    "dasr_input_contract": {
                        "rate_base": "rate_base or regulated_asset_base",
                        "allowed_roe": "allowed return; see trace['allowed_roe_convention']",
                        "equity_ratio": "allowed equity share of the capital structure, in (0, 1]",
                        "payout_ratio": "no default: retained earnings fund the rate base",
                        "regulatory_lag": "explicit under-recovery haircut, decaying over the transition",
                        "identity": "V = book_equity + (allowed_roe - ke) * book_equity / (ke - g)",
                    },
                    "engine_precedence_note": ENGINE_PRECEDENCE_NOTE,
                },
            )

        rate_base = float(rows["rate_base"].value)
        allowed_roe = float(rows["allowed_roe"].value)
        equity_ratio = float(rows["equity_ratio"].value)
        cost_of_equity, cost_source = self._cost_of_equity(context, rows)
        shares = float(rows["shares_diluted"].value)
        payout = float(rows["payout_ratio"].value)
        growth, growth_source = self._growth(context, rows)
        book_rate_base = float(rows["book_rate_base"].value) if rows.get("book_rate_base") else None
        transition_years, transition_source = self._transition_years(rows)
        regulatory_lag, lag_source = self._regulatory_lag(rows)
        convention = (
            str(rows["allowed_roe_convention"].value)
            if rows.get("allowed_roe_convention")
            else "whole_rate_base"
        )
        depreciation_rate = (
            float(rows["depreciation_rate"].value) if rows.get("depreciation_rate") else None
        )
        depreciation = (
            float(rows["depreciation_amortization"].value)
            if rows.get("depreciation_amortization")
            else None
        )
        capex = abs(float(rows["capex"].value)) if rows.get("capex") else None
        rate_case_year = int(rows["rate_case_year"].value) if rows.get("rate_case_year") else None
        net_income = float(rows["net_income"].value) if rows.get("net_income") else None

        blockers: list[str] = []
        if cost_source != "financial_facts":
            blockers.append("cost_of_equity_source")

        def build(roe: float, ke: float, lag: float, years: int) -> RegulatedAssetInputs:
            return RegulatedAssetInputs(
                rate_base=rate_base,
                allowed_roe=roe,
                equity_ratio=equity_ratio,
                cost_of_equity=ke,
                shares_diluted=shares,
                payout_ratio=payout,
                regulatory_base_growth=growth,
                book_rate_base=book_rate_base,
                transition_years=years,
                regulatory_lag=lag,
                depreciation_rate=depreciation_rate,
                depreciation_amortization=depreciation,
                capex=capex,
                rate_case_year=rate_case_year,
                allowed_roe_convention=convention,
                reported_net_income=net_income,
            )

        try:
            base_result = run_regulated_asset(build(allowed_roe, cost_of_equity, regulatory_lag, transition_years))
        except RegulatedAssetError as err:
            return _insufficient(
                context,
                missing=[err.missing_input],
                reason=err.reason,
                extra_trace={"engine_precedence_note": ENGINE_PRECEDENCE_NOTE},
            )

        specs = {
            "bear": {
                "allowed_roe": allowed_roe + ALLOWED_ROE_BEAR_DELTA,
                "cost_of_equity": cost_of_equity + KE_BEAR_DELTA,
                "regulatory_lag": min(regulatory_lag + LAG_BEAR_DELTA, 1.0),
                "transition_years": transition_years + TRANSITION_BEAR_YEARS,
                "driver": "regulatory_downturn_allowed_roe_cut_and_under_recovery",
            },
            "base": {
                "allowed_roe": allowed_roe,
                "cost_of_equity": cost_of_equity,
                "regulatory_lag": regulatory_lag,
                "transition_years": transition_years,
                "driver": "current_allowed_return_and_known_lag",
            },
            "bull": {
                "allowed_roe": allowed_roe + ALLOWED_ROE_BULL_DELTA,
                "cost_of_equity": cost_of_equity + KE_BULL_DELTA,
                "regulatory_lag": max(regulatory_lag + LAG_BULL_DELTA, 0.0),
                "transition_years": max(transition_years + TRANSITION_BULL_YEARS, 0),
                "driver": "rate_case_recovery_of_lagged_under_recovery",
            },
        }
        scenario_values: dict[str, float] = {}
        scenario_traces: dict[str, dict] = {}
        for name, spec in specs.items():
            try:
                outcome = run_regulated_asset(
                    build(
                        spec["allowed_roe"],
                        spec["cost_of_equity"],
                        spec["regulatory_lag"],
                        spec["transition_years"],
                    )
                )
            except RegulatedAssetError as err:
                # A regulatory scenario can fail validation when the bear cuts
                # allowed ROE below zero the model is willing to price. It is
                # revalued at base inputs and the substitution is published.
                outcome = base_result
                spec = {**spec, "substituted_base_inputs": err.missing_input}
                specs[name] = spec
            scenario_values[name] = outcome.value_per_share
            scenario_traces[name] = {
                "definition": {"name": name, "drivers": [spec["driver"]], "assumptions": spec},
                "value_per_share": outcome.value_per_share,
                "allowed_roe": spec["allowed_roe"],
                "allowed_roe_minus_cost_of_equity": spec["allowed_roe"] - spec["cost_of_equity"],
                "trace": outcome.trace,
            }

        if base_result.trace["value_destroying_allowed_roe"]:
            blockers.append("value_destroying_allowed_roe")
        if base_result.trace["negative_equity_value"]:
            blockers.append("negative_regulated_equity_value")
        if base_result.trace["frozen_base_warning"].get("warning"):
            blockers.append("rate_base_frozen_below_capex")
        if growth_source != "financial_facts":
            blockers.append("regulatory_base_growth_source")
        if lag_source == "policy_default" and transition_years > 0:
            # A zero lag only matters when there IS a transition to lag
            # through: with transition_years = 0 the under-recovery haircut is
            # inapplicable, and blocking every converged utility for a default
            # that changes nothing would be noise, not rigour.
            blockers.append("regulatory_lag_source")

        probabilities = evidence_weighted_probabilities(
            evidence_confidence=mean_confidence(
                fact for name, fact in rows.items() if name in MODEL_INPUT_METRICS
            ),
            directional_signal=max(
                -1.0, min(1.0, (allowed_roe - cost_of_equity) * 5.0 - regulatory_lag * 0.5)
            ),
            downside_risk=min(1.0, max(0.0, regulatory_lag)),
        )
        weighted = probability_weighted_value(
            [
                Scenario(name, probabilities[name], scenario_values[name])
                for name in ("bear", "base", "bull")
            ]
        )
        expected = weighted["expected_value"]
        sensitivity = regulated_asset_sensitivity(
            rate_base=rate_base,
            allowed_roe=allowed_roe,
            equity_ratio=equity_ratio,
            cost_of_equity=cost_of_equity,
            shares_diluted=shares,
            payout_ratio=payout,
            growth=growth,
            book_rate_base=book_rate_base,
            transition_years=transition_years,
            regulatory_lag=regulatory_lag,
            allowed_roe_convention=convention,
        )

        ratio = adr_ratio(company)
        comparable_price = context.current_price / ratio if (ratio and context.current_price) else context.current_price
        used = {name: fact for name, fact in rows.items() if name in MODEL_INPUT_METRICS}
        ids, periods = fact_ids_and_periods(used)
        trace = base_result.trace
        result = {
            "ticker": company.ticker,
            "model_type": model_type,
            "status": "ok",
            "publishable": True,
            "current_price": context.current_price,
            "bear_value": scenario_values["bear"],
            "base_value": scenario_values["base"],
            "bull_value": scenario_values["bull"],
            "expected_value": expected,
            "margin_of_safety": margin_of_safety(expected, comparable_price),
            "missing_inputs": [],
            "publication_blockers": blockers,
            "adr_ratio": ratio,
            "value_per_share_basis": "ordinary_share",
            "listed_share_values": (
                {
                    "bear": scenario_values["bear"] * ratio,
                    "base": scenario_values["base"] * ratio,
                    "bull": scenario_values["bull"] * ratio,
                    "expected": expected * ratio,
                }
                if ratio
                else None
            ),
            "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
            "reverse_dcf": {},
            "sensitivity": sensitivity,
            "moat": empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            ),
            "dasr": {
                "rate_base": rate_base,
                "allowed_roe": allowed_roe,
                "equity_ratio": equity_ratio,
                "cost_of_equity": cost_of_equity,
                "regulatory_base_growth": growth,
                "enterprise_value": base_result.enterprise_value,
                "equity_value": base_result.equity_value,
                "allowed_earnings": base_result.allowed_earnings,
                "earning_power_shortfall": trace["earning_power_shortfall"],
                "excess_return_reconciliation": trace["excess_return_reconciliation"],
            },
            "trace": {
                "method": model_type,
                "engine": self.key,
                "engine_precedence_note": ENGINE_PRECEDENCE_NOTE,
                "input_source": "financial_facts",
                "publishable": True,
                "status": "ok",
                "model_version": MODEL_VERSION,
                "scenario_style": "utilities_regulatory",
                "no_net_debt_subtracted": True,
                "net_debt_note": (
                    "The rate base already IS the capital employed (RB * "
                    "equity_ratio equity / RB * (1 - equity_ratio) debt), so the "
                    "model returns equity value directly and never subtracts "
                    "net debt from it."
                ),
                "fact_ids": {**snapshot.fact_ids(), **ids},
                "periods": {**snapshot.periods(), **periods},
                "input_provenance": provenance_trace(used),
                "snapshot": {
                    "as_of": snapshot.as_of_period,
                    "income_statement": snapshot.income_statement,
                    "balance_sheet": snapshot.balance_sheet,
                    "shares": snapshot.shares_period,
                    "warnings": snapshot.warnings,
                },
                "assumptions": {
                    "rate_base": rate_base,
                    "rate_base_source_metric": rows["rate_base"].metric,
                    "allowed_roe": allowed_roe,
                    "allowed_roe_convention": convention,
                    "equity_ratio": equity_ratio,
                    "cost_of_equity": cost_of_equity,
                    "cost_of_equity_source": cost_source,
                    "payout_ratio": payout,
                    "regulatory_base_growth": growth,
                    "regulatory_base_growth_source": growth_source,
                    "book_rate_base": book_rate_base,
                    "transition_years": transition_years,
                    "transition_years_source": transition_source,
                    "regulatory_lag": regulatory_lag,
                    "regulatory_lag_source": lag_source,
                    "depreciation_rate": depreciation_rate,
                    "capex": capex,
                    "rate_case_year": rate_case_year,
                    "identity": "V = book_equity + (allowed_roe - ke) * book_equity / (ke - g)",
                },
                "dasr": trace,
                "value_composition": trace["value_composition"],
                "excess_return_reconciliation": trace["excess_return_reconciliation"],
                "converged_base_value": trace["converged_base_value"],
                "transition_value_uplift": trace["transition_value_uplift"],
                "enterprise_value": trace["enterprise_value"],
                "enterprise_value_formula": trace["enterprise_value_formula"],
                "equity_value_identity": trace["equity_value_identity"],
                "allowed_roe_convention": trace["allowed_roe_convention"],
                "earning_power_shortfall": trace["earning_power_shortfall"],
                "frozen_base_warning": trace["frozen_base_warning"],
                "negative_value_handling": trace["negative_value_handling"],
                "value_destroying_allowed_roe": trace["value_destroying_allowed_roe"],
                "value_below_book_equity": trace["value_below_book_equity"],
                "negative_equity_value": trace["negative_equity_value"],
                "probabilities": probabilities,
                "probability_method": "source_confidence_plus_allowed_spread_and_lag",
                "evidence_confidence": mean_confidence(used.values()),
                "evidence_confidence_inputs": sorted(MODEL_INPUT_METRICS & set(rows)),
                "publication_blockers": blockers,
                "scenarios": scenario_traces,
                "weighted": weighted["trace"],
            },
        }
        return apply_publication_blockers(result)

    def _cost_of_equity(self, context: ValuationContext, rows: dict[str, SourcedFact]):
        fact = rows.get("cost_of_equity")
        if fact is not None:
            return fact.value, "financial_facts"
        return default_wacc(context.company), "tag_default"

    def _growth(self, context: ValuationContext, rows: dict[str, SourcedFact]) -> tuple[float, str]:
        fact = rows.get("regulatory_base_growth")
        if fact is not None:
            return fact.value, "financial_facts"
        return default_terminal_growth(context.company), "tag_default"

    def _transition_years(self, rows: dict[str, SourcedFact]) -> tuple[int, str]:
        fact = rows.get("transition_years")
        if fact is None:
            return DEFAULT_TRANSITION_YEARS, "policy_default"
        years = int(round(fact.value))
        if years < 0 or years > 20:
            return DEFAULT_TRANSITION_YEARS, "policy_default_out_of_range"
        return years, "financial_facts"

    def _regulatory_lag(self, rows: dict[str, SourcedFact]) -> tuple[float, str]:
        fact = rows.get("regulatory_lag")
        if fact is None:
            return 0.0, "policy_default"
        value = fact.value
        if value < 0 or value > 1:
            return 0.0, "policy_default_out_of_range"
        return value, "financial_facts"
