"""Estimador Ledoit-Wolf (app/valuation/risk_matrix.py): oraculo y propiedades.

El caso pequeno esta fijado contra sklearn.covariance.ledoit_wolf
(scikit-learn 1.x, objetivo identidad escalada mu*I, Ledoit-Wolf 2004):
shrinkage 0.4706259802725595 y la matriz de abajo para ORACLE_X. La
implementacion se verifico ademas bit a bit (<1e-15) contra sklearn en
(60,3), (252,8), (100,2) y (61,5) con datos aleatorios sembrados.
"""

from __future__ import annotations

import numpy as np

from app.valuation.risk_matrix import (
    correlation_from_covariance,
    ledoit_wolf_covariance,
    risk_contributions,
)

ORACLE_X = np.array(
    [
        [0.01, -0.02, 0.005],
        [-0.005, 0.01, -0.003],
        [0.002, -0.001, 0.004],
        [0.0, 0.003, -0.002],
        [-0.007, 0.008, 0.001],
    ]
)
ORACLE_SHRINKAGE = 0.4706259802725595
ORACLE_COV = np.array(
    [
        [4.400851751420307e-05, -3.260943961521034e-05, 6.987737060402216e-06],
        [-3.260943961521034e-05, 8.593493987661638e-05, -1.3975474120804433e-05],
        [6.987737060402216e-06, -1.3975474120804433e-05, 3.045654260918059e-05],
    ]
)


def test_ledoit_wolf_matches_sklearn_oracle() -> None:
    cov, shrinkage = ledoit_wolf_covariance(ORACLE_X)
    assert abs(shrinkage - ORACLE_SHRINKAGE) < 1e-12
    assert np.abs(cov - ORACLE_COV).max() < 1e-15


def test_ledoit_wolf_properties_on_random_data() -> None:
    rng = np.random.RandomState(7)
    x = rng.multivariate_normal(np.zeros(6), np.eye(6) * 0.0004 + 0.0001, size=120)
    cov, shrinkage = ledoit_wolf_covariance(x)
    assert 0.0 <= shrinkage <= 1.0
    # Simetrica y semidefinida positiva (el objetivo mu*I lo es y la
    # combinacion convexa conserva la propiedad).
    assert np.abs(cov - cov.T).max() < 1e-15
    assert np.linalg.eigvalsh(cov).min() > -1e-12
    # Diagonal encogida = (1-d)*s_ii + d*mu.
    demeaned = x - x.mean(axis=0)
    sample = (demeaned.T @ demeaned) / len(x)
    mu = float(np.trace(sample)) / 6
    expected_diag = (1.0 - shrinkage) * np.diagonal(sample) + shrinkage * mu
    assert np.abs(np.diagonal(cov) - expected_diag).max() < 1e-15


def test_ledoit_wolf_single_asset_no_shrinkage() -> None:
    x = np.array([[0.01], [-0.02], [0.005], [0.0], [-0.003]])
    cov, shrinkage = ledoit_wolf_covariance(x)
    assert shrinkage == 0.0
    demeaned = x - x.mean(axis=0)
    assert abs(cov[0][0] - float((demeaned**2).sum()) / len(x)) < 1e-15


def test_ledoit_wolf_already_scaled_identity() -> None:
    # Columnas centradas con la misma varianza y covarianza cero: la muestra
    # ya es mu*I salvo ruido de coma flotante (1 ulp entre diagonales por el
    # orden de la suma), asi que encoger hacia mu*I no cambia nada: la salida
    # debe quedar pegada a la muestral aunque el shrinkage salga alto.
    a, b = 0.01, 0.02
    x = np.array([[a, b], [-a, -b], [b, -a], [-b, a]])
    cov, shrinkage = ledoit_wolf_covariance(x)
    assert 0.0 <= shrinkage <= 1.0
    demeaned = x - x.mean(axis=0)
    sample = (demeaned.T @ demeaned) / len(x)
    assert np.abs(cov - sample).max() < 1e-12


def test_correlation_from_covariance_known_case() -> None:
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    corr = correlation_from_covariance(cov)
    assert abs(corr[0][1] - 0.01 / 0.06) < 1e-12
    assert corr[0][0] == 1.0 and corr[1][1] == 1.0


def test_correlation_from_covariance_zero_variance_axis() -> None:
    cov = np.array([[0.0, 0.0], [0.0, 0.09]])
    corr = correlation_from_covariance(cov)
    assert corr[0][0] == 1.0 and corr[1][1] == 1.0
    assert corr[0][1] == 0.0 and corr[1][0] == 0.0


def test_risk_contributions_single_asset() -> None:
    shares, marginal, vol = risk_contributions(np.array([1.0]), np.array([[0.04]]))
    assert shares[0] == 1.0
    assert abs(vol - 0.2) < 1e-12
    assert abs(marginal[0] - 0.2) < 1e-12


def test_risk_contributions_hand_computed() -> None:
    # Sigma w = [0.025, 0.05]; var = 0.0375; cuotas = [1/3, 2/3].
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    shares, marginal, vol = risk_contributions(np.array([0.5, 0.5]), cov)
    assert abs(shares[0] - 1.0 / 3.0) < 1e-12
    assert abs(shares[1] - 2.0 / 3.0) < 1e-12
    assert abs(shares.sum() - 1.0) < 1e-12
    assert abs(vol - np.sqrt(0.0375)) < 1e-12


def test_risk_contributions_zero_variance_degenerates_evenly() -> None:
    shares, marginal, vol = risk_contributions(np.array([0.7, 0.3]), np.zeros((2, 2)))
    assert vol == 0.0
    assert np.abs(shares - 0.5).max() < 1e-15
    assert np.abs(marginal).max() == 0.0
