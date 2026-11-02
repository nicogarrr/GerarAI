"""/portfolio/intelligence: retornos diarios en una pasada, mismo resultado bit a bit.

``_returns`` validaba cada cierre dos veces (como anterior y como actual),
``_portfolio_returns`` sumaba con generadores sobre tuplas por dia y
``_fill_trailing_spot`` recorria toda la serie para encontrar el ultimo cierre
ajustado. Con 300 posiciones x 5 anos eran ~1,3 s de CPU por peticion. Estos
tests comparan con las implementaciones de antes (copiadas aqui) en series
con ceros, huecos, None, cola spot y pesos ausentes: el resultado tiene que ser
IDENTICO (==, mismas claves, mismo orden), no aproximado.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


def _returns_antes(series):
    result = {}
    for previous, current in zip(series, series[1:]):
        prev_close = previous.adj_close
        curr_close = current.adj_close
        if prev_close and curr_close and prev_close > 0 and curr_close > 0:
            result[current.date] = float(curr_close / prev_close - 1)
    return result


def _portfolio_returns_antes(returns, weights):
    by_date = defaultdict(list)
    for company_id, series in returns.items():
        for day, value in series.items():
            by_date[day].append((weights.get(company_id, 0), value))
    result = {}
    for day, values in sorted(by_date.items()):
        active_weight = sum(weight for weight, _ in values)
        if active_weight > 0:
            result[day] = sum(weight * value for weight, value in values) / active_weight
    return result


def _fill_antes(series):
    last_valid = -1
    for index, row in enumerate(series):
        if row.adj_close and row.adj_close > 0:
            last_valid = index
    if last_valid < 0 or last_valid == len(series) - 1:
        return series
    filled = list(series[: last_valid + 1])
    for row in series[last_valid + 1 :]:
        if row.close and row.close > 0:
            filled.append(
                SimpleNamespace(date=row.date, close=row.close, adj_close=row.close, source=row.source)
            )
        else:
            filled.append(row)
    return filled


def _serie(seed: int, n: int, *, huecos: bool = True, cola: int = 0) -> list[SimpleNamespace]:
    rnd = random.Random(seed)
    start = date(2021, 1, 4) + timedelta(days=rnd.randrange(0, 40))
    price = Decimal(str(round(rnd.uniform(5, 500), 4)))
    rows = []
    for i in range(n):
        price = (price * Decimal(str(round(1 + rnd.gauss(0.0003, 0.02), 6)))).quantize(Decimal("0.000001"))
        adj = price
        if huecos:
            roll = rnd.random()
            if roll < 0.03:
                adj = Decimal("0")
            elif roll < 0.05:
                adj = None
            elif roll < 0.06:
                adj = Decimal("-1")
        rows.append(SimpleNamespace(date=start + timedelta(days=i), close=price, adj_close=adj, source="t"))
    for i in range(cola):
        close = rows[-1].close if rows else Decimal("10")
        rows.append(
            SimpleNamespace(date=start + timedelta(days=n + i), close=close, adj_close=None, source="spot")
        )
    return rows


def _igual(a: dict, b: dict) -> bool:
    return list(a.items()) == list(b.items())


def test_returns_identico_al_de_antes():
    for seed in range(60):
        serie = _serie(seed, random.Random(seed).randrange(0, 400))
        assert _igual(PortfolioIntelligenceService._returns(serie), _returns_antes(serie))
    assert PortfolioIntelligenceService._returns([]) == {}


def test_fill_trailing_spot_identico_al_de_antes():
    casos = [_serie(s, 50, cola=s % 4) for s in range(40)]
    casos += [
        [],
        _serie(1, 3, cola=5),
        [SimpleNamespace(date=date(2024, 1, 1), close=None, adj_close=None, source="x")],
    ]
    casos.append(
        _serie(2, 30, huecos=False)
        + [SimpleNamespace(date=date(2030, 1, 1), close=Decimal("0"), adj_close=None, source="spot")]
    )
    for serie in casos:
        nueva = PortfolioIntelligenceService._fill_trailing_spot(serie)
        antes = _fill_antes(serie)
        assert [(r.date, r.close, r.adj_close, r.source) for r in nueva] == [
            (r.date, r.close, r.adj_close, r.source) for r in antes
        ]
        if antes is serie:
            assert nueva is serie


def test_portfolio_returns_identico_al_de_antes():
    for seed in range(25):
        rnd = random.Random(seed)
        returns = {
            cid: _returns_antes(_fill_antes(_serie(seed * 100 + cid, rnd.randrange(20, 300))))
            for cid in range(1, rnd.randrange(2, 30))
        }
        weights = {cid: rnd.random() for cid in returns if rnd.random() > 0.15}
        if seed % 5 == 0:
            weights = dict.fromkeys(returns, 0.0)
        assert _igual(
            PortfolioIntelligenceService._portfolio_returns(returns, weights),
            _portfolio_returns_antes(returns, weights),
        )
    assert PortfolioIntelligenceService._portfolio_returns({}, {}) == {}
