"""/portfolio/intelligence: correlaciones con numpy, iguales a Pearson en Python (<= 1e-9).

Las correlaciones eran ~1 s de los ~2,6 s del endpoint con 300 posiciones
(un producto escalar en Python por par: 44.850 pares). Ahora cada grupo de
pares con el mismo calendario comun se calcula con numpy de una vez. Nico
acepto diferencias de redondeo de hasta 1e-9; estos tests fijan esa
tolerancia frente a la formula de siempre y que se conservan los N/D
(serie constante, historico corto, sin serie), los conteos, la diagonal, la
simetria exacta y el orden de las claves.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from statistics import mean
from types import SimpleNamespace

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService as S

TOL = 1e-9


def _reference(returns, rows):
    result: dict = {}
    observations: dict = {}
    for _, left_company in rows:
        result[left_company.ticker] = {}
        observations[left_company.ticker] = {}
        for _, right_company in rows:
            left = returns.get(left_company.id, {})
            right = returns.get(right_company.id, {})
            dates = sorted(left.keys() & right.keys())
            observations[left_company.ticker][right_company.ticker] = len(dates)
            if left_company.id == right_company.id and dates:
                correlation = 1.0
            elif len(dates) < S.MIN_CORRELATION_OBSERVATIONS:
                correlation = None
            else:
                xs, ys = [left[d] for d in dates], [right[d] for d in dates]
                x_mean, y_mean = mean(xs), mean(ys)
                numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
                denominator = math.sqrt(
                    sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys)
                )
                correlation = numerator / denominator if denominator else None
            result[left_company.ticker][right_company.ticker] = correlation
    return result, observations


def _assert_parity(returns, rows):
    result, observations = S._correlations(returns, rows)  # noqa: SLF001
    expected, expected_obs = _reference(returns, rows)
    assert observations == expected_obs
    assert list(result) == list(expected)
    assert [list(r) for r in result.values()] == [list(r) for r in expected.values()]
    for left, row in expected.items():
        for right, value in row.items():
            got = result[left][right]
            if value is None:
                assert got is None, (left, right, got)
            else:
                assert type(got) is float, (left, right, type(got))
                assert abs(got - value) <= TOL, (left, right, got, value)
            assert got == result[right][left]  # simetria exacta
    return result


def _rows(ids, dup=()):
    rows = [(None, SimpleNamespace(id=cid, ticker=f"T{cid}")) for cid in ids]
    rows += [(None, SimpleNamespace(id=cid, ticker=f"T{cid}")) for cid in dup]
    return rows


def _series(rng, days, start=0, gap=0.0):
    d0 = date(2022, 1, 3)
    return {
        d0 + timedelta(days=i): rng.gauss(0.0004, 0.02) for i in range(start, days) if rng.random() >= gap
    }


def test_mismo_calendario_grupo_denso():
    rng = random.Random(1)
    returns = {cid: _series(rng, 400) for cid in range(1, 31)}
    _assert_parity(returns, _rows(returns))


def test_calendarios_desalineados_huecos_y_cortas():
    rng = random.Random(2)
    returns = {cid: _series(rng, 520, start=(cid % 5) * 37, gap=0.04) for cid in range(1, 26)}
    returns[7] = _series(rng, 520, start=500)  # 20 dias: justo el minimo con algunas
    returns[8] = _series(rng, 520, start=505)  # corta: N/D
    returns[9] = dict.fromkeys(returns[1], 0.0)  # varianza cero: N/D
    returns[10] = dict.fromkeys(returns[2], 0.1)  # constante no nula: N/D
    returns.pop(11)  # posicion sin serie
    result = _assert_parity(returns, _rows(range(1, 26), dup=(3, 11)))
    assert result["T9"]["T1"] is None
    assert result["T10"]["T4"] is None
    assert result["T10"]["T10"] == 1.0
    assert result["T11"]["T11"] is None


def test_calendarios_escalonados_grupos_dispersos():
    # Cada serie empieza un dia distinto: casi cada par tiene su calendario
    # comun y se calcula por la via de pares sueltos (no la matriz).
    rng = random.Random(3)
    returns = {cid: _series(rng, 300, start=cid * 3) for cid in range(1, 41)}
    _assert_parity(returns, _rows(returns))


def test_series_identicas_y_casi_constantes():
    rng = random.Random(4)
    base = _series(rng, 120)
    returns = {
        1: dict(base),
        2: dict(base),
        3: {d: v * -2.0 for d, v in base.items()},
        4: {d: 0.01 + (1e-9 if i % 2 else 0.0) for i, d in enumerate(base)},
    }
    result = _assert_parity(returns, _rows(returns))
    assert abs(result["T1"]["T2"] - 1.0) <= TOL
    assert abs(result["T1"]["T3"] + 1.0) <= TOL


def test_sin_posiciones_y_una_sola():
    assert S._correlations({}, []) == ({}, {})  # noqa: SLF001
    rng = random.Random(5)
    returns = {1: _series(rng, 50)}
    _assert_parity(returns, _rows(returns))
