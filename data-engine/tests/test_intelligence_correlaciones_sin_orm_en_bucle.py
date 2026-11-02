"""/portfolio/intelligence: la matriz de correlaciones no relee atributos ORM por par.

El doble bucle de ``_correlations`` hace P^2 iteraciones (90.000 con 300
posiciones) y leia ``company.id``/``company.ticker`` varias veces en cada una:
~1 millon de lecturas de atributos ORM por peticion. Ahora se leen una vez por
fila. Estos tests fijan cuantas lecturas se hacen y que la matriz (conteos y
orden de las claves identicos; valores hasta 1e-9 desde el calculo con numpy)
es la de la formula de siempre, tambien con posiciones repetidas de la misma
empresa.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from statistics import mean

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


class _Empresa:
    lecturas = 0

    def __init__(self, company_id: int, ticker: str) -> None:
        self._id = company_id
        self._ticker = ticker

    @property
    def id(self) -> int:
        _Empresa.lecturas += 1
        return self._id

    @property
    def ticker(self) -> str:
        _Empresa.lecturas += 1
        return self._ticker


def _serie(seed: int, n: int, salto: int = 0) -> dict[date, float]:
    rnd = random.Random(seed)
    start = date(2021, 1, 4) + timedelta(days=salto)
    return {start + timedelta(days=i): rnd.gauss(0.0005, 0.02) for i in range(n) if rnd.random() > 0.03}


def _referencia(returns, rows):
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
            elif len(dates) < PortfolioIntelligenceService.MIN_CORRELATION_OBSERVATIONS:
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


def _caso(posiciones: int):
    returns = {cid: _serie(cid, 120, salto=(cid % 3) * 10) for cid in range(1, posiciones + 1)}
    returns[2] = dict(list(returns[2].items())[:15])  # historico corto -> None
    returns.pop(3)  # sin serie
    rows = [(None, _Empresa(cid, f"T{cid}")) for cid in range(1, posiciones + 1)]
    rows.append((None, _Empresa(1, "T1")))  # misma empresa en otra cartera
    return returns, rows


def test_matriz_identica_a_la_formula_de_siempre():
    returns, rows = _caso(9)
    result, observations = PortfolioIntelligenceService._correlations(returns, rows)  # noqa: SLF001
    esperado, esperadas = _referencia(returns, rows)
    assert observations == esperadas
    for fila, valores in esperado.items():
        for columna, valor in valores.items():
            obtenido = result[fila][columna]
            if valor is None:
                assert obtenido is None, (fila, columna)
            else:
                assert abs(obtenido - valor) <= 1e-9, (fila, columna)
    assert [list(fila) for fila in result.values()] == [list(fila) for fila in esperado.values()]
    assert list(result) == list(esperado)


def test_lee_id_y_ticker_una_vez_por_fila():
    returns, rows = _caso(12)
    _Empresa.lecturas = 0
    PortfolioIntelligenceService._correlations(returns, rows)  # noqa: SLF001
    # Unas pocas lecturas por FILA (id y ticker para la tabla, id para las
    # fechas ordenadas); antes eran varias por PAR (P^2: 1.886 con 13 filas).
    assert _Empresa.lecturas <= 4 * len(rows)
