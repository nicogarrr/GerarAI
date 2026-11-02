"""Chat «¿qué posición va peor/mejor?»: una posición sin cotización real no entra en el ranking.

Sin cotización guardada, el ledger valora la posición al precio de su última
compra o venta (auditoría A3): su rentabilidad sale ~0 % (o la de las
comisiones) y parece medida. Cartera, impuestos y el contexto del Cerebro ya la
marcan «sin cotización real» (``trade_price_fallbacks``); el ranking del chat
la ordenaba como una más y hasta podía encabezarlo («la que peor va»).
"""

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Position, Transaction
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el ranking no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    # (ticker, cantidad, precio de compra, precio guardado, cotización guardada?)
    for ticker, qty, buy, mark, quoted in (("UBER", 10, "100", "150", True), ("MSFT", 10, "100", "90", True),
                                            ("NEWCO", 10, "100", "100", False)):
        company = Company(ticker=ticker, name=ticker, exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="EUR")
        db.add(company)
        db.flush()
        db.add(Transaction(tenant_id=1, company_id=company.id, trade_date=date(2026, 10, 1), action="buy",
                           quantity=Decimal(qty), price=Decimal(buy), fees=Decimal("1"), currency="EUR"))
        if quoted:
            db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 29), open=Decimal(mark),
                               high=Decimal(mark), low=Decimal(mark), close=Decimal(mark)))
        value = Decimal(qty) * Decimal(mark)
        cost = Decimal(qty) * Decimal(buy) + 1
        db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal(qty), average_cost=cost / qty,
                        market_price=Decimal(mark), market_value=value, market_value_native=value,
                        market_value_base=value, cost_basis_native=cost, cost_basis_base=cost, currency="EUR",
                        base_currency="EUR", as_of=date(2026, 10, 30), source="postgres_ledger"))
    db.commit()
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_unquoted_position_is_left_out_of_the_ranking():
    resp = _ask(_db(), "¿Qué posición va peor?")
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.startswith("La que peor va sobre su coste: MSFT")
    assert "1. MSFT" in resp.answer and "2. UBER" in resp.answer
    assert "3." not in resp.answer
    assert "Sin cotización real (valoradas al precio de su última operación), fuera: NEWCO." in resp.answer


def test_quoted_positions_unchanged():
    resp = _ask(_db(), "¿Cuál es mi mejor posición?")
    assert resp.answer.startswith("La que mejor va sobre su coste: UBER +49,9 % (+499,00 €).")
