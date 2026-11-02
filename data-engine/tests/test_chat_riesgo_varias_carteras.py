"""Chat: la caída máxima y el TWR con varias carteras describen cada una.

Antes el riesgo del chat tomaba las fotos de la cartera con la foto más
reciente de cualquiera y la presentaba como «tu cartera»: con «Largo plazo» y
«Trading», una de las dos desaparecía. Ahora, con varias, una línea por
cartera; con una, la respuesta no cambia.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Portfolio, PortfolioDailySnapshot
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _snapshots(db, name, returns, *, tenant=1, end_offset=0):
    portfolio = Portfolio(tenant_id=tenant, name=name)
    db.add(portfolio)
    db.flush()
    start = date.today() - timedelta(days=len(returns) + end_offset)
    for i, ret in enumerate(returns):
        db.add(PortfolioDailySnapshot(
            tenant_id=tenant, portfolio_id=portfolio.id, snapshot_date=start + timedelta(days=i + 1),
            base_currency="EUR", positions_value_base=Decimal("1000"), cash_value_base=Decimal("0"),
            total_value_base=Decimal("1000"), daily_return=None if ret is None else Decimal(str(ret)),
            pricing_coverage=Decimal("1"),
        ))


def _ask(db):
    return asyncio.run(ChatService().answer(db, "¿Cuál ha sido la caída máxima de mi cartera?", "portfolio", None))


def test_each_portfolio_is_described(db):
    # Largo plazo: 1,10 → 0,88 → 0,924 (TWR -7,6 %, caída -20 %). Trading: +5 %, +5 % (TWR 10,25 %, sin caída).
    _snapshots(db, "Largo plazo", [None, 0.10, -0.20, 0.05], end_offset=1)
    _snapshots(db, "Trading", [0.05, 0.05])
    _snapshots(db, "Secreta B", [0.5, 0.5], tenant=2)
    db.commit()
    db.info["tenant_id"] = 1
    resp = _ask(db)
    assert resp.llm_trace["path"] == "portfolio_risk"
    assert "Tienes 2 carteras con fotos diarias; cada una por separado:" in resp.answer
    assert "- «Largo plazo»: Histórico de la cartera (" in resp.answer
    assert "rentabilidad TWR -7,6 %, caída máxima -20,0 %" in resp.answer
    assert "- «Trading»: Histórico de la cartera (" in resp.answer
    assert "rentabilidad TWR 10,3 %, caída máxima 0,0 %" in resp.answer
    assert "Secreta" not in resp.answer and "125" not in resp.answer


def test_single_portfolio_answer_is_unchanged(db):
    _snapshots(db, "Única", [None, 0.10, -0.20, 0.05])
    db.commit()
    db.info["tenant_id"] = 1
    resp = _ask(db)
    assert "carteras con fotos diarias" not in resp.answer
    assert "Histórico de la cartera (" in resp.answer and "rentabilidad TWR -7,6 %" in resp.answer
