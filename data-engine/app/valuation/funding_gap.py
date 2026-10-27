"""Funding-gap based dilution inputs for speculative / pre-FCF companies.

Replaces the arbitrary new_capital_needed=100 default with a transparent
funding gap when cash / burn / capex facts exist; otherwise marks dilution
as incomplete rather than inventing capital needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.valuation.dilution_model import DilutionInput, run_dilution
from app.valuation.financial_snapshot import FinancialSnapshot


@dataclass(frozen=True)
class FundingGapResult:
    funding_gap: float | None
    available_cash: float | None
    planned_capex: float | None
    burn_proxy: float | None
    min_cash_buffer: float
    status: str
    missing_inputs: list[str]
    dilution: dict | None = None
    burn_proxy_source: str | None = None


def estimate_funding_gap(
    snapshot: FinancialSnapshot,
    *,
    current_price: float | None,
    value_per_share: float | None,
    min_cash_buffer: float = 50.0,
    default_horizon_years: float = 2.0,
) -> FundingGapResult:
    cash = snapshot.value("cash_and_equivalents")
    ocf = snapshot.value("operating_cash_flow")
    capex = snapshot.value("capital_expenditure")
    # Capex facts are often stored as negative cash outflows.
    planned_capex = abs(capex) if capex is not None else None

    missing: list[str] = []
    if cash is None:
        missing.append("cash_and_equivalents")
    if planned_capex is None:
        missing.append("capital_expenditure")
    if ocf is None:
        missing.append("operating_cash_flow")

    if missing:
        return FundingGapResult(
            funding_gap=None,
            available_cash=cash,
            planned_capex=planned_capex,
            burn_proxy=None,
            min_cash_buffer=min_cash_buffer,
            status="incomplete",
            missing_inputs=missing,
            dilution=None,
        )

    # Negative OCF implies cash burn; positive OCF reduces the gap.
    # OCF positivo financia primero el capex: la necesidad de capex es la
    # quema neta max(capex - OCF, 0) (es decir, -FCF si FCF < 0). Antes se
    # ignoraba el OCF positivo y se sumaba el capex entero.
    burn_proxy = 0.0
    burn_proxy_source = "operating_cash_flow" if ocf is not None else "unavailable"
    if ocf is not None and ocf < 0:
        burn_proxy = abs(ocf) * default_horizon_years
    ocf_offset = ocf if (ocf is not None and ocf > 0) else 0.0

    capex_need = max((planned_capex or 0.0) - ocf_offset, 0.0) * default_horizon_years
    available = cash or 0.0
    funding_gap = max(capex_need + burn_proxy + min_cash_buffer - available, 0.0)

    dilution = None
    shares = snapshot.value("shares_diluted")
    if (
        funding_gap > 0
        and shares
        and shares > 0
        and current_price
        and current_price > 0
        and value_per_share is not None
    ):
        dilution = run_dilution(
            DilutionInput(
                current_shares=shares,
                new_capital_needed=funding_gap,
                issuance_price=max(current_price * 0.85, 0.1),
                current_value_per_share=value_per_share,
            )
        )

    return FundingGapResult(
        funding_gap=funding_gap,
        available_cash=cash,
        planned_capex=planned_capex,
        burn_proxy=burn_proxy,
        min_cash_buffer=min_cash_buffer,
        status="estimated" if funding_gap > 0 else "no_gap",
        missing_inputs=[],
        dilution=dilution,
        burn_proxy_source=burn_proxy_source,
    )
