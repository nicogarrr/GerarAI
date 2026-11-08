"""Asequibilidad con varias divisas y cantidades con decimales (Nico, 2026-11-08 21:49 Madrid).

1. Caja en EUR y USD sin tipo de cambio guardado: «¿me da para 2 META a
   600 USD?» respondía «no te llega, faltan 600 USD» ignorando los 3.200 €.
   Ahora convierte con el tipo oficial guardado (BCE) y lo cita con su fecha;
   sin tipo, dice qué saldo no pudo convertir y no concluye.
2. «0,5 acciones» salía «0 acciones son 300 USD»: ahora «0,5 acciones».
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


def _db(*, fx: bool):
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
    if fx:
        # 1 USD = 0,8 EUR (BCE) → 1 EUR = 1,25 USD.
        session.add(
            FXRate(
                tenant_id=1,
                base_currency="EUR",
                quote_currency="USD",
                rate=Decimal("0.8"),
                rate_date=date(2026, 11, 6),
                source="ECB",
            )
        )
    session.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("3200"), as_of=date(2026, 11, 7)))
    session.add(CashBalance(tenant_id=1, currency="USD", balance=Decimal("600"), as_of=date(2026, 11, 7)))
    session.commit()
    return session


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None)).answer  # type: ignore[arg-type]


def test_mixed_cash_without_rate_does_not_drop_the_euros():
    answer = _ask(_db(fx=False), "¿Me da el efectivo para comprar 2 acciones de META?")
    assert "no te llega" not in answer
    assert "No pude convertir 3.200,00 €" in answer
    assert "no puedo decirte si te llega" in answer
    assert "600,00 USD" in answer


def test_mixed_cash_with_official_rate_is_converted_and_cited():
    answer = _ask(_db(fx=True), "¿Me da el efectivo para comprar 2 acciones de META?")
    # 3.200 € × 1,25 + 600 USD = 4.600 USD frente a 1.200 USD.
    assert "1 € = 1,2500 USD (BCE, 6 nov 2026)" in answer
    assert "4.600,00 USD" in answer and "te llega y sobran 3.400,00 USD" in answer


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("¿Me da el efectivo para comprar 0,5 acciones de META?", "0,5 acciones son 300,00 USD"),
        ("¿Tengo suficiente dinero para comprar 1,25 acciones de META?", "1,25 acciones son 750,00 USD"),
        ("¿Me da el efectivo para comprar 1 acciones de META?", "1 acción es 600,00 USD"),
    ],
)
def test_fractional_quantity_keeps_its_decimals(question, text):
    assert text in _ask(_db(fx=True), question)
