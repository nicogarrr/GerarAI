"""Cerebro nunca suma ni rotula en EUR un valor NATIVO sin convertir.

``Position.market_value`` está en la moneda de la posición. Con base EUR, una
posición en GBp sin tipo de cambio (``market_value_base`` None) valía 150.000
peniques y Cerebro la mostraba como «valor 150.000,00 €», la sumaba al total y
diluía el peso de las demás: AAA (900 € reales, la única con valor conocido)
salía con un 0,6 % en vez de 100 %.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent, Position
from app.services.chat_service import ChatService
from app.services.position_value import position_base_value


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _seed(db):
    a = Company(ticker="AAA", name="Alpha", exchange="NYSE", company_type="operating", valuation_model="unassigned")
    b = Company(ticker="BBB", name="Beta", exchange="LSE", company_type="operating", valuation_model="unassigned")
    db.add_all([a, b])
    db.flush()
    db.add(Position(tenant_id=1, company_id=a.id, quantity=Decimal("10"), average_cost=Decimal("80"), currency="USD",
                    base_currency="EUR", market_value=Decimal("1000"), market_value_base=Decimal("900"), as_of=date(2026, 10, 29)))
    db.add(Position(tenant_id=1, company_id=b.id, quantity=Decimal("100"), average_cost=Decimal("1400"), currency="GBp",
                    base_currency="EUR", market_value=Decimal("150000"), market_value_base=None, as_of=date(2026, 10, 29)))
    db.commit()
    return a, b


def _ask(db, question):
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


def test_overview_never_labels_native_pence_as_euros_nor_sums_them(db):
    _seed(db)
    resp = _ask(db, "¿Qué tengo en mi cartera?")
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert "150.000" not in resp.answer
    assert "valor total 900" in resp.answer
    aaa = next(line for line in resp.answer.splitlines() if line.startswith("- AAA"))
    bbb = next(line for line in resp.answer.splitlines() if line.startswith("- BBB"))
    assert "(100 %)" in aaa
    assert "sin valor en" in bbb and "%" not in bbb


def test_position_weight_uses_only_values_in_base_currency(db):
    _seed(db)
    resp = _ask(db, "¿Qué peso tiene AAA en mi cartera?")
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "100 %" in resp.answer
    resp_b = _ask(db, "¿Qué peso tiene BBB en mi cartera?")
    assert resp_b.llm_trace["path"] == "portfolio_position"
    assert "150.000" not in resp_b.answer and "%" not in resp_b.answer
    assert "sin valor en" in resp_b.answer


def test_prompt_context_weights_skip_unconverted_positions(db):
    _seed(db)
    ctx = {row["ticker"]: row["weight_pct"] for row in ChatService()._portfolio_positions_context(db)}
    assert ctx == {"AAA": 100.0, "BBB": None}


def test_news_answer_weight_ignores_unconverted_native_value(db):
    a, _ = _seed(db)
    db.add(NewsEvent(tenant_id=1, company_id=a.id, title="Resultados de AAA", source="SEC", url="https://example.com/a"))
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1
    from app.services.brain_data_tools import _company_news_answer

    resp = _company_news_answer(db, a, 1)
    assert "el 100,00 % de tu cartera" in resp.answer


def test_base_value_rules():
    def pos(**kw):
        defaults = {"currency": "USD", "base_currency": "EUR", "market_value": Decimal("10"),
                    "market_value_base": None, "valuation_hold_reason": None}
        defaults.update(kw)
        return Position(**defaults)

    assert position_base_value(pos(market_value_base=Decimal("9"))) == Decimal("9")
    assert position_base_value(pos(currency="EUR")) == Decimal("10")
    assert position_base_value(pos()) is None
    assert position_base_value(pos(currency="GBp", base_currency="GBP")) is None  # peniques != libras
    assert position_base_value(pos(market_value_base=Decimal("9"), valuation_hold_reason="split")) is None
