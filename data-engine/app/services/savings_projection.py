"""Deterministic savings illustrations, not forecasts of security returns.

One contract for Cartera, Cerebro and the DCA contribution split. Returns
include reinvested dividends: the terminal dividend illustration is never
added a second time. No portfolio values, FX rates or tax rates are inferred.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import InvestmentPlan

DEFAULT_RETURNS = (0.0, 0.03, 0.05, 0.07)


def project_savings(*, monthly: float, years: int, annual_return: float,
                    dividend_yield: float = 0.03, inflation: float = 0.02) -> dict[str, Any]:
    """End-of-month contributions; annual effective nominal total return."""
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 80:
        raise ValueError('years must be an integer between 1 and 80')
    for name, value, low, high in (
        ('monthly', monthly, 0, 1_000_000), ('annual_return', annual_return, -0.99, 1),
        ('dividend_yield', dividend_yield, 0, 0.5), ('inflation', inflation, -0.99, 1),
    ):
        if isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} outside supported finite range')
    months = years * 12
    monthly_rate = math.expm1(math.log1p(annual_return) / 12)
    future = monthly * months if monthly_rate == 0 else monthly * math.expm1(months * math.log1p(monthly_rate)) / monthly_rate
    contributed = monthly * months
    annual_dividend = future * dividend_yield
    return {
        'years': years, 'annual_total_return': annual_return,
        'contributed': round(contributed, 2), 'terminal_value': round(future, 2),
        'simulated_return': round(future - contributed, 2),
        'terminal_value_today_money': round(future / (1 + inflation) ** years, 2),
        'annual_inflation': inflation, 'terminal_dividend_yield': dividend_yield,
        'terminal_annual_gross_dividend': round(annual_dividend, 2),
        'terminal_monthly_gross_dividend_equivalent': round(annual_dividend / 12, 2),
        'net_dividend': None,
    }


def savings_contract(db: Session, *, annual_return: float | None = None,
                     dividend_yield: float = 0.03, inflation: float = 0.02,
                     monthly: float | None = None, years: int | None = None,
                     currency: str | None = None) -> dict[str, Any]:
    plan = db.scalar(select(InvestmentPlan).where(
        *tenant_filters(db, InvestmentPlan)
    ).order_by(InvestmentPlan.created_at.asc(), InvestmentPlan.id.asc()).limit(1))
    preview = monthly is not None or years is not None or currency is not None
    amount = monthly if monthly is not None else float(plan.monthly_contribution) if plan else None
    horizon = years if years is not None else plan.horizon_years if plan else None
    # A custom amount without its explicit currency must not inherit a different unit.
    unit = currency.upper() if currency else (plan.monthly_contribution_currency or '').upper() if plan and monthly is None else None
    result: dict[str, Any] = {
        'plan_exists': plan is not None, 'plan_id': plan.id if plan else None,
        'preview': preview, 'monthly_contribution': amount, 'currency': unit or None,
        'horizon_years': horizon, 'initial_capital': 0, 'portfolio_included': False,
        'basis': 'future_month_end_contributions_only',
        'assumptions': [
            'Hipótesis, no probabilidades ni promesas de rentabilidad. Puedes perder capital.',
            'Aportaciones al final de cada mes, sin capital inicial ni cartera real.',
            'Rentabilidad total anual efectiva: incluye los dividendos reinvertidos.',
            'Dividendo final bruto ilustrativo, no previsión de pagos. No se suma al retorno total.',
            'Sin costes ni impuestos; neto no disponible. Inflación es una hipótesis editable.',
            'Los niveles DCA reparten la cuota; no alteran las rentabilidades supuestas.',
        ],
        'scenarios': [], 'status': 'no_plan' if amount is None or horizon is None else 'currency_missing' if not unit else 'ok',
        'source': '/plan', 'projection_url': '/portfolio?tab=prevision',
    }
    if result['status'] != 'ok':
        return result
    returns = (annual_return,) if annual_return is not None else DEFAULT_RETURNS
    result['scenarios'] = [project_savings(monthly=float(amount), years=horizon,
        annual_return=rate, dividend_yield=dividend_yield, inflation=inflation) for rate in returns]
    return result
