"""_correlations reutiliza desviaciones por serie y da el mismo coeficiente bit a bit.

Cada par repetia tres sumas sobre ~500 dias; dos de ellas (las sumas de
cuadrados) solo dependen de la serie y de las fechas, no del par. Con 30
posiciones son 435 pares. Este test fija que el resultado es IDENTICO (==, no
aproximado) a la formula de Pearson de antes, incluidos los pares con fechas
distintas, los N/D por historico corto y la diagonal.
"""

import math
import random
from datetime import date, timedelta
from statistics import mean
from types import SimpleNamespace

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService as S


def _reference(left, right, min_obs):
    dates = tuple(sorted(left.keys() & right.keys()))
    if left is right and dates:
        return 1.0, len(dates)
    if len(dates) < min_obs:
        return None, len(dates)
    xs, ys = [left[d] for d in dates], [right[d] for d in dates]
    xm, ym = mean(xs), mean(ys)
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - xm) ** 2 for x in xs) * sum((y - ym) ** 2 for y in ys))
    return (num / den if den else None), len(dates)


def test_correlations_identical_to_reference_formula():
    rng = random.Random(11)
    d0 = date(2024, 1, 1)
    returns = {}
    for cid in range(1, 9):
        start = 0 if cid != 7 else 400  # serie corta: pares con pocas fechas comunes
        returns[cid] = {
            d0 + timedelta(days=i): rng.gauss(0, 0.02)
            for i in range(start, 520)
            if rng.random() > 0.05  # huecos distintos por serie
        }
    returns[8] = dict.fromkeys(returns[8], 0.0)  # varianza cero -> N/D
    rows = [(None, SimpleNamespace(id=cid, ticker=f"T{cid}")) for cid in returns]

    result, observations = S._correlations(returns, rows)

    for _, a in rows:
        for _, b in rows:
            expected, count = _reference(returns[a.id], returns[b.id], S.MIN_CORRELATION_OBSERVATIONS)
            assert observations[a.ticker][b.ticker] == count
            assert result[a.ticker][b.ticker] == expected, (a.ticker, b.ticker)
    assert result["T8"]["T1"] is None
