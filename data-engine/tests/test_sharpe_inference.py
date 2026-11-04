"""Dependent-return Sharpe inference, not iid sqrt(n) significance claims."""
import math

import numpy as np
import pytest

from app.services.sharpe_inference import sharpe_inference


def infer(values, **kwargs):
    return sharpe_inference(values, frequency="monthly", periods_per_year=12,
                            risk_free_per_period=0.001, **kwargs)


def test_hac_matches_independent_moment_matrix_calculation():
    x = np.random.default_rng(41).normal(0.012, 0.07, 240)
    out = infer(x, hac_lags=5)
    y = x - 0.001
    mu, second = np.mean(y), np.mean(y*y)
    sigma = np.sqrt(second - mu*mu)
    moments = np.column_stack((y-mu, y*y-second))
    covariance = moments.T @ moments / len(y)
    for k in range(1, 6):
        lagged = moments[k:].T @ moments[:-k] / len(y)
        covariance += (1-k/6) * (lagged+lagged.T)
    gradient = np.array([second/sigma**3, -mu/(2*sigma**3)])
    se = math.sqrt(gradient @ covariance @ gradient / len(y))
    assert out["sharpe_per_period"] == pytest.approx(mu/sigma)
    assert out["standard_error"] == pytest.approx(se)
    assert out["t_statistic"] == pytest.approx(mu/sigma/se)
    assert out["confidence_interval"][0] == pytest.approx(mu/sigma-1.959963984540054*se)
    assert out["frequency"] == "monthly"
    assert out["periods_per_year"] == 12
    assert out["risk_free_per_period"] == 0.001
    assert out["n_observations"] == 240
    assert out["selection_adjustment"] == "unknown_trials"
    assert out["validation_claim"] is False


def test_positive_serial_dependence_changes_uncertainty():
    rng = np.random.default_rng(7)
    x = np.zeros(1200)
    for i in range(1, len(x)):
        x[i] = .8*x[i-1] + rng.normal(0, .02)
    out = infer(x, hac_lags=12)
    iid = infer(x, hac_lags=0)
    assert out["standard_error"] > 1.5*iid["standard_error"]
    assert out["lag1_autocorrelation"] > .6


@pytest.mark.parametrize("n", [0, 1, 2, 12, 59])
def test_short_sample_never_produces_test_or_interval(n):
    out = infer(np.random.default_rng(0).normal(.01, .03, n))
    assert out["status"] == "insufficient_sample"
    assert out["t_statistic"] is None
    assert out["confidence_interval"] is None
    assert out["validation_claim"] is False


@pytest.mark.parametrize("values", [[.01]*80, [0.0]*80])
def test_constant_returns_are_not_infinite_sharpe(values):
    out = infer(values)
    assert out["status"] == "zero_variance"
    assert out["sharpe_per_period"] is None
    assert out["t_statistic"] is None


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "oops", True])
def test_invalid_returns_are_not_silently_dropped(bad):
    out = infer([.01, bad]*40)
    assert out["status"] == "invalid_series"
    assert out["n_observations"] == 80
    assert out["sharpe_per_period"] is None


def test_bonferroni_requires_explicit_trial_count_and_widens_interval():
    values = np.random.default_rng(7).normal(.01, .04, 240)
    raw, adjusted = infer(values), infer(values, trials=100)
    assert adjusted["selection_adjustment"] == "bonferroni_declared_trials"
    assert adjusted["adjusted_p_value"] == pytest.approx(min(1,100*raw["p_value"]))
    assert adjusted["confidence_interval"][0] < raw["confidence_interval"][0]
    assert adjusted["confidence_interval"][1] > raw["confidence_interval"][1]
    assert adjusted["validation_claim"] is False


@pytest.mark.parametrize("kwargs", [{"trials":0}, {"trials":True}, {"hac_lags":-1},
    {"hac_lags":1000}, {"confidence":1}, {"risk_free_per_period":float("inf")}])
def test_invalid_configuration_rejected(kwargs):
    args = {"frequency":"monthly", "periods_per_year":12, "risk_free_per_period":0}
    args.update(kwargs)
    with pytest.raises(ValueError):
        sharpe_inference([.01,.02]*40, **args)


def test_scale_invariance_when_rf_scales_with_returns():
    x = np.random.default_rng(11).normal(.01, .05, 160)
    a = infer(x)
    b = sharpe_inference(x*3, frequency="monthly", periods_per_year=12, risk_free_per_period=.003)
    assert a["t_statistic"] == pytest.approx(b["t_statistic"])
    assert a["confidence_interval"] == pytest.approx(b["confidence_interval"])
