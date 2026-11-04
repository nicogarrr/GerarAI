"""Explicit annual revenue path, never EPS growth or historical CAGR in disguise.

No company is classified as mature from its ticker, size or a 10% threshold.
Callers supply comparable full-year revenue forecasts and sources. Optional
linear fade is a disclosed model assumption, not a fact or a universal cap.
The output is suitable for run_path_dcf; integration remains the caller's job.
"""
from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True)
class AnnualRevenue:
    fiscal_year: int
    value: float
    currency: str
    scale: int
    scope: str
    published: date
    source_url: str
    citation: str
    period: str = "FY"
    metric: str = "revenue"


def sourced_revenue_path(base: AnnualRevenue, forecasts: list[AnnualRevenue], *,
                         as_of: date, terminal_growth: float | None = None,
                         fade_years: int | None = None, fade_source: str | None = None) -> dict:
    """Growth = forecast annual revenue / previous annual revenue - 1.

    Compare identical currency, monetary scale and consolidation scope only.
    Forecast chronology is consecutive from base FY, available at the cutoff.
    No annualisation, interpolation, FX, missing-year fill or CAGR fallback.
    Fade starts AFTER explicit forecasts and reaches terminal in fade_years.
    """
    out = {"status": "missing", "growth_path": None, "revenue_path": None,
           "inputs": [asdict(row) for row in [base, *forecasts]],
           "limitations": ["revenue_only_not_earnings_or_cash_flow",
                            "no_automatic_maturity_classification"]}
    if not forecasts:
        return {**out, "reason": "annual_revenue_forecasts_required"}
    rows = [base, *forecasts]
    for index, row in enumerate(rows):
        if (row.metric != "revenue" or row.period != "FY" or row.published > as_of
                or not row.source_url.startswith("https://") or not row.citation.strip()
                or not isfinite(row.value) or row.value <= 0 or row.scale <= 0
                or not row.scope.strip() or not row.currency.strip()
                or (row.currency, row.scale, row.scope) != (base.currency, base.scale, base.scope)
                or row.fiscal_year != base.fiscal_year + index):
            return {**out, "status": "invalid", "reason": "incompatible_or_unavailable_annual_revenue"}
    path = [nxt.value/prev.value-1 for prev, nxt in zip(rows, rows[1:])]
    revenues = [row.value for row in forecasts]
    has_fade = any(v is not None for v in (terminal_growth, fade_years, fade_source))
    if has_fade:
        if (terminal_growth is None or not isfinite(terminal_growth) or terminal_growth <= -1
                or type(fade_years) is not int or not 1 <= fade_years <= 50 or not fade_source):
            return {**out, "status": "missing", "reason": "complete_explicit_fade_assumption_required"}
        initial = path[-1]
        for year in range(1, fade_years+1):
            growth = initial + (terminal_growth-initial)*year/fade_years
            path.append(growth)
            revenues.append(revenues[-1]*(1+growth))
    return {**out, "status": "ok", "growth_path": path, "revenue_path": revenues,
            "method": "explicit_annual_revenue_then_disclosed_linear_fade",
            "fade": {"years": fade_years, "terminal_growth": terminal_growth,
                     "source": fade_source}, "reason": None}
