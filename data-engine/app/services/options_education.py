"""Offline European reference model, not quotes or a trading recommendation.

Inputs are explicit, no market-data lookup or portfolio/DB side effects. Continuous
q is an approximation, not support for discrete dividends or American exercise.
Prices/Greeks are per share. Time uses ACT/365. Vega/rho are per 1 percentage
point; theta is per calendar day. Delta is not a success probability.
"""
from dataclasses import dataclass
from math import erf, exp, isfinite, log, pi, sqrt
from typing import Literal

from scipy.optimize import brentq

Kind = Literal['call', 'put']


@dataclass(frozen=True)
class Inputs:
    spot: float
    strike: float
    years: float
    rate: float
    dividend_yield: float
    volatility: float
    kind: Kind

    def __post_init__(self) -> None:
        if self.kind not in ('call', 'put'):
            raise ValueError('kind must be call or put')
        if not all(isfinite(v) for v in (self.spot, self.strike, self.years,
                                        self.rate, self.dividend_yield, self.volatility)):
            raise ValueError('all inputs must be finite')
        if self.spot <= 0 or self.strike <= 0 or self.years < 0 or self.volatility < 0:
            raise ValueError('spot/strike positive; time/volatility nonnegative')


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    vega_per_point: float
    theta_per_day: float
    rho_per_point: float


def _cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))


def intrinsic(spot: float, strike: float, kind: Kind) -> float:
    if kind not in ('call', 'put') or not all(isfinite(x) and x >= 0 for x in (spot, strike)):
        raise ValueError('invalid payoff inputs')
    return max((spot - strike) if kind == 'call' else (strike - spot), 0.0)


def european_bounds(x: Inputs) -> tuple[float, float]:
    s = x.spot * exp(-x.dividend_yield * x.years)
    k = x.strike * exp(-x.rate * x.years)
    return (max(s - k, 0.0), s) if x.kind == 'call' else (max(k - s, 0.0), k)


def european_price(x: Inputs) -> float:
    if x.years == 0:
        return intrinsic(x.spot, x.strike, x.kind)
    if x.volatility == 0:
        return european_bounds(x)[0]
    root = sqrt(x.years)
    d1 = (log(x.spot / x.strike) + (x.rate - x.dividend_yield +
          x.volatility**2 / 2) * x.years) / (x.volatility * root)
    d2 = d1 - x.volatility * root
    s = x.spot * exp(-x.dividend_yield * x.years)
    k = x.strike * exp(-x.rate * x.years)
    if x.kind == 'call':
        return max(0.0, s * _cdf(d1) - k * _cdf(d2))
    return max(0.0, k * _cdf(-d2) - s * _cdf(-d1))


def european_greeks(x: Inputs) -> Greeks | None:
    """Undefined at expiry or zero vol: return None, never fabricated zero Greeks."""
    if x.years == 0 or x.volatility == 0:
        return None
    root = sqrt(x.years)
    d1 = (log(x.spot / x.strike) + (x.rate - x.dividend_yield +
          x.volatility**2 / 2) * x.years) / (x.volatility * root)
    d2 = d1 - x.volatility * root
    dq, dr = exp(-x.dividend_yield * x.years), exp(-x.rate * x.years)
    density = exp(-d1**2 / 2) / sqrt(2 * pi)
    sign = 1 if x.kind == 'call' else -1
    delta = sign * dq * _cdf(sign * d1)
    gamma = dq * density / (x.spot * x.volatility * root)
    vega = x.spot * dq * density * root / 100
    theta = (-x.spot * dq * density * x.volatility / (2 * root)
             - sign * x.rate * x.strike * dr * _cdf(sign * d2)
             + sign * x.dividend_yield * x.spot * dq * _cdf(sign * d1)) / 365
    rho = sign * x.strike * x.years * dr * _cdf(sign * d2) / 100
    return Greeks(delta, gamma, vega, theta, rho)


def european_iv(x: Inputs, premium: float, *, max_vol: float = 5.0) -> float | None:
    """Brent inversion, European only. None for missing/nonidentifiable IV.

    Caller must independently verify style, contract, timestamp and quote quality.
    An input historical vol does not become 'implied' vol without a market price.
    """
    from dataclasses import replace

    if not isfinite(premium) or premium < 0 or not isfinite(max_vol) or max_vol <= 0:
        raise ValueError('invalid premium or volatility limit')
    if x.years == 0:
        return None
    lower, upper = european_bounds(x)
    # Boundary prices are numerically nonidentifiable, not evidence of zero IV.
    if not lower < premium < upper:
        return None
    def residual(vol: float) -> float:
        return european_price(replace(x, volatility=vol)) - premium
    if residual(max_vol) < 0:
        return None
    try:
        return float(brentq(residual, 0.0, max_vol, xtol=1e-12, maxiter=200))
    except (ValueError, RuntimeError):
        return None


def long_option_pnl(spot_at_expiry: float, strike: float, kind: Kind, premium: float,
                    *, multiplier: float, contracts: int = 1, fees: float = 0) -> float:
    """Explicit verified deliverable multiplier. No assumption that it is 100."""
    if (not all(isfinite(v) for v in (premium, multiplier, fees)) or premium < 0
            or multiplier <= 0 or fees < 0 or isinstance(contracts, bool)
            or not isinstance(contracts, int) or contracts <= 0):
        raise ValueError('invalid contract size, premium or fees')
    return (intrinsic(spot_at_expiry, strike, kind) - premium) * multiplier * contracts - fees
