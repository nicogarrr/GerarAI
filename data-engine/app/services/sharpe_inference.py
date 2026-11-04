"""Read-only per-period Sharpe diagnostics with dependence-aware uncertainty.

Delta-method influence function + Bartlett/Newey-West long-run variance.
See docs/research/sharpe-inference.md for formula, assumptions and provenance.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist

import numpy as np

MIN_OBSERVATIONS = 60  # conservative product guard, NOT a statistical guarantee
METHOD = "sharpe_delta_hac_bartlett_v1"


def sharpe_inference(
    returns: Sequence[float], *, frequency: str, periods_per_year: int,
    risk_free_per_period: float, horizon: dict | None = None,
    confidence: float = .95, hac_lags: int | None = None, trials: int | None = None,
) -> dict:
    """Wald t-type statistic for H0: per-period Sharpe=0 (normal, not Student t).

    Never drops gaps or nonfinite data. No annualization under dependence.
    Unknown trial count blocks a validation claim, not descriptive inference.
    """
    n = len(returns)
    if (not isinstance(periods_per_year, int) or isinstance(periods_per_year, bool)
            or periods_per_year <= 0 or not frequency or not math.isfinite(risk_free_per_period)
            or not 0 < confidence < 1):
        raise ValueError("Explicit frequency, positive periods/year, finite per-period rf and 0<confidence<1 required")
    if trials is not None and (not isinstance(trials, int) or isinstance(trials, bool) or trials < 1):
        raise ValueError("trials must include every tried specification, as a positive integer")
    if hac_lags is not None and (not isinstance(hac_lags, int) or isinstance(hac_lags, bool)
                                  or hac_lags < 0 or hac_lags >= n):
        raise ValueError("hac_lags must be an integer in [0, n-1]")
    lags = min(n-1, int(math.floor(4*(n/100)**(2/9)))) if n else 0
    if hac_lags is not None:
        lags = hac_lags
    out = {
        "method": METHOD, "status": "insufficient_sample", "frequency": frequency,
        "periods_per_year": periods_per_year, "risk_free_per_period": risk_free_per_period,
        "risk_free_basis": "constant_simple_return_per_observation", "horizon": horizon,
        "n_observations": n, "minimum_observations_policy": MIN_OBSERVATIONS,
        "hac_lags": lags, "bandwidth_rule": "floor(4*(n/100)^(2/9))" if hac_lags is None else "explicit",
        "confidence_level": confidence, "sharpe_per_period": None, "standard_error": None,
        "t_statistic": None, "null_sharpe_per_period": 0.0, "reference_distribution": "asymptotic_standard_normal",
        "p_value": None, "adjusted_p_value": None, "confidence_interval": None,
        "lag1_autocorrelation": None, "trials": trials,
        "selection_adjustment": "unknown_trials" if trials is None else "bonferroni_declared_trials",
        "validation_claim": False,
        "warnings": ["Asymptotic diagnostic, not proof of skill; requires stationary weakly dependent returns and finite fourth moments.",
                     "No sqrt(periods_per_year) annualization under serial dependence.",
                     "Trial count must cover tuning, tickers, horizons and abandoned specifications; holdout validation still required."],
    }
    try:
        if any(v is None or isinstance(v, (bool, str)) for v in returns):
            raise ValueError
        values = np.asarray(returns, dtype=float)
        if values.ndim != 1 or not np.all(np.isfinite(values)):
            raise ValueError
    except (TypeError, ValueError):
        out["status"] = "invalid_series"
        return out
    if n < 2:
        return out
    x = values-risk_free_per_period
    mu = float(np.mean(x))
    centered = x-mu
    sigma = float(np.sqrt(np.mean(centered**2)))
    if sigma <= 1e-12:
        out["status"] = "zero_variance"
        return out
    sr = mu/sigma
    out["sharpe_per_period"] = sr
    if np.std(x[:-1]) > 1e-12 and np.std(x[1:]) > 1e-12:
        out["lag1_autocorrelation"] = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    if n < MIN_OBSERVATIONS:
        out["warnings"].append("Short sample: t statistic and confidence interval withheld by policy.")
        return out
    # IF of mu/sigma using population moment estimators (ddof=0).
    influence = centered/sigma - mu*(centered**2-sigma**2)/(2*sigma**3)
    influence -= np.mean(influence)
    lrv = float(influence @ influence/n)
    for lag in range(1, lags+1):
        lrv += 2*(1-lag/(lags+1))*float(influence[lag:] @ influence[:-lag]/n)
    if not math.isfinite(lrv) or lrv <= 1e-24:
        out["status"] = "degenerate_uncertainty"
        return out
    se = math.sqrt(lrv/n)
    statistic = sr/se
    p = math.erfc(abs(statistic)/math.sqrt(2))
    # Bonferroni union bound does not assume independent trials. It cannot
    # repair an incomplete trial ledger or invalid marginal asymptotics.
    alpha = (1-confidence)/(trials or 1)
    if alpha/2 <= 0 or 1-alpha/2 == 1:
        raise ValueError("confidence/trials exceeds normal quantile precision")
    z = NormalDist().inv_cdf(1-alpha/2)
    out.update(status="asymptotic_diagnostic", standard_error=se, t_statistic=statistic,
               p_value=p, adjusted_p_value=min(1.0, p*trials) if trials else None,
               confidence_interval=[sr-z*se, sr+z*se])
    return out
