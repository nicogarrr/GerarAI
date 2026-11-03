"""Empresas nombradas como las nombra la gente («Santander», «Coca-Cola», «cocacola»).

Prueba real del chat (2026-11-02): con SAN.MC («Banco Santander») y KO
(«The Coca-Cola Company») en cartera, «Si vendo todas mis acciones de
Santander…» contestaba «No tienes Santander en cartera», y «¿Cuánto me
pagará Coca-Cola en dividendos?» llegaba al modelo sin la posición (que
pedía «cuántas acciones tienes» e inventaba cifras).
"""

from __future__ import annotations

from app.models.entities import Company
from app.services.company_names import companies_named_in


def _c(cid, ticker, name):
    c = Company(ticker=ticker, name=name)
    c.id = cid
    return c


_UNIVERSE = [
    _c(1, "SAN.MC", "Banco Santander, S.A."),
    _c(2, "KO", "The Coca-Cola Company"),
    _c(3, "SAB.MC", "Banco de Sabadell, S.A."),
    _c(4, "AAPL", "Apple Inc."),
    _c(5, "BAC", "Bank of America Corporation"),
]


def _tickers(q):
    return [c.ticker for c in companies_named_in(q, _UNIVERSE).companies]


def test_banco_santander_se_nombra_por_santander():
    assert _tickers("Si vendo todas mis acciones de Santander hoy, ¿cuánto pagaría de IRPF?") == ["SAN.MC"]


def test_coca_cola_con_guion_y_junto():
    assert _tickers("¿Cuánto me pagará Coca-Cola en dividendos el próximo año?") == ["KO"]
    assert _tickers("cuanto valen mis aciones de cocacola") == ["KO"]


def test_sin_falsos_positivos():
    # «santander» en minúscula sigue siendo palabra corriente; «Sabadell»
    # (con conector «de») no se activa por la segunda palabra; «el banco»
    # no nombra a ninguna empresa.
    assert _tickers("vivo en santander") == []
    assert _tickers("¿Qué tal el banco?") == []
    assert _tickers("¿Cómo va la bolsa en America?") == []
    assert _tickers("¿Y Apple?") == ["AAPL"]
