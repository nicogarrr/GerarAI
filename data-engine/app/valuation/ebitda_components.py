"""EBITDA de un ejercicio con su fórmula, también cuando el emisor no etiqueta el resultado operativo.

Caso real (backtest PIT, 8-nov-2026): CNQ (40-F) y Airbus (ESEF) no etiquetan
``ProfitLossFromOperatingActivities``; sin resultado operativo no había EBITDA, el método
caía a PER y, con el beneficio en pico de ciclo, el escenario bajista de CNQ salía a
−62/−70 %/año. Los dos sí etiquetan el beneficio antes de impuestos (``ProfitLossBeforeTax``),
los gastos financieros (``FinanceCosts``) y las amortizaciones.

Orden (el primero que exista manda; los dos primeros son el comportamiento de antes):
1. resultado operativo + |amortizaciones|;
2. EBITDA que traiga la fuente;
3. beneficio antes de impuestos − resultado financiero neto + |amortizaciones| (derivado), y si el
   emisor no etiqueta el resultado financiero neto, beneficio antes de impuestos + |gastos financieros|
   + |amortizaciones| (incluye ingresos financieros, por eso se avisa).
El beneficio antes de impuestos, si no se etiqueta, es beneficio del ejercicio (dominante + minoritarios)
+ gasto por impuesto (IAS 1.82–83): Airbus (ESEF) etiqueta ProfitLoss e IncomeTaxExpenseContinuingOperations
pero no ProfitLossBeforeTax.
Función pura: la usan la valoración de la app y el backtest point-in-time (misma lógica).
"""
from __future__ import annotations

OPERATING_PLUS_DA = "operating_income_plus_da"
REPORTED = "reported_ebitda"
PRETAX_COMPONENTS = "pretax_plus_finance_costs_plus_da"
PRETAX_NET_FINANCE = "pretax_less_net_finance_result_plus_da"

FORMULAS = {
    OPERATING_PLUS_DA: "resultado operativo + amortizaciones del ejercicio",
    REPORTED: "EBITDA de la fuente",
    PRETAX_COMPONENTS: "beneficio antes de impuestos + gastos financieros + amortizaciones del ejercicio "
                       "(sin resultado operativo etiquetado)",
    PRETAX_NET_FINANCE: "beneficio antes de impuestos − resultado financiero neto + amortizaciones del ejercicio "
                        "(sin resultado operativo etiquetado)",
}
DERIVED = (PRETAX_COMPONENTS, PRETAX_NET_FINANCE)


def pretax_income(*, income_before_tax: float | None, profit_loss: float | None,
                  income_tax_expense: float | None) -> float | None:
    """Beneficio antes de impuestos: el etiquetado o beneficio del ejercicio + gasto por impuesto."""
    if income_before_tax is not None:
        return income_before_tax
    if profit_loss is not None and income_tax_expense is not None:
        return profit_loss + income_tax_expense
    return None


def ebitda_from_components(
    *,
    operating_income: float | None,
    depreciation_amortization: float | None,
    ebitda_reported: float | None = None,
    income_before_tax: float | None = None,
    interest_expense: float | None = None,
    net_finance_result: float | None = None,
) -> tuple[float | None, str | None]:
    """(EBITDA, base) del ejercicio; (None, None) si no se puede construir."""
    da = abs(depreciation_amortization) if depreciation_amortization is not None else None
    if operating_income is not None and da is not None:
        return operating_income + da, OPERATING_PLUS_DA
    if ebitda_reported is not None:
        return ebitda_reported, REPORTED
    if income_before_tax is not None and da is not None:
        if net_finance_result is not None:  # signo IFRS: positivo = ingreso financiero neto
            return income_before_tax - net_finance_result + da, PRETAX_NET_FINANCE
        if interest_expense is not None:
            return income_before_tax + abs(interest_expense) + da, PRETAX_COMPONENTS
    return None, None
