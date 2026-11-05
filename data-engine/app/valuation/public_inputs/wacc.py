"""Pure, fail-closed nominal USD cost-of-capital calculation."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class MarketInput:
    value: Decimal
    unit: str
    observed_at: date
    published_at: date
    source_url: str
    reference: str


def calculate_wacc(inputs: dict[str, MarketInput], *, as_of: date) -> dict:
    """CAPM Ke plus market-value capital weights; no policy defaults.

    Rates are decimal fractions, beta dimensionless, E/D in USD. Zero debt
    must be an explicit sourced value. g is an assumption, not part of WACC.
    """
    missing = []
    invalid = []
    required = ("risk_free_rate", "beta", "equity_risk_premium", "market_equity", "debt")
    for key in required:
        if key not in inputs:
            missing.append(key)
    for key, item in inputs.items():
        expected = "USD" if key in {"market_equity", "debt"} else "ratio" if key == "beta" else "decimal"
        try:
            value = Decimal(str(item.value))
            valid = value.is_finite() and value >= 0
        except Exception:
            valid = False
        if (not valid or item.unit != expected or item.observed_at > as_of
                or item.published_at > as_of or not item.source_url.startswith("https://") or not item.reference):
            invalid.append(key)
    debt = inputs.get("debt")
    if debt is not None and "debt" not in invalid and Decimal(str(debt.value)) > 0:
        missing.extend(k for k in ("cost_of_debt", "tax_rate") if k not in inputs)
    result = {"status": "invalid" if invalid else "missing" if missing else "ok", "wacc": None,
              "cost_of_equity": None, "missing": missing, "invalid": invalid,
              "currency": "USD", "method": "CAPM_market_weighted_WACC",
              "sources": {k: {"value": str(v.value), "unit": v.unit,
                               "observed_at": v.observed_at.isoformat(),
                               "published_at": v.published_at.isoformat(),
                               "source_url": v.source_url, "reference": v.reference}
                          for k, v in inputs.items()}}
    if invalid or missing:
        return result
    v = {k: Decimal(str(item.value)) for k, item in inputs.items()}
    if not (0 <= v["risk_free_rate"] <= Decimal(".20") and 0 < v["beta"] <= 5
            and 0 < v["equity_risk_premium"] <= Decimal(".20") and v["market_equity"] > 0):
        result.update(status="invalid", invalid=["economic_bounds"])
        return result
    ke = v["risk_free_rate"] + v["beta"] * v["equity_risk_premium"]
    if v["debt"] > 0:
        if not (0 <= v["tax_rate"] <= 1 and 0 <= v["cost_of_debt"] <= Decimal(".50")):
            result.update(status="invalid", invalid=["debt_or_tax_bounds"])
            return result
        total = v["market_equity"] + v["debt"]
        wacc = ke * v["market_equity"] / total + v["cost_of_debt"] * (1-v["tax_rate"]) * v["debt"] / total
    else:
        wacc = ke
    if not Decimal(".01") <= wacc <= Decimal(".50"):
        result.update(status="invalid", invalid=["wacc_bounds"])
        return result
    result.update(wacc=wacc, cost_of_equity=ke)
    return result
