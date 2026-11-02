"""Chat: «¿cuántas acciones de KO tengo?» sin KO y con una sola posición.

Decía «tu cartera guardada tiene 1 posiciones abiertas en otros tickers» (el
inglés ya distinguía el singular). Ahora «1 posición abierta en otro ticker».
"""
import asyncio
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Position
from app.models.entities import Base
from app.services.chat_service import ChatService


def _db(n_positions):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    for ticker in ("KO", "UBER", "MSFT"):
        db.add(Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned", currency="USD"))
    db.flush()
    ids = {c.ticker: c.id for c in db.query(Company).all()}
    for ticker in ("UBER", "MSFT")[:n_positions]:
        db.add(Position(tenant_id=1, company_id=ids[ticker], quantity=30, average_cost=50, currency="EUR",
                        market_value=2400, market_value_base=2400, as_of=date(2026, 10, 30)))
    db.commit()
    return db


def _ask(db):
    return asyncio.run(ChatService().answer(db, "¿Cuántas acciones de KO tengo?", "portfolio", None))


def test_one_other_position_is_singular():
    resp = _ask(_db(1))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert resp.answer == ("No tienes ninguna posición guardada en KO; "
                           "tu cartera guardada tiene 1 posición abierta en otro ticker.")


def test_two_other_positions_stay_plural():
    resp = _ask(_db(2))
    assert resp.answer == ("No tienes ninguna posición guardada en KO; "
                           "tu cartera guardada tiene 2 posiciones abiertas en otros tickers.")
