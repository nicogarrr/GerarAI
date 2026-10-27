"""/portfolio/intelligence: la beta y las correlaciones no repiten medias exactas.

``_beta`` recalculaba ``mean(portfolio)`` DENTRO del generador de la covarianza:
una media exacta de n valores por cada una de las n observaciones (O(n^2); con
5 años de historia, ~1.250 x 1.250). ``_correlations`` calculaba 2 medias por
par y cada par dos veces (a-b y b-a): 684 medias con 19 posiciones. El
endpoint tardaba ~1 s por peticion en CPU pura. Estos tests fijan cuantas
medias se calculan y que los valores son EXACTAMENTE los de la formula de
siempre (mismas sumas, mismo orden).
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from statistics import mean
from types import SimpleNamespace

import pytest

from app.services import portfolio_intelligence_service as module
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


def _serie(seed: int, n: int, start: date = date(2021, 1, 4)) -> dict[date, float]:
    rnd = random.Random(seed)
    return {start + timedelta(days=i): rnd.gauss(0.0005, 0.02) for i in range(n)}


def _correlacion_referencia(left: dict[date, float], right: dict[date, float]) -> float | None:
    """La formula de Pearson tal y como estaba (sin caches)."""
    dates = sorted(left.keys() & right.keys())
    xs, ys = [left[d] for d in dates], [right[d] for d in dates]
    x_mean, y_mean = mean(xs), mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return numerator / denominator if denominator else None


@pytest.fixture
def contador_de_medias(monkeypatch):
    llamadas = {"n": 0}

    def _mean(values):
        llamadas["n"] += 1
        return mean(values)

    monkeypatch.setattr(module, "mean", _mean)
    return llamadas


def _filas(n: int):
    return [
        (SimpleNamespace(id=i), SimpleNamespace(id=i, ticker=f"T{i:02d}"))
        for i in range(n)
    ]


def test_correlaciones_calculan_cada_media_una_vez(contador_de_medias):
    filas = _filas(12)
    returns = {i: _serie(i, 300) for i in range(12)}
    PortfolioIntelligenceService._correlations(returns, filas)
    # Mismas fechas para todas: una media por serie, no 2 por par ordenado.
    assert contador_de_medias["n"] == 12


def test_correlaciones_identicas_a_la_formula_y_simetricas():
    filas = _filas(6)
    returns = {i: _serie(100 + i, 250) for i in range(6)}
    # Una serie con huecos: el solape cambia por par y la media tambien.
    returns[5] = {d: v for k, (d, v) in enumerate(_serie(7, 260).items()) if k % 3}
    result, observations = PortfolioIntelligenceService._correlations(returns, filas)
    for i in range(6):
        for j in range(6):
            a, b = f"T{i:02d}", f"T{j:02d}"
            esperado = 1.0 if i == j else _correlacion_referencia(returns[i], returns[j])
            assert result[a][b] == esperado
            assert result[a][b] == result[b][a]
            assert observations[a][b] == len(returns[i].keys() & returns[j].keys())


def test_beta_calcula_la_media_de_la_cartera_una_vez(monkeypatch, contador_de_medias):
    cartera = _serie(1, 1250)
    mercado = _serie(2, 1250)
    prices = []
    nivel = 100.0
    dias = sorted(mercado)
    prices.append(SimpleNamespace(date=dias[0] - timedelta(days=1), adj_close=nivel))
    for d in dias:
        nivel *= 1 + mercado[d]
        prices.append(SimpleNamespace(date=d, adj_close=nivel))
    monkeypatch.setattr(module, "_benchmark_prices", lambda db, cutoff: prices)
    beta, meta = PortfolioIntelligenceService._beta(None, cartera, date(2020, 1, 1))  # type: ignore[arg-type]
    assert meta["status"] == "calculated"
    assert contador_de_medias["n"] == 2
    # Valor exacto con la formula de covarianza/varianza de siempre.
    market_returns = PortfolioIntelligenceService._returns(prices)
    fechas = sorted(cartera.keys() & market_returns.keys())
    p = [cartera[d] for d in fechas]
    m = [market_returns[d] for d in fechas]
    pm, mm = mean(p), mean(m)
    esperado = sum((x - pm) * (y - mm) for x, y in zip(p, m)) / sum((y - mm) ** 2 for y in m)
    assert beta == esperado
