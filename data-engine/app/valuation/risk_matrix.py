"""Matriz de covarianza con shrinkage Ledoit-Wolf y contribucion al riesgo.

Estimador: Ledoit-Wolf 2004 ("A well-conditioned estimator for
large-dimensional covariance matrices", JMA) con objetivo identidad
escalada mu*I, mu = tr(S)/N. La intensidad se acota a [0, 1] como exige
el paper (kappa* es una combinacion convexa). Implementacion verificada
contra sklearn.covariance.ledoit_wolf (scikit-learn 1.x): shrinkage y
matriz identicos salvo error de redondeo de coma flotante (<1e-15) en
(60,3), (252,8), (100,2) y (61,5); los valores del oraculo fijan el caso
pequeno en tests/test_risk_matrix_estimator.py.

Solo algebra pura sobre numpy: sin llamadas de red, sin dependencias
nuevas (numpy ya es dependencia de data-engine).
"""
from __future__ import annotations

import numpy as np

ANNUALIZATION_FACTOR = 252


def ledoit_wolf_covariance(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Covarianza encogida (diaria) e intensidad de shrinkage.

    `returns` es una matriz T x N de retornos simples (una fila por
    sesion, una columna por activo), sin huecos: el llamador alinea las
    series a las fechas comunes antes de entrar aqui. T >= 2 y N >= 1.
    """
    if returns.ndim != 2 or returns.shape[0] < 2 or returns.shape[1] < 1:
        raise ValueError("returns debe ser T x N con T >= 2 y N >= 1")
    demeaned = returns - returns.mean(axis=0)
    t, n = demeaned.shape
    sample = (demeaned.T @ demeaned) / t
    mu = float(np.trace(sample)) / n
    squared = demeaned * demeaned
    # p_hat = (1/T) * sum_k ||x_k x_k' - S||_F^2, desarrollado:
    # sum(X2'X2)/T - sum(S^2). Numericamente >= 0 (estimador de varianza).
    p_hat = float((squared.T @ squared).sum()) / t - float((sample * sample).sum())
    delta = float(((sample - mu * np.eye(n)) ** 2).sum()) / n
    beta = min(p_hat / (n * t), delta)
    if delta == 0.0 or beta <= 0.0:
        # delta == 0: la muestra ya es mu*I (o N == 1), nada que encoger.
        # beta <= 0 solo por redondeo: el paper acota kappa* a [0, 1].
        shrinkage = 0.0
    else:
        shrinkage = beta / delta
    shrunk = (1.0 - shrinkage) * sample + shrinkage * mu * np.eye(n)
    return shrunk, shrinkage


def correlation_from_covariance(covariance: np.ndarray) -> np.ndarray:
    """Correlacion derivada de una covarianza: coherente con ella bit a bit.

    Una varianza <= 0 no puede venir de una covarianza valida; se deja la
    diagonal a 1 y el resto del eje a 0 en lugar de fabricar NaN.
    """
    std = np.sqrt(np.maximum(np.diagonal(covariance), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = covariance / np.outer(std, std)
    corr = np.where(np.isfinite(corr), corr, 0.0)
    np.fill_diagonal(corr, 1.0)
    return corr


def risk_contributions(weights: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Contribucion al riesgo por posicion.

    Devuelve (cuota_de_varianza_i, contribucion_marginal_i, volatilidad):
    - cuota_i = w_i * (Sigma w)_i / (w' Sigma w): suma 1 (Euler sobre la
      varianza); negativa solo si una posicion cubre a las demas.
    - marginal_i = (Sigma w)_i / sigma_p.
    - volatilidad = sqrt(w' Sigma w), en la misma base temporal que Sigma.
    """
    portfolio_variance = float(weights @ covariance @ weights)
    if portfolio_variance <= 0.0:
        shares = np.full(weights.shape, 1.0 / len(weights))
        marginal = np.zeros(weights.shape)
        return shares, marginal, 0.0
    portfolio_vol = float(np.sqrt(portfolio_variance))
    marginal_weighted = covariance @ weights
    shares = weights * marginal_weighted / portfolio_variance
    marginal = marginal_weighted / portfolio_vol
    return shares, marginal, portfolio_vol
