from dataclasses import replace
from math import exp

import pytest

from app.services.options_education import (
    Inputs,
    european_bounds,
    european_greeks,
    european_iv,
    european_price,
    long_option_pnl,
)

BASE = Inputs(100, 100, 1, .05, 0, .2, 'call')


def test_known_reference_and_put_call_parity():
    assert european_price(BASE) == pytest.approx(10.4505835722)
    assert european_price(replace(BASE, kind='put')) == pytest.approx(5.5735260223)


@pytest.mark.parametrize('q', [0, .02, .10])
@pytest.mark.parametrize('r', [-.02, 0, .05])
@pytest.mark.parametrize('spot', [50, 100, 150])
def test_parity_and_bounds(q, r, spot):
    x = replace(BASE, dividend_yield=q, rate=r, spot=spot)
    put = replace(x, kind='put')
    assert european_price(x) - european_price(put) == pytest.approx(
        spot * exp(-q) - 100 * exp(-r), abs=1e-10)
    for inp in (x, put):
        lo, hi = european_bounds(inp)
        assert lo - 1e-10 <= european_price(inp) <= hi + 1e-10


@pytest.mark.parametrize('kind', ['call', 'put'])
def test_all_greeks_against_independent_finite_differences(kind):
    x = replace(BASE, kind=kind, dividend_yield=.03)
    g = european_greeks(x)
    h = .001
    def d(field, step):
        return (european_price(replace(x, **{field: getattr(x, field) + step})) -
                european_price(replace(x, **{field: getattr(x, field) - step}))) / (2 * step)
    assert g.delta == pytest.approx(d('spot', h), rel=1e-6)
    gamma = (european_price(replace(x, spot=x.spot+h)) - 2*european_price(x) +
             european_price(replace(x, spot=x.spot-h))) / h**2
    assert g.gamma == pytest.approx(gamma, rel=1e-5)
    assert g.vega_per_point == pytest.approx(d('volatility', 1e-5)/100, rel=1e-6)
    assert g.rho_per_point == pytest.approx(d('rate', 1e-5)/100, rel=1e-6)
    assert g.theta_per_day == pytest.approx(-d('years', 1e-5)/365, rel=1e-6)


@pytest.mark.parametrize('kind', ['call', 'put'])
@pytest.mark.parametrize('vol', [.1, .2, .8, 2])
def test_iv_roundtrip(kind, vol):
    x = replace(BASE, kind=kind, volatility=vol, dividend_yield=.02)
    assert european_iv(x, european_price(x)) == pytest.approx(vol, abs=1e-8)


def test_invalid_and_nonidentifiable_iv():
    lo, hi = european_bounds(BASE)
    for p in (0, lo, hi, hi+1):
        assert european_iv(BASE, p) is None
    assert european_iv(replace(BASE, years=0), 2) is None
    assert european_iv(BASE, 50, max_vol=.1) is None
    with pytest.raises(ValueError):
        european_iv(BASE, float('nan'))


@pytest.mark.parametrize('field,value', [('spot', 0), ('strike', -1), ('years', -1),
    ('volatility', -1), ('rate', float('inf')), ('dividend_yield', float('nan')),
    ('kind', 'CALL')])
def test_reject_invalid_inputs(field, value):
    with pytest.raises(ValueError):
        replace(BASE, **{field: value})


def test_expiry_zero_vol_and_explicit_multiplier():
    assert european_price(replace(BASE, years=0, spot=110)) == 10
    assert european_greeks(replace(BASE, years=0)) is None
    assert european_greeks(replace(BASE, volatility=0)) is None
    assert european_price(replace(BASE, volatility=0)) == european_bounds(BASE)[0]
    assert long_option_pnl(110, 100, 'call', 3, multiplier=100, fees=2) == 698
    assert long_option_pnl(0, 100, 'call', 3, multiplier=10) == -30
    with pytest.raises(ValueError):
        long_option_pnl(100, 100, 'put', 2, multiplier=100, contracts=True)
