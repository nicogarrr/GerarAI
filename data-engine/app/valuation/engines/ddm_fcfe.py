"""Dividend-discount (DDM) and free-cash-flow-to-equity (FCFE) engines.

Both are *equity methods*: they discount cash flow that is already after
interest, so their present value **is** the equity value and net debt is never
subtracted. The arithmetic, the clamps, the identity between the two legs and
the edge cases all live in ``app/valuation/dividend_equity.py``; this module
only resolves facts, picks the method, and publishes the trace.

Contracts (FinancialFact metric names)
--------------------------------------

DDM (``DividendDiscountEngine``):

===============================  ==============================================
``dividend_per_share``           required. D0, last declared annual dividend.
``cost_of_equity``               strongly preferred; falls back to the tag WACC
                                 with ``cost_of_equity_source=tag_default``.
``dividend_growth``              d1 and g2 (a single explicit assumption).
``book_value_growth``            alias for the above when no dividend growth.
``eps`` / ``eps_diluted``        needed only for the justified-P/E leg.
``net_income``                   alias path for eps when no EPS fact exists.
``payout_ratio``                 needed for the justified-P/E leg.
``roe`` / ``return_on_equity``   enables the ``g <= ROE`` refusal.
``shares_diluted``               required.
``dividend_forecast_years``      n1. Policy default 3, declared in the trace.
===============================  ==============================================

FCFE (``FreeCashFlowToEquityEngine``) adds:

===========================  =================================================
``net_income``               required.
``capex`` / ``capital_expenditure``   required. Signs are normalised to an
                             outflow magnitude and the normalisation is
                             published, because the two are subtracted from each
                             other and a mixed convention inverts the term.
``depreciation_amortization``  required.
``delta_total_debt``         required (or ``total_debt`` + ``total_debt_prior_period``).
``delta_working_capital``    required (or ``working_capital`` + its prior period).
``retention_ratio``          b. Or derived from ``payout_ratio`` as 1 - payout.
===========================  =================================================

Refusals, each with a named ``missing_inputs`` entry
---------------------------------------------------

* No dividend and no verifiable payout → ``insufficient_data``. A dividend
  discount model on a company that pays no dividend is an invention.
* ``ke <= g`` → ``cost_of_equity_above_dividend_growth`` (the perpetuity is
  infinite or negative; clamping the spread would invent a price).
* ``ke <= -1`` → ``cost_of_equity_above_minus_one`` (discount factors
  alternate in sign, so they are not a discount).
* ``g >= roe`` → ``growth_below_return_on_equity`` (the equity base cannot
  compound faster than its own return; dividing by the difference is how these
  models end up quoting 400x multiples as information).
* ``payout > 105%`` sustained → ``payout_ratio_not_above_one``.
* ``shares_diluted <= 0`` → ``positive_shares_diluted``.
* An ADR with no ``adr:N`` ratio → ``adr_ratio``, same refusal as the FCFF DCF.

Publication blockers
--------------------

``dividend_growth_source``   the growth was a tag default, not a fact.
``cost_of_equity_source``    ``ke`` was a tag default, not a sourced fact.
``payout_ratio_source``      the payout was derived, not verifiable.
``forecast_is_not_the_driver``  terminal value > 95% of the value (reusing the
                             FCFF token: the explicit stage is a formality).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.valuation.dividend_equity import (
    MIN_COST_OF_EQUITY_SPREAD,
    DdmInputError,
    DdmInputs,
    FcfeInputs,
    ddm_sensitivity_rows,
    fcfe_sensitivity_rows,
    gordon_value,
    reconcile_dividend_model,
    run_ddm,
    run_fcfe,
    solve_required_dividend_growth,
)
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
from app.valuation.scenario_definitions import evidence_weighted_probabilities
from app.valuation.scenario_model import Scenario, probability_weighted_value

# Facts the DDM/FCFE models actually read. Scoped so the evidence confidence
# (and therefore the scenario probabilities) cannot be moved by a balance
# sheet the model never looks at.
MODEL_INPUT_METRICS = frozenset(
    {
        "dividend_per_share",
        "cost_of_equity",
        "dividend_growth",
        "book_value_growth",
        "shares_diluted",
        "eps",
        "eps_diluted",
        "net_income",
        "payout_ratio",
        "roe",
        "return_on_equity",
        "capex",
        "capital_expenditure",
        "depreciation_amortization",
        "delta_total_debt",
        "delta_working_capital",
        "retention_ratio",
        "dividends_paid",
    }
)

# Scenario bumps. ``ke`` and ``g`` are the two inputs a DDM reader argues about
# and the two the divergence is most sensitive to; both move together in the
# bear so the scenario stays a coherent story ("rates up, payout squeezed")
# rather than two unrelated shocks.
KE_BEAR_DELTA = 0.015
KE_BULL_DELTA = -0.010
GROWTH_BEAR_DELTA = -0.020
GROWTH_BULL_DELTA = 0.015
TERMINAL_BEAR_DELTA = -0.010
TERMINAL_BULL_DELTA = 0.005

DEFAULT_STAGE1_YEARS = 3

DIVIDEND_ALIASES = {
    "dividend_per_share": ("dividend_per_share", "dividends_per_share", "annual_dividend_per_share"),
    "cost_of_equity": ("cost_of_equity", "cost_of_equity_capm", "ke"),
    "dividend_growth": ("dividend_growth", "dps_growth", "book_value_growth", "book_growth"),
    "eps": ("eps", "eps_diluted"),
    "net_income": ("net_income", "profit_loss", "net_profit"),
    "payout_ratio": ("payout_ratio", "dividend_payout_ratio", "payout"),
    "roe": ("roe", "return_on_equity", "return_on_tangible_equity"),
    "shares_diluted": ("shares_diluted",),
    "dividends_paid": ("dividends_paid", "dividends_paid_common", "payments_of_dividends"),
    "dividend_forecast_years": ("dividend_forecast_years", "ddm_forecast_years"),
}

FCFE_ALIASES = {
    "net_income": ("net_income", "profit_loss", "net_profit"),
    "capex": ("capex", "capital_expenditure", "capex_abs"),
    "depreciation_amortization": (
        "depreciation_amortization",
        "depreciation_and_amortization",
        "depreciation",
    ),
    "delta_total_debt": (
        "delta_total_debt",
        "change_in_total_debt",
        "net_debt_issued",
    ),
    "total_debt_prior_period": ("total_debt_prior_period", "total_debt_prior_year"),
    # Signo de INVERSION (+ = el circulante sube y consume caja), el que resta
    # el puente FCFE. change_in_working_capital NO es alias: va en signo de
    # flujo de caja (el contrario) y se niega aparte (ver _cash_flow_wc_as_delta).
    "delta_working_capital": (
        "delta_working_capital",
        "working_capital_investment",
    ),
    "working_capital": ("working_capital", "net_working_capital"),
    "working_capital_prior_period": (
        "working_capital_prior_period",
        "working_capital_prior_year",
    ),
    "retention_ratio": ("retention_ratio", "earnings_retention_ratio"),
    "payout_ratio": ("payout_ratio", "dividend_payout_ratio", "payout"),
    "cost_of_equity": ("cost_of_equity", "cost_of_equity_capm", "ke"),
    "roe": ("roe", "return_on_equity", "return_on_tangible_equity"),
    "shares_diluted": ("shares_diluted",),
    "total_debt": ("total_debt",),
    "net_debt": ("net_debt",),
    "dividend_growth": ("dividend_growth", "dps_growth", "book_value_growth", "book_growth"),
    "dividend_forecast_years": ("dividend_forecast_years", "ddm_forecast_years"),
}


@dataclass(frozen=True)
class _GrowthAssumption:
    stage1: float
    terminal: float
    source: str


def _growth_assumption(
    context: ValuationContext, rows: dict[str, SourcedFact]
) -> _GrowthAssumption:
    """Explicit-stage and terminal growth, with the source of each.

    A single ``dividend_growth`` fact is used for both legs on purpose: a DDM
    with two different growth rates and one datum behind it is a model with one
    input and two outputs, and the reader has no way to tell which leg the
    fact supports. ``trace["growth_source"]`` always says which it was.
    """
    fact = rows.get("dividend_growth")
    if fact is not None:
        return _GrowthAssumption(fact.value, fact.value, "financial_facts")
    fallback = default_terminal_growth(context.company)
    return _GrowthAssumption(fallback, fallback, "tag_default")


def _cost_of_equity(
    context: ValuationContext, rows: dict[str, SourcedFact]
) -> tuple[float, str]:
    fact = rows.get("cost_of_equity")
    if fact is not None:
        return fact.value, "financial_facts"
    return default_wacc(context.company), "tag_default"


def _stage1_years(rows: dict[str, SourcedFact]) -> tuple[int, str]:
    fact = rows.get("dividend_forecast_years")
    if fact is None:
        return DEFAULT_STAGE1_YEARS, "policy_default"
    years = int(round(fact.value))
    if years < 0 or years > 20:
        return DEFAULT_STAGE1_YEARS, "policy_default_out_of_range"
    return years, "financial_facts"


def _derive_payout(
    rows: dict[str, SourcedFact], *, dividend: float | None, net_income: float | None
) -> tuple[float | None, str]:
    """Verifiable payout: the fact, or dividends / net income when both exist.

    A derived payout is weaker than a stated one (the dividend per share and
    the net income may not cover the same period), which is why it carries a
    publication blocker instead of being treated as a fact.
    """
    stated = rows.get("payout_ratio")
    if stated is not None:
        return stated.value, "financial_facts"
    if dividend is not None and net_income is not None and net_income > 0 and dividend > 0:
        return dividend / net_income, "derived_dividend_over_net_income"
    return None, "unavailable"


def _eps(rows: dict[str, SourcedFact], *, net_income: float | None, shares: float | None):
    """EPS, from the fact or from net income over diluted shares."""
    fact = rows.get("eps")
    if fact is not None:
        return fact.value, "financial_facts"
    if net_income is not None and shares is not None and shares > 0:
        return net_income / shares, "derived_net_income_over_shares"
    return None, "unavailable"


def _valid_spread(cost_of_equity: float, terminal: float) -> bool:
    return cost_of_equity > terminal and (cost_of_equity - terminal) >= MIN_COST_OF_EQUITY_SPREAD


def _scenario_pair(
    *,
    cost_of_equity: float,
    stage1: float,
    terminal: float,
) -> tuple[dict, dict, dict, list[str]]:
    """bear/base/bull input specs that are guaranteed ordered and valid.

    Value is monotone increasing in ``d1`` and ``g2`` and decreasing in ``ke``,
    so bear (ke up, growth down) can only go below base and bull (ke down,
    growth up) can only go above it. The repair path for a bull whose spread
    collapses under the bumps only ever moves its inputs *towards* base, which
    keeps ``bear <= base <= bull`` true by construction, and the degradation is
    published rather than hidden.
    """
    notes: list[str] = []
    bear = {
        "cost_of_equity": cost_of_equity + KE_BEAR_DELTA,
        "stage1_growth": stage1 + GROWTH_BEAR_DELTA,
        "stage2_growth": terminal + TERMINAL_BEAR_DELTA,
    }
    if not _valid_spread(bear["cost_of_equity"], bear["stage2_growth"]):
        # Raising ke and cutting growth widens the spread, so this can only
        # fail against the ke > -1 guard.
        bear["cost_of_equity"] = max(bear["cost_of_equity"], 0.0)
        notes.append("bear cost of equity clamped to >= 0: a negative discount rate is not a discount.")
    base = {
        "cost_of_equity": cost_of_equity,
        "stage1_growth": stage1,
        "stage2_growth": terminal,
    }
    bull = {
        "cost_of_equity": cost_of_equity + KE_BULL_DELTA,
        "stage1_growth": stage1 + GROWTH_BULL_DELTA,
        "stage2_growth": terminal + TERMINAL_BULL_DELTA,
    }
    if not _valid_spread(bull["cost_of_equity"], bull["stage2_growth"]):
        bull["stage2_growth"] = terminal
        notes.append(
            "bull terminal growth bump dropped: the bear/bull ke move would have "
            f"left a spread below the {MIN_COST_OF_EQUITY_SPREAD:.3f} floor."
        )
    if not _valid_spread(bull["cost_of_equity"], bull["stage2_growth"]):
        bull["cost_of_equity"] = cost_of_equity
        notes.append("bull cost-of-equity discount dropped: the spread floor binds at base.")
    return bear, base, bull, notes


CASH_FLOW_WC_METRIC = "change_in_working_capital"


def _cash_flow_wc_as_delta(
    raw: dict[str, SourcedFact], rows: dict[str, SourcedFact]
) -> bool:
    """Usa ``change_in_working_capital`` como ΔCC del puente, NEGADO.

    El hecho se guarda en signo de flujo de caja (FMP ``changeInWorkingCapital``:
    − = el circulante absorbió caja); el puente FCFE resta un AUMENTO del
    circulante, que es el signo contrario. Solo entra si no hay un
    ``delta_working_capital`` declarado. Devuelve True si lo usó.
    """
    if rows.get("delta_working_capital") is not None:
        return False
    cash_flow = raw.get(CASH_FLOW_WC_METRIC)
    if cash_flow is None:
        return False
    rows["delta_working_capital"] = replace(cash_flow, value=-cash_flow.value)
    return True


def _resolve_delta(
    rows: dict[str, SourcedFact], *, direct: str, current: str, prior: str
) -> tuple[float | None, str]:
    """A balance-sheet delta, from a stored difference or from both instants.

    ``(None, "unavailable")`` when neither route works, so the caller names the
    input instead of inventing a zero.
    """
    stated = rows.get(direct)
    if stated is not None:
        return stated.value, "financial_facts"
    now = rows.get(current)
    before = rows.get(prior)
    if now is not None and before is not None:
        return now.value - before.value, "derived_from_two_instants"
    return None, "unavailable"


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


def _insufficient_from_error(context: ValuationContext, err: DdmInputError) -> dict:
    return _insufficient(
        context,
        missing=[err.missing_input],
        reason=err.reason,
    )


class _EquityMethodEngine(ValuationEngine):
    """Shared plumbing: ADR basis, probabilities, ADR conversion, publication."""

    def _base_result(
        self,
        context: ValuationContext,
        *,
        model_type: str,
        scenario_values: dict[str, float],
        scenario_traces: dict,
        probabilities: dict[str, float],
        rows: dict[str, SourcedFact],
        used_metrics: set[str],
        assumptions: dict,
        sensitivity: dict,
        reverse: dict,
        publication_blockers: list[str],
        extra_top_level: dict | None = None,
    ) -> dict:
        company = context.company
        weighted = probability_weighted_value(
            [
                Scenario(name, probabilities[name], scenario_values[name])
                for name in ("bear", "base", "bull")
            ]
        )
        expected = weighted["expected_value"]
        ratio = adr_ratio(company)
        comparable_price = context.current_price / ratio if (ratio and context.current_price) else context.current_price
        used = {name: fact for name, fact in rows.items() if name in used_metrics}
        ids, periods = fact_ids_and_periods(used)
        snapshot = context.snapshot
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
            "publication_blockers": publication_blockers,
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
            "reverse_dcf": reverse,
            "sensitivity": sensitivity,
            "moat": empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            ),
            "trace": {
                "method": model_type,
                "engine": self.key,
                "input_source": "financial_facts",
                "publishable": True,
                "status": "ok",
                "model_version": MODEL_VERSION,
                "scenario_style": f"{self.key}_equity_causal",
                "no_net_debt_subtracted": True,
                "net_debt_note": (
                    "Equity method: the discounted stream is after interest and "
                    "net borrowing, so its present value is the equity value. "
                    "Net debt is never subtracted."
                ),
                "fact_ids": {**snapshot.fact_ids(), **ids},
                "periods": {**snapshot.periods(), **periods},
                "input_provenance": provenance_trace(used),
                "assumptions": assumptions,
                "probabilities": probabilities,
                "probability_method": "source_confidence_plus_payout_and_spread",
                "evidence_confidence": mean_confidence(used.values()),
                "evidence_confidence_inputs": sorted(used_metrics & set(rows)),
                "publication_blockers": publication_blockers,
                "snapshot": {
                    "as_of": snapshot.as_of_period,
                    "income_statement": snapshot.income_statement,
                    "balance_sheet": snapshot.balance_sheet,
                    "shares": snapshot.shares_period,
                    "warnings": snapshot.warnings,
                },
                "scenarios": scenario_traces,
                "weighted": weighted["trace"],
                "reverse_ddm": reverse.get("trace") if reverse else None,
            },
        }
        if extra_top_level:
            result.update(extra_top_level)
        return apply_publication_blockers(result)

    def _adr_refusal(self, context: ValuationContext, *, model_type: str) -> dict | None:
        if not is_adr_without_ratio(context.company):
            return None
        return _insufficient(
            context,
            missing=["adr_ratio"],
            reason=(
                f"{context.company.ticker} is quoted as an ADR but the "
                "ordinary-shares-per-ADR ratio is unknown, so the per-share "
                "value and the quoted price are not on the same basis."
            ),
            extra_trace={"model_type": model_type, "engine": self.key},
        )


class DividendDiscountEngine(_EquityMethodEngine):
    """Multi-stage dividend discount model, per ordinary share.

    Requires a declared dividend (or a verifiable payout against net income);
    refuses a cost of equity that does not clear the growth, a growth that does
    not clear the ROE, and a sustained payout above earnings. Publishes the
    Gordon/justified-P/E reconciliation, so the price can be audited term by
    term, plus a reverse DDM of the growth the price requires.
    """

    key = "ddm"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        model_type = company.valuation_model or "dividend_discount"
        refusal = self._adr_refusal(context, model_type=model_type)
        if refusal is not None:
            return refusal

        raw = latest_facts(
            context.db,
            company.id,
            sorted({alias for group in DIVIDEND_ALIASES.values() for alias in group}),
            cutoff=context_split_cutoff(context),
        )
        rows = resolve_aliases(raw, DIVIDEND_ALIASES)

        missing: list[str] = []
        shares_fact = rows.get("shares_diluted")
        if shares_fact is None:
            missing.append("shares_diluted")
        dividend_fact = rows.get("dividend_per_share")
        total_dividends_fact = rows.get("dividends_paid")
        dividend: float | None = None
        dividend_source = "unavailable"
        dividend_derivation: dict | None = None
        if dividend_fact is not None:
            dividend = float(dividend_fact.value)
            dividend_source = "financial_facts"
        elif (
            total_dividends_fact is not None
            and shares_fact is not None
            and float(shares_fact.value) > 0
            and abs(float(total_dividends_fact.value)) > 0
        ):
            # DPS derivado: dividendos pagados totales / acciones diluidas.
            # abs(): parte del cash-flow SEC lo reporta en negativo. Es una
            # derivacion, no un hecho declarado: va marcada en la traza con
            # sus componentes y bloquea la publicacion igual que el payout
            # derivado.
            dividend = abs(float(total_dividends_fact.value)) / float(shares_fact.value)
            dividend_source = "derived_dividends_paid_over_shares"
            dividend_derivation = {
                "formula": "abs(dividends_paid) / shares_diluted",
                "dividends_paid": total_dividends_fact.as_trace(),
                "shares_diluted": shares_fact.as_trace(),
            }
        if dividend is None:
            missing.append("dividend_per_share_or_payout_ratio")

        if missing:
            return _insufficient(
                context,
                missing=missing,
                reason=(
                    "A dividend discount model needs a declared dividend per "
                    "share and diluted shares. Valuing a non-dividend payer by "
                    "its dividend is not a valuation."
                ),
                extra_trace={
                    "dividend_input_contract": {
                        "dividend_per_share": "last declared annual dividend, per ordinary share",
                        "or": "net_income + payout_ratio (or dividend_per_share + net_income)",
                        "cost_of_equity": "sourced cost of equity; tag default is flagged",
                        "dividend_growth": "explicit d1 and g2 (aliases: book_value_growth)",
                    },
                    "missing_input_detail": {
                        "dividend_per_share": None
                        if dividend_fact is None
                        else dividend_fact.as_trace(),
                    },
                },
            )

        assert shares_fact is not None and dividend is not None
        shares = float(shares_fact.value)
        growth = _growth_assumption(context, rows)
        cost_of_equity, cost_source = _cost_of_equity(context, rows)
        years, years_source = _stage1_years(rows)
        net_income_fact = rows.get("net_income")
        net_income = float(net_income_fact.value) if net_income_fact else None
        payout, payout_source = _derive_payout(
            rows, dividend=dividend, net_income=net_income
        )
        eps, eps_source = _eps(rows, net_income=net_income, shares=shares)
        roe_fact = rows.get("roe")
        roe = float(roe_fact.value) if roe_fact else None

        blockers: list[str] = []
        if growth.source != "financial_facts":
            blockers.append("dividend_growth_source")
        if cost_source != "financial_facts":
            blockers.append("cost_of_equity_source")
        if payout_source not in ("financial_facts",):
            blockers.append("payout_ratio_source")
        if dividend_source != "financial_facts":
            blockers.append("dividend_per_share_source")

        base_inputs = DdmInputs(
            dividend_per_share=dividend,
            cost_of_equity=cost_of_equity,
            stage1_growth=growth.stage1,
            stage1_years=years,
            stage2_growth=growth.terminal,
            payout_ratio=payout,
            eps=eps,
            return_on_equity=roe,
            shares_diluted=shares,
        )
        try:
            base_result = run_ddm(base_inputs)
        except DdmInputError as err:
            return _insufficient_from_error(context, err)

        bear_spec, base_spec, bull_spec, scenario_notes = _scenario_pair(
            cost_of_equity=cost_of_equity,
            stage1=growth.stage1,
            terminal=growth.terminal,
        )
        scenario_values: dict[str, float] = {}
        scenario_traces: dict[str, dict] = {}
        for name, spec in (("bear", bear_spec), ("base", base_spec), ("bull", bull_spec)):
            try:
                outcome = run_ddm(
                    DdmInputs(
                        dividend_per_share=dividend,
                        cost_of_equity=spec["cost_of_equity"],
                        stage1_growth=spec["stage1_growth"],
                        stage1_years=years,
                        stage2_growth=spec["stage2_growth"],
                        payout_ratio=payout,
                        eps=eps,
                        return_on_equity=roe,
                        shares_diluted=shares,
                    )
                )
            except DdmInputError as err:
                # A scenario that cannot be evaluated falls back to base and
                # says so; silently dropping it would leave a bear/base/bull
                # range with a hole in it.
                outcome = base_result
                scenario_notes.append(
                    f"{name} scenario revalued at base inputs: {err.missing_input}."
                )
            scenario_values[name] = outcome.value_per_share
            scenario_traces[name] = {
                "definition": {
                    "name": name,
                    "drivers": [
                        f"cost_of_equity {spec['cost_of_equity']:.4f}",
                        f"stage1_growth {spec['stage1_growth']:.4f}",
                        f"stage2_growth {spec['stage2_growth']:.4f}",
                    ],
                    "assumptions": spec,
                },
                "value_per_share": outcome.value_per_share,
                "trace": outcome.trace,
            }

        reconciliation = _ddm_reconciliation(
            dividend=dividend,
            cost_of_equity=cost_of_equity,
            terminal=growth.terminal,
            payout=payout,
            eps=eps,
            roe=roe,
            multi_stage_value=base_result.value_per_share,
        )
        terminal_share = base_result.trace.get("pv_terminal_share_of_value")
        if isinstance(terminal_share, (int, float)) and terminal_share > 0.95:
            blockers.append("forecast_is_not_the_driver")

        probabilities = evidence_weighted_probabilities(
            evidence_confidence=mean_confidence(
                fact for name, fact in rows.items() if name in MODEL_INPUT_METRICS
            ),
            directional_signal=min(
                1.0,
                max(
                    -1.0,
                    (cost_of_equity - growth.terminal - 0.05) * 3
                    + ((payout or 0.0) - 0.5) * 1.5,
                ),
            ),
            downside_risk=min(1.0, max(0.0, 1.0 - (payout or 0.0))),
        )
        sensitivity = ddm_sensitivity_rows(
            dividend_per_share=dividend,
            cost_of_equity=cost_of_equity,
            terminal_growth=growth.terminal,
            payout_ratio=payout if payout is not None else 0.0,
            stage1_years=years,
        )
        ratio = adr_ratio(company)
        comparable_price = context.current_price / ratio if (ratio and context.current_price) else context.current_price
        reverse = (
            solve_required_dividend_growth(
                market_price=comparable_price,
                dividend_per_share=dividend,
                cost_of_equity=cost_of_equity,
                stage2_growth=growth.terminal,
                stage1_years=years,
                payout_ratio=payout,
            )
            if comparable_price is not None and comparable_price > 0
            else {}
        )

        used_metrics = {
            "dividend_per_share",
            "cost_of_equity",
            "dividend_growth",
            "shares_diluted",
            "eps",
            "net_income",
            "payout_ratio",
            "roe",
            "dividend_forecast_years",
        }
        assumptions = {
            "dividend_per_share_d0": dividend,
            "dividend_source": dividend_source,
            "dividend_per_share_derivation": dividend_derivation,
            "stage1_growth": growth.stage1,
            "stage1_years": years,
            "stage1_years_source": years_source,
            "stage2_growth": growth.terminal,
            "growth_source": growth.source,
            "cost_of_equity": cost_of_equity,
            "cost_of_equity_source": cost_source,
            "payout_ratio": payout,
            "payout_source": payout_source,
            "eps": eps,
            "eps_source": eps_source,
            "roe": roe,
            "scenario_notes": scenario_notes,
            "clamp_notes": base_result.trace.get("clamp_notes", []),
        }
        return self._base_result(
            context,
            model_type=model_type,
            scenario_values=scenario_values,
            scenario_traces=scenario_traces,
            probabilities=probabilities,
            rows=rows,
            used_metrics=used_metrics,
            assumptions=assumptions,
            sensitivity=sensitivity,
            reverse=reverse,
            publication_blockers=blockers,
            extra_top_level={
                "ddm": {
                    "dividend_per_share_d0": dividend,
                    "stage1_growth": growth.stage1,
                    "stage2_growth": growth.terminal,
                    "stage1_years": years,
                    "cost_of_equity": cost_of_equity,
                    "payout_ratio": payout,
                    "reconciliation": reconciliation,
                }
            },
        )


class FreeCashFlowToEquityEngine(_EquityMethodEngine):
    """Free cash flow to equity: the discounted stream IS the equity value.

    ``FCFE = NI - (capex - D&A) + Δdebt - ΔWC`` projected at ``ke``. The
    engine carries ``total_debt``/``net_debt`` as disclosure only and never
    subtracts them, which is the double count these models usually make; the
    trace proves it by showing the bridge that collapses onto the Gordon price.
    """

    key = "fcfe"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        model_type = company.valuation_model or "free_cash_flow_to_equity"
        refusal = self._adr_refusal(context, model_type=model_type)
        if refusal is not None:
            return refusal

        raw = latest_facts(
            context.db,
            company.id,
            sorted({alias for group in FCFE_ALIASES.values() for alias in group} | {CASH_FLOW_WC_METRIC}),
            cutoff=context_split_cutoff(context),
        )
        rows = resolve_aliases(raw, FCFE_ALIASES)
        wc_from_cash_flow = _cash_flow_wc_as_delta(raw, rows)

        missing: list[str] = []
        for key_name, label in (
            ("net_income", "net_income"),
            ("capex", "capex"),
            ("depreciation_amortization", "depreciation_amortization"),
            ("shares_diluted", "shares_diluted"),
        ):
            if rows.get(key_name) is None:
                missing.append(label)

        # A delta is a difference of two balance-sheet instants. Providers that
        # report the two readings instead of the difference are accepted, but
        # only when BOTH instants are present: with one instant the delta is
        # unknown, and defaulting it to zero would state that the company
        # neither borrowed nor repaid.
        delta_debt, delta_debt_source = _resolve_delta(
            rows, direct="delta_total_debt", current="total_debt", prior="total_debt_prior_period"
        )
        delta_wc, delta_wc_source = _resolve_delta(
            rows,
            direct="delta_working_capital",
            current="working_capital",
            prior="working_capital_prior_period",
        )
        if wc_from_cash_flow:
            delta_wc_source = "negated_cash_flow_change_in_working_capital"
        if delta_debt is None:
            missing.append("delta_total_debt_or_total_debt_pair")
        if delta_wc is None:
            missing.append("delta_working_capital_or_working_capital_pair")

        if missing:
            return _insufficient(
                context,
                missing=missing,
                reason=(
                    "An FCFE model needs net income, capex, depreciation, the "
                    "change in total debt, the change in working capital and "
                    "diluted shares: the bridge is the model. Coercing a missing "
                    "delta to zero would state that the company neither borrowed "
                    "nor repaid, which is a fact about the world."
                ),
                extra_trace={
                    "fcfe_input_contract": {
                        "formula": "FCFE = NI - (capex - D&A) + delta_total_debt - delta_working_capital",
                        "retention_ratio": "b; or derived as 1 - payout_ratio",
                        "sign_convention": (
                            "capex and depreciation are normalised to outflow/"
                            "charge magnitudes; the normalisation is published in "
                            "trace['sign_normalisation']"
                        ),
                    }
                },
            )

        shares = float(rows["shares_diluted"].value)
        net_income = float(rows["net_income"].value)
        capex_raw = float(rows["capex"].value)
        depreciation_raw = float(rows["depreciation_amortization"].value)
        assert delta_debt is not None and delta_wc is not None
        delta_debt = float(delta_debt)
        delta_wc = float(delta_wc)

        # The bridge subtracts (capex - D&A) from net income, so the two terms
        # must share a convention. Ingestion stores capex as a cash outflow
        # (negative) and depreciation as a charge (positive); taking absolute
        # values normalises both without inventing anything, and the fact that
        # it was applied is published.
        capex = abs(capex_raw)
        depreciation = abs(depreciation_raw)
        sign_normalisation = {
            "capex_raw": capex_raw,
            "depreciation_amortization_raw": depreciation_raw,
            "capex_used": capex,
            "depreciation_amortization_used": depreciation,
            "applied": capex_raw != capex or depreciation_raw != depreciation,
            "reason": (
                "The FCFE bridge subtracts net reinvestment, so capex enters as "
                "an outflow magnitude and depreciation as a charge magnitude. A "
                "mixed convention inverts the term."
            ),
        }

        growth = _growth_assumption(context, rows)
        cost_of_equity, cost_source = _cost_of_equity(context, rows)
        years, years_source = _stage1_years(rows)

        retention_fact = rows.get("retention_ratio")
        payout, payout_source = _derive_payout(rows, dividend=None, net_income=net_income)
        if retention_fact is not None:
            retention = float(retention_fact.value)
            retention_source = "financial_facts"
        elif payout is not None:
            retention = 1.0 - payout
            retention_source = "derived_from_payout"
        else:
            return _insufficient(
                context,
                missing=["retention_ratio_or_payout_ratio"],
                reason=(
                    "FCFE needs the earnings retention policy: without b (or a "
                    "payout ratio to derive it from) the reinvestment term "
                    "(1 - b)(capex - D&A) is unknown and the model would value "
                    "100% of the reinvestment as if none of it were kept."
                ),
            )
        roe_fact = rows.get("roe")
        roe = float(roe_fact.value) if roe_fact else None

        blockers: list[str] = []
        if growth.source != "financial_facts":
            blockers.append("dividend_growth_source")
        if cost_source != "financial_facts":
            blockers.append("cost_of_equity_source")
        if retention_source != "financial_facts":
            blockers.append("payout_ratio_source")

        base_inputs = FcfeInputs(
            net_income=net_income,
            capex=capex,
            depreciation_amortization=depreciation,
            retention_ratio=retention,
            cost_of_equity=cost_of_equity,
            stage1_growth=growth.stage1,
            stage1_years=years,
            stage2_growth=growth.terminal,
            delta_total_debt=delta_debt,
            delta_working_capital=delta_wc,
            shares_diluted=shares,
            total_debt=float(rows["total_debt"].value) if rows.get("total_debt") else None,
            net_debt=float(rows["net_debt"].value) if rows.get("net_debt") else None,
            return_on_equity=roe,
        )
        try:
            base_result = run_fcfe(base_inputs)
        except DdmInputError as err:
            return _insufficient_from_error(context, err)

        bear_spec, base_spec, bull_spec, scenario_notes = _scenario_pair(
            cost_of_equity=cost_of_equity,
            stage1=growth.stage1,
            terminal=growth.terminal,
        )
        scenario_values: dict[str, float] = {}
        scenario_traces: dict[str, dict] = {}
        for name, spec in (("bear", bear_spec), ("base", base_spec), ("bull", bull_spec)):
            try:
                outcome = run_fcfe(
                    FcfeInputs(
                        net_income=net_income,
                        capex=capex,
                        depreciation_amortization=depreciation,
                        retention_ratio=retention,
                        cost_of_equity=spec["cost_of_equity"],
                        stage1_growth=spec["stage1_growth"],
                        stage1_years=years,
                        stage2_growth=spec["stage2_growth"],
                        delta_total_debt=delta_debt,
                        delta_working_capital=delta_wc,
                        shares_diluted=shares,
                        return_on_equity=roe,
                        # Disclosure only, carried into every scenario so the
                        # "we did not subtract the debt" claim is visible on
                        # each of them, not just on the base.
                        total_debt=(
                            float(rows["total_debt"].value) if rows.get("total_debt") else None
                        ),
                        net_debt=(
                            float(rows["net_debt"].value) if rows.get("net_debt") else None
                        ),
                    )
                )
            except DdmInputError as err:
                outcome = base_result
                scenario_notes.append(
                    f"{name} scenario revalued at base inputs: {err.missing_input}."
                )
            scenario_values[name] = outcome.value_per_share
            scenario_traces[name] = {
                "definition": {
                    "name": name,
                    "drivers": [
                        f"cost_of_equity {spec['cost_of_equity']:.4f}",
                        f"stage1_growth {spec['stage1_growth']:.4f}",
                        f"stage2_growth {spec['stage2_growth']:.4f}",
                    ],
                    "assumptions": spec,
                },
                "value_per_share": outcome.value_per_share,
                "trace": outcome.trace,
            }

        terminal_share = base_result.trace.get("pv_terminal_share_of_value")
        if isinstance(terminal_share, (int, float)) and terminal_share > 0.95:
            blockers.append("forecast_is_not_the_driver")

        probabilities = evidence_weighted_probabilities(
            evidence_confidence=mean_confidence(
                fact for name, fact in rows.items() if name in MODEL_INPUT_METRICS
            ),
            directional_signal=min(
                1.0,
                max(-1.0, (cost_of_equity - growth.terminal - 0.05) * 3),
            ),
            downside_risk=min(1.0, max(0.0, -base_result.fcfe / max(abs(net_income), 1e-9))),
        )
        sensitivity = fcfe_sensitivity_rows(
            fcfe=base_result.fcfe,
            cost_of_equity=cost_of_equity,
            terminal_growth=growth.terminal,
        )

        used_metrics = {
            "net_income",
            "capex",
            "depreciation_amortization",
            "delta_total_debt",
            "delta_working_capital",
            "shares_diluted",
            "retention_ratio",
            "payout_ratio",
            "cost_of_equity",
            "roe",
            "dividend_growth",
            "total_debt",
            "net_debt",
        }
        assumptions = {
            "net_income": net_income,
            "capex": capex,
            "depreciation_amortization": depreciation,
            "delta_total_debt": delta_debt,
            "delta_total_debt_source": delta_debt_source,
            "delta_working_capital": delta_wc,
            "delta_working_capital_source": delta_wc_source,
            "retention_ratio": retention,
            "retention_source": retention_source,
            "payout_ratio": payout,
            "payout_source": payout_source,
            "fcfe_base": base_result.fcfe,
            "stage1_growth": growth.stage1,
            "stage1_years": years,
            "stage1_years_source": years_source,
            "stage2_growth": growth.terminal,
            "growth_source": growth.source,
            "cost_of_equity": cost_of_equity,
            "cost_of_equity_source": cost_source,
            "roe": roe,
            "sign_normalisation": sign_normalisation,
            "scenario_notes": scenario_notes,
            "clamp_notes": base_result.trace.get("clamp_notes", []),
        }
        return self._base_result(
            context,
            model_type=model_type,
            scenario_values=scenario_values,
            scenario_traces=scenario_traces,
            probabilities=probabilities,
            rows=rows,
            used_metrics=used_metrics,
            assumptions=assumptions,
            sensitivity=sensitivity,
            reverse={},
            publication_blockers=blockers,
            extra_top_level={
                "fcfe": {
                    "fcfe_base": base_result.fcfe,
                    "bridge": base_result.trace["bridge"],
                    "reconciliation": base_result.trace["reconciliation"],
                    "stage1_growth": growth.stage1,
                    "stage2_growth": growth.terminal,
                    "stage1_years": years,
                    "cost_of_equity": cost_of_equity,
                    "no_net_debt_subtracted": True,
                }
            },
        )


def _ddm_reconciliation(
    *,
    dividend: float,
    cost_of_equity: float,
    terminal: float,
    payout: float | None,
    eps: float | None,
    roe: float | None,
    multi_stage_value: float,
) -> dict:
    """The Gordon/justified-P-E identity, plus what the explicit stage added.

    Three numbers, all auditable on paper:

    1. ``gordon_perpetuity_value`` = ``D1 / (ke - g2)`` — the value of the
       dividend grown forever, nothing else.
    2. ``eps_implied_value`` = ``EPS1 * payout / (ke - g2)`` — the same price
       written as a justified forward P/E, valid only while
       ``g = ROE * (1 - payout)``. Equal to (1) exactly when the declared
       dividend *is* ``EPS * payout``; the gap is the dividend policy, with
       ``ke`` and ``g`` cancelled out.
    3. ``multi_stage_premium_over_gordon`` — what the ``d1``/``n1`` explicit
       stage added over the perpetuity, which is the part of the answer that
       depends on a forecast rather than on a policy.
    """
    identity = reconcile_dividend_model(
        dividend_per_share=dividend,
        cost_of_equity=cost_of_equity,
        terminal_growth=terminal,
        payout_ratio=payout,
        eps=eps,
        return_on_equity=roe,
    )
    gordon = identity["gordon_perpetuity_value"]
    return {
        **identity,
        "multi_stage_value": multi_stage_value,
        "multi_stage_premium_over_gordon": multi_stage_value - gordon,
        "multi_stage_premium_pct": (
            (multi_stage_value - gordon) / gordon if gordon > 0 else None
        ),
        "gordon_value_recomputed": gordon_value(dividend, cost_of_equity, terminal),
        "audit_note": (
            "Everything above is one of D1, ke, g, payout and EPS. A reader who "
            "disagrees with the price disagrees with one of five numbers, and "
            "each of them is named here with the value used."
        ),
    }
