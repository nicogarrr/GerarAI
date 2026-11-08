"""«¿Me da el efectivo para comprar 10 acciones de META?» es una cuenta, no una orden (benchmark Cerebro, 2026-11-08).

Antes contestaba «No ejecuto órdenes: GerarAI no compra ni vende en tu
bróker» a una pregunta de si te llega el dinero. Ahora compara tu efectivo
guardado (al tipo de cambio guardado) con el precio guardado por la cantidad
pedida. «Compra 10 acciones de META» sigue sin ejecutarse.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Company, FXRate, MarketPrice
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("la cuenta no pasa por el modelo")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    meta = Company(
        ticker="META",
        name="Meta Platforms Inc",
        exchange="NASDAQ",
        currency="USD",
        company_type="platform",
        valuation_model="unassigned",
    )
    session.add(meta)
    session.flush()
    session.add(
        MarketPrice(
            company_id=meta.id,
            date=date(2026, 11, 6),
            open=600,
            high=600,
            low=600,
            close=Decimal("600"),
            adj_close=Decimal("600"),
            volume=0,
            source="test",
        )
    )
    session.add(
        FXRate(
            tenant_id=1,
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("0.9"),
            rate_date=date(2026, 11, 6),
            source="test",
        )
    )
    session.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("3200"), as_of=date(2026, 11, 7)))
    session.commit()
    yield session
    session.close()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "question",
    [
        "¿Me da el efectivo para comprar 10 acciones de META?",
        "¿Tengo suficiente dinero para comprar 10 acciones de META?",
    ],
)
def test_affordability_is_a_calculation(db, question):
    resp = _ask(db, question)
    assert "No ejecuto órdenes" not in resp.answer
    assert "3.200,00 €" in resp.answer
    assert "6.000,00 USD" in resp.answer
    assert "no te llega" in resp.answer and "2.444,44 USD" in resp.answer


def test_without_quantity_says_how_many(db):
    resp = _ask(db, "¿Me llega el efectivo para comprar META?")
    assert "te llega para 5 acciones" in resp.answer


def test_bare_order_is_still_refused(db):
    assert "No ejecuto órdenes" in _ask(db, "Compra 10 acciones de META").answer
