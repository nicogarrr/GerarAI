"""Tests de propiedades de fórmulas técnicas y de scoring.

Casos aleatorios con semilla fija (``random.Random``), 200 por propiedad.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.market_regime_quant import paired_beta
from app.services.propicks_funnel_service import _percentile_ranks
from app.services.propicks_price_service import momentum_from_series

N_CASOS = 200


def _casos(semilla: int, n: int = N_CASOS) -> list[random.Random]:
    base = random.Random(semilla)
    return [random.Random(base.random()) for _ in range(n)]


def _sesiones(n: int) -> list[date]:
    out: list[date] = []
    day = date(2024, 1, 1)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _serie(retornos: list[float], dias: list[date], inicio: float = 100.0) -> dict[date, float]:
    precio = inicio
    out = {dias[0]: precio}
    for dia, r in zip(dias[1:], retornos, strict=False):
        precio *= 1 + r
        out[dia] = precio
    return out


@pytest.mark.parametrize("rng", _casos(301, 100), ids=lambda _: "")
def test_beta_lineal_en_la_exposicion(rng):
    """β = cov/var (CFA, Sharpe 1964): si r_i = α + k·r_m día a día, β = k;
    el mercado contra sí mismo da 1."""
    dias = _sesiones(64)
    mercado = [rng.gauss(0, 0.012) for _ in range(63)]
    alfa = rng.uniform(-0.001, 0.001)
    k = rng.uniform(-1.5, 3.0)
    activo = [alfa + k * r for r in mercado]
    if any(r <= -0.95 for r in activo):
        pytest.skip("retorno imposible en la muestra")
    bench = _serie(mercado, dias)
    out = paired_beta(_serie(activo, dias), bench, 63)
    assert out["beta"] == pytest.approx(k, abs=1e-3)
    assert paired_beta(bench, bench, 63)["beta"] == pytest.approx(1.0)


@pytest.mark.parametrize("rng", _casos(302), ids=lambda _: "")
def test_percentiles_en_cero_uno_y_monotonos(rng):
    """Percentiles por rango (Hyndman & Fan tipo 7): en [0, 1], el mínimo 0 y
    el máximo 1 cuando son únicos, monótonos con el valor e invariantes a una
    transformación creciente (×k > 0 y + c)."""
    valores = {i: float(rng.randint(-50, 50)) for i in range(rng.randint(2, 40))}
    ranks = _percentile_ranks(valores)
    assert all(0.0 <= p <= 1.0 for p in ranks.values())
    n = len(valores)
    lo, hi = min(valores.values()), max(valores.values())
    n_lo = sum(1 for v in valores.values() if v == lo)
    n_hi = sum(1 for v in valores.values() if v == hi)
    # Empates en los extremos: el rango medio (0 y 1 solo si el extremo es único).
    if lo != hi:
        assert ranks[min(valores, key=valores.__getitem__)] == pytest.approx((n_lo - 1) / 2 / (n - 1))
        assert ranks[max(valores, key=valores.__getitem__)] == pytest.approx(1 - (n_hi - 1) / 2 / (n - 1))
    for a in valores:
        for b in valores:
            if valores[a] < valores[b]:
                assert ranks[a] < ranks[b]
    k, c = rng.uniform(0.1, 10), rng.uniform(-100, 100)
    assert _percentile_ranks({i: v * k + c for i, v in valores.items()}) == ranks


@pytest.mark.parametrize("rng", _casos(303), ids=lambda _: "")
def test_momentum_invariante_a_la_escala_del_precio(rng):
    """Rentabilidad simple P_t/P_{t−d} − 1 (Jegadeesh & Titman): no cambia al
    multiplicar todos los precios (p. ej. un split ya ajustado) y reproduce la
    rentabilidad construida."""
    hoy = date(2026, 6, 30)
    dias = rng.choice([126, 182, 365])
    r = Decimal(repr(round(rng.uniform(-0.8, 3.0), 6)))
    p0 = Decimal(repr(round(rng.uniform(1, 500), 4)))
    serie = [(hoy - timedelta(days=dias + rng.randint(0, 15)), p0), (hoy, p0 * (1 + r))]
    m = momentum_from_series(serie, dias)
    assert m is not None
    assert m == pytest.approx(r)
    k = Decimal(repr(round(rng.uniform(0.01, 100), 4)))
    assert momentum_from_series([(d, p * k) for d, p in serie], dias) == pytest.approx(m)
