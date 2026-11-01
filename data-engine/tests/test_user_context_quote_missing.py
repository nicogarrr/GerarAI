"""Contexto del Cerebro: una posición sin cotización real no aporta P&L latente.

Sin cotización guardada, la posición del ledger se valora con el precio de su
última operación (auditoría A3). /portfolio/positions e Impuestos ya enseñan esa
plusvalía como desconocida, pero el contexto del chat la sumaba como medida:
compras a 10 y 14 → «P&L +40,00 EUR (+16,7 %)» inventado, y el total de la
cartera y el ranking de pérdidas/ganancias del chat lo arrastraban.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Company, Portfolio, Position, Transaction
from app.services.user_context import build_user_context
from tests.cerebro_seed import NOW, TODAY, fake_dca_reader, seeded_session


@pytest.fixture
def db():
    session = seeded_session()
    comp = Company(
        ticker="ZQX", name="Zeta Quoteless", exchange="BME", currency="EUR", sector="Industrials",
        industry="x", company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    session.add(comp)
    session.flush()
    portfolio = session.scalar(select(Portfolio).where(Portfolio.tenant_id == 1))
    assert portfolio is not None
    for qty, price, day in (("10", "10", date(2026, 3, 2)), ("10", "14", date(2026, 6, 1))):
        session.add(Transaction(
            tenant_id=1, company_id=comp.id, action="buy", quantity=Decimal(qty), price=Decimal(price),
            fees=Decimal("0"), currency="EUR", trade_date=day,
        ))
    # Lo que deja rebuild_position sin cotización: precio = el de la última compra.
    session.add(Position(
        tenant_id=1, portfolio_id=portfolio.id, company_id=comp.id, quantity=Decimal("20"),
        average_cost=Decimal("12"), market_price=Decimal("14"), market_value=Decimal("280"),
        market_value_base=Decimal("280"), cost_basis_base=Decimal("240"),
        unrealized_pnl_base=Decimal("40"), unrealized_pnl=Decimal("40"), currency="EUR",
        base_currency="EUR", as_of=TODAY, source="postgres_ledger",
    ))
    session.flush()
    yield session
    session.close()


def _ctx(db):
    ctx = build_user_context(db, today=TODAY, now=NOW, dca_reader=fake_dca_reader)
    assert ctx is not None
    return ctx


def test_sin_cotizacion_no_hay_pnl_inventado_en_el_contexto(db):
    ctx = _ctx(db)
    text = ctx.render()
    line = next(row for row in text.splitlines() if row.startswith("- ZQX ("))
    assert "P&L" not in line
    assert "sin cotización real" in line
    rows = {row["ticker"]: row for row in ctx.blocks["cartera"].rows}
    assert rows["ZQX"]["pnl"] is None
    assert rows["ZQX"]["pnl_pct"] is None


def test_sin_cotizacion_el_total_no_suma_su_pnl(db):
    text = _ctx(db).render()
    # Sin ZQX: 10.000 − 7.850 = +2.150 EUR (+27,4 %); ZQX no suma ni coste ni P&L.
    assert "P&L latente +2.150,00 EUR (+27,4 % sobre coste)" in text
    assert "+2.190,00" not in text


def test_con_cotizacion_posterior_el_pnl_vuelve(db):
    from app.models import MarketPrice

    comp = db.scalar(select(Company).where(Company.ticker == "ZQX"))
    db.add(MarketPrice(company_id=comp.id, date=date(2026, 10, 1), close=Decimal("14")))
    db.flush()
    line = next(row for row in _ctx(db).render().splitlines() if row.startswith("- ZQX ("))
    assert "P&L +40,00 EUR" in line
