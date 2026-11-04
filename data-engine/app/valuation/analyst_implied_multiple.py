"""Pure reverse exit-multiple calculation for an analyst price target.

A target is an equity price at target_date, not today's enterprise value.
No forecast, discount rate, currency conversion or shares are inferred here.
All monetary inputs share currency and scale; shares and PT must refer to the
same listing/share basis (ADR ratios and dilution must be resolved upstream).
The result is an exit-value-only diagnostic, not a full analyst DCF: interim
distributions are excluded. Target-date net debt is not silently replaced with
today's net debt. EV uses FCFF/WACC, equity uses FCFE/cost of equity.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from app.valuation.currency import is_currency_code, normalize_currency


def implied_forward_multiple(*, target_price, shares, forward_fcf, net_debt_at_target,
                             currency: str, fcf_currency: str, basis: str, fcf_kind: str,
                             target_date: date, forward_date: date, discount_rate,
                             evidence: dict[str, str]) -> dict:
    result = {"status": "invalid", "multiple": None, "warnings": [], "missing": [],
              "basis": basis, "fcf_kind": fcf_kind, "target_date": target_date.isoformat(),
              "forward_date": forward_date.isoformat(), "currency": currency,
              "inputs": {"target_price": str(target_price), "shares": str(shares),
                         "forward_fcf": str(forward_fcf), "net_debt_at_target": str(net_debt_at_target),
                         "discount_rate": str(discount_rate), "evidence": dict(evidence)}}
    required = ["target_price", "shares", "forward_fcf", "discount_rate"]
    if basis == "enterprise":
        required.append("net_debt_at_target")
    missing = [key for key in required if not evidence.get(key)]
    if basis == "enterprise" and net_debt_at_target is None:
        missing.append("net_debt_at_target_value")
    if missing:
        result.update(status="missing", missing=missing)
        return result
    try:
        price, n, fcf, rate = (Decimal(str(v)) for v in (target_price, shares, forward_fcf, discount_rate))
        debt = Decimal(str(net_debt_at_target)) if net_debt_at_target is not None else Decimal(0)
    except (InvalidOperation, ValueError):
        return result
    if (any(not v.is_finite() for v in (price, n, fcf, rate, debt)) or min(price, n, fcf) <= 0
            or not 0 <= rate <= 1 or currency != fcf_currency or not is_currency_code(currency, allow_subunits=False)
            or normalize_currency(currency)[1] != 1
            or (basis, fcf_kind) not in {("enterprise", "fcff"), ("equity", "fcfe")}
            or forward_date < target_date
            or (basis == "equity" and net_debt_at_target is not None)):
        return result
    years = Decimal((forward_date-target_date).days) / Decimal("365.25")
    capital = price*n + debt if basis == "enterprise" else price*n
    if capital <= 0:
        return result
    # Undo discounting from the forward capitalisation date to the PT date.
    multiple = capital * (1+rate) ** years / fcf
    if multiple > 80:
        result["warnings"].append("implied_multiple_above_80")
    result.update(status="orientation" if result["warnings"] else "ok", multiple=multiple,
                  years_to_forward=str(years), method="EV_FCF" if basis == "enterprise" else "P_FCF")
    return result
