"""Ilustracion patrimonial pura: capital, aportaciones, costes e inflacion.

No carga cartera ni precios, no elige rentabilidades y no calcula impuestos.
Todos los importes de entrada deben usar la misma divisa. El retorno total
anual es nominal efectivo e incluye dividendos reinvertidos, sin sumarlos otra vez.
"""
from __future__ import annotations

import math
from typing import Any


def _future_value(capital: float, monthly: float, years: int, annual_factor: float) -> float:
    months = years * 12
    if annual_factor == 0:
        # Perdida del 100 % cada mes: solo queda la ultima aportacion, posterior.
        return monthly
    monthly_rate = math.expm1(math.log(annual_factor) / 12)
    if monthly_rate == 0:
        return capital + monthly * months
    growth_log = months * math.log1p(monthly_rate)
    return capital * math.exp(growth_log) + monthly * math.expm1(growth_log) / monthly_rate


def project_wealth(
    *,
    initial_capital: float,
    monthly: float,
    years: int,
    annual_return: float,
    inflation: float,
    contribution_fee: float = 0.0,
    contribution_spread: float = 0.0,
    annual_cost: float = 0.0,
) -> dict[str, Any]:
    """Aportaciones al final del mes; costes descontados, no financiados aparte.

    Comision fija por aportacion, seguida de spread/FX proporcional al importe
    restante. El capital inicial ya esta invertido y no vuelve a pagar entrada.
    Coste anual efectivo: factor (1+retorno)*(1-coste), convertido a mensual.
    No es un TER diario ni una simulacion de operaciones o de fiscalidad.
    Los ceros de costes son hipotesis explicitas, nunca costes reales inferidos.
    """
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 80:
        raise ValueError("years must be an integer between 1 and 80")
    for name, value, low, high in (
        ("initial_capital", initial_capital, 0, 1_000_000_000_000),
        ("monthly", monthly, 0, 1_000_000),
        ("annual_return", annual_return, -0.99, 1),
        ("inflation", inflation, -0.99, 1),
        ("contribution_fee", contribution_fee, 0, 1_000_000),
        ("contribution_spread", contribution_spread, 0, 1),
        ("annual_cost", annual_cost, 0, 1),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"{name} outside supported finite range")
    if contribution_fee > monthly:
        raise ValueError("contribution_fee must not exceed monthly contribution")

    invested_monthly = (monthly - contribution_fee) * (1 - contribution_spread)
    gross = _future_value(initial_capital, monthly, years, 1 + annual_return)
    after_costs = _future_value(
        initial_capital, invested_monthly, years, (1 + annual_return) * (1 - annual_cost)
    )
    deflator = (1 + inflation) ** years
    contributed = monthly * years * 12
    return {
        "years": years,
        "initial_capital": initial_capital,
        "monthly_contribution": monthly,
        "annual_total_return": annual_return,
        "annual_inflation": inflation,
        "contribution_fee": contribution_fee,
        "contribution_spread": contribution_spread,
        "annual_cost": annual_cost,
        "future_contributions": round(contributed, 2),
        "total_capital_supplied": round(initial_capital + contributed, 2),
        "monthly_invested_after_entry_costs": round(invested_monthly, 2),
        "terminal_gross": round(gross, 2),
        "terminal_after_costs_before_tax": round(after_costs, 2),
        "terminal_gross_today_money": round(gross / deflator, 2),
        "terminal_after_costs_today_money_before_tax": round(after_costs / deflator, 2),
        "terminal_net_after_tax": None,
        "tax_status": "not_modelled",
        "assumptions": [
            "Ilustración con hipótesis editables, no predicción. Puedes perder capital.",
            "Importes en una misma divisa; este cálculo no carga cartera, precios ni FX.",
            "Retorno total nominal anual efectivo, incluidos dividendos reinvertidos.",
            "Aportaciones al final de mes; comisión fija y luego spread/FX sobre el resto.",
            "Capital inicial ya invertido, sin nuevo coste de entrada.",
            "Coste anual efectivo sobre el saldo: factor (1+retorno)*(1-coste).",
            "Costes cero por defecto son supuestos, no datos reales del intermediario.",
            "Importes despues de costes antes de impuestos; neto fiscal no disponible.",
            "Inflación es una hipótesis; valor real expresado en dinero de hoy.",
        ],
    }
