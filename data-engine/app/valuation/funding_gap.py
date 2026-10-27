"""Funding-gap based dilution inputs for speculative / pre-FCF companies.

Replaces the arbitrary new_capital_needed=100 default with a transparent
funding gap when cash / burn / capex facts exist; otherwise marks dilution
as incomplete rather than inventing capital needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.valuation.dilution_model import DilutionInput, run_dilution
from app.valuation.financial_snapshot import FinancialSnapshot

#: Colchón mínimo de caja por defecto, en MESES de la salida de caja anual
#: (quema operativa + capex no cubierto). Seis meses es la pauta habitual de
#: "runway" mínimo antes de una ampliación; queda en la traza y es ajustable.
DEFAULT_MIN_CASH_BUFFER_MONTHS = 6.0


@dataclass(frozen=True)
class FundingGapResult:
    funding_gap: float | None
    available_cash: float | None
    planned_capex: float | None
    burn_proxy: float | None
    min_cash_buffer: float | None
    status: str
    missing_inputs: list[str]
    dilution: dict | None = None
    burn_proxy_source: str | None = None
    # Unidad y base del colchón: "meses de salida de caja" (por defecto) o
    # "explicito" (importe pasado por quien llama, en la unidad de los hechos).
    min_cash_buffer_basis: str | None = None


def estimate_funding_gap(
    snapshot: FinancialSnapshot,
    *,
    current_price: float | None,
    value_per_share: float | None,
    min_cash_buffer: float | None = None,
    min_cash_buffer_months: float = DEFAULT_MIN_CASH_BUFFER_MONTHS,
    default_horizon_years: float = 2.0,
) -> FundingGapResult:
    """Hueco de financiación = capex neto + quema + colchón − caja.

    El colchón mínimo de caja tiene UNIDADES explícitas. Por defecto son
    ``min_cash_buffer_months`` meses de la salida de caja anual (quema
    operativa + capex no cubierto por el OCF), así que sale en la misma
    unidad y moneda que los hechos: escalar todos los hechos ×10⁶ escala el
    hueco ×10⁶. Antes era un 50 absoluto, que con hechos en dólares
    (1,2e9 de caja) no pesaba nada y con hechos en millones eran 50 M.
    ``min_cash_buffer`` (importe en la unidad de los hechos) lo sustituye
    cuando quien llama lo conoce.
    """
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
            min_cash_buffer_basis="explicito" if min_cash_buffer is not None else None,
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

    annual_capex_need = max((planned_capex or 0.0) - ocf_offset, 0.0)
    capex_need = annual_capex_need * default_horizon_years
    if min_cash_buffer is None:
        annual_burn = abs(ocf) if (ocf is not None and ocf < 0) else 0.0
        buffer = (annual_burn + annual_capex_need) * min_cash_buffer_months / 12.0
        buffer_basis = f"{min_cash_buffer_months:g} meses de salida de caja anual"
    else:
        buffer = min_cash_buffer
        buffer_basis = "explicito"
    available = cash or 0.0
    funding_gap = max(capex_need + burn_proxy + buffer - available, 0.0)

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
        min_cash_buffer=buffer,
        status="estimated" if funding_gap > 0 else "no_gap",
        missing_inputs=[],
        dilution=dilution,
        burn_proxy_source=burn_proxy_source,
        min_cash_buffer_basis=buffer_basis,
    )
