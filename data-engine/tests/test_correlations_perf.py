"""_correlations no re-ordena las fechas comunes por par.

Con P posiciones la interseccion de fechas se ordenaba por cada par
(O(P^2) sorts de ~D fechas). Las fechas de cada serie se ordenan UNA vez
y la interseccion reutiliza tuplas ya ordenadas: el numero de llamadas a
sorted queda acotado por P. El coeficiente sigue siendo bit a bit el de la
formula de referencia (test_correlations_exact_cache).

Run from data-engine/:
    pytest tests/test_correlations_perf.py -v
"""

import builtins
import random
from datetime import date, timedelta
from types import SimpleNamespace

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService as S


def _returns(n_companies=40, n_days=300):
    rng = random.Random(7)
    d0 = date(2024, 1, 1)
    returns = {}
    for cid in range(1, n_companies + 1):
        start = 0 if cid % 3 else 50  # algunas series empiezan mas tarde
        returns[cid] = {
            d0 + timedelta(days=i): rng.gauss(0, 0.02) for i in range(start, n_days) if rng.random() > 0.03
        }
    return returns


def test_interseccion_no_se_reordena_por_par(monkeypatch):
    returns = _returns()
    rows = [(None, SimpleNamespace(id=cid, ticker=f"T{cid}")) for cid in returns]
    calls = []
    real_sorted = builtins.sorted
    monkeypatch.setattr(
        builtins, "sorted", lambda *a, **k: (calls.append(len(a[0])), real_sorted(*a, **k))[1]
    )
    S._correlations(returns, rows)
    # Antes: ~P^2 ordenaciones de la interseccion. Ahora: una por serie.
    assert len(calls) <= len(rows) + 2, f"{len(calls)} ordenaciones para {len(rows)} series"


def test_resultado_equivalente_a_la_formula():
    # Mismo contrato que test_correlations_exact_cache: el calculo no cambia.
    import math
    from statistics import mean

    returns = _returns()
    rows = [(None, SimpleNamespace(id=cid, ticker=f"T{cid}")) for cid in returns]
    result, observations = S._correlations(returns, rows)

    def reference(left, right):
        dates = tuple(sorted(left.keys() & right.keys()))
        if left is right and dates:
            return 1.0, len(dates)
        if len(dates) < S.MIN_CORRELATION_OBSERVATIONS:
            return None, len(dates)
        xs, ys = [left[d] for d in dates], [right[d] for d in dates]
        xm, ym = mean(xs), mean(ys)
        num = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
        den = math.sqrt(sum((x - xm) ** 2 for x in xs) * sum((y - ym) ** 2 for y in ys))
        return (num / den if den else None), len(dates)

    for _, a in rows:
        for _, b in rows:
            expected, count = reference(returns[a.id], returns[b.id])
            assert observations[a.ticker][b.ticker] == count
            assert result[a.ticker][b.ticker] == expected, (a.ticker, b.ticker)
