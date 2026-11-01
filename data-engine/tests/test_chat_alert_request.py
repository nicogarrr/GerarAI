"""«Avísame si MSFT baja de 300» en el chat.

El chat no crea alertas, pero respondía con el volcado de datos de la
empresa («Todavía no tengo hechos financieros fiables…»), que podía leerse
como si la alerta hubiera quedado puesta. Ahora dice claramente que no la
crea y dónde crearla.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("no debe llamar al LLM")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        for ticker in ("MSFT", "UBER", "KO"):
            comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                           valuation_model="unassigned")
            session.add(comp)
            session.flush()
            session.add(Position(
                tenant_id=1, company_id=comp.id, quantity=Decimal(5), average_cost=Decimal(100),
                market_value=Decimal(600), market_value_base=Decimal(600), cost_basis_base=Decimal(500),
                currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
            ))
        session.commit()
        yield session


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize(("question", "ticker"), [
    ("Avísame si MSFT baja de 300", "MSFT"),
    ("avísame cuando UBER suba de 100", "UBER"),
    ("Ponme una alerta si KO cae por debajo de 60", "KO"),
    ("crea una alerta para MSFT a 300", "MSFT"),
    ("Alértame si UBER pasa de 90", "UBER"),
    ("vigila KO y avísame", "KO"),
])
def test_pedir_una_alerta_dice_que_el_chat_no_la_crea(db, question, ticker):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "alert_request"
    assert "No puedo crear alertas desde el chat" in resp.answer
    assert "Alertas → Nueva alerta" in resp.answer
    assert ticker in resp.answer
    assert "hechos financieros" not in resp.answer


def test_pedir_alerta_sin_empresa(db):
    resp = _ask(db, "avísame si mi cartera cae un 10 %")
    assert resp.llm_trace["path"] == "alert_request"
    assert "Alertas → Nueva alerta" in resp.answer


@pytest.mark.parametrize("question", [
    "¿Qué alertas tengo de MSFT?",
    "alertas de MSFT",
    "¿Me avisaste ayer de MSFT?",
    "¿Cómo funcionan los avisos de precio?",
])
def test_consultar_alertas_sigue_igual(db, question):
    resp = _ask(db, question)
    assert (resp.llm_trace or {}).get("path") != "alert_request"
