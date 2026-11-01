"""Preguntas fiscales que no llegaban al bloque fiscal del contexto personal.

«¿Cuánto IRPF pagaré este año?» o «¿Cuánta retención me han aplicado este
año?» respondían «No puedo responderte con fuentes ahora mismo» (la regex
pedía «retenciones» y el verbo en primera persona no contaba como pregunta
personal). «¿Cuánto he ganado en 2025?» y «¿qué ganancias patrimoniales tengo
en 2026?» daban la rentabilidad acumulada de hoy, ignorando el año.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, Transaction

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


class _NoLLM:
    name = "no-llm"

    async def complete(self, *args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("no LLM")


@pytest.fixture
def db(monkeypatch):
    import app.core.local_date as local_date

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    company = Company(
        ticker="KO", name="Coca-Cola", exchange="NYSE", company_type="platform",
        valuation_model="unassigned", currency="EUR",
    )
    session.add(company)
    session.flush()
    for trade_date, action, qty, price in (
        (date(2024, 1, 5), "buy", "30", "50"),
        (date(2025, 6, 2), "sell", "10", "60"),
        (date(2026, 10, 1), "sell", "10", "75"),
    ):
        session.add(Transaction(
            tenant_id=1, company_id=company.id, trade_date=trade_date, action=action,
            quantity=Decimal(qty), price=Decimal(price), fees=Decimal("0"), currency="EUR",
        ))
    session.add(Position(
        tenant_id=1, company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("50"),
        market_value=Decimal("800"), market_value_native=Decimal("800"), market_value_base=Decimal("800"),
        cost_basis_native=Decimal("500"), cost_basis_base=Decimal("500"), currency="EUR",
        base_currency="EUR", as_of=date(2026, 10, 30),
    ))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _ask(db, question):
    from app.services.chat_service import ChatService

    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize(("question", "year", "realized"), [
    ("¿Cuánto IRPF pagaré este año?", 2026, "250,00"),
    ("¿Cuánta retención me han aplicado este año?", 2026, "250,00"),
    ("¿Qué impuestos pago este año?", 2026, "250,00"),
    ("¿Cuánto IRPF pagué en 2025?", 2025, "100,00"),
    ("¿Cuánto he ganado en 2025?", 2025, "100,00"),
    ("¿qué ganancias patrimoniales tengo en 2026?", 2026, "250,00"),
])
def test_la_pregunta_fiscal_usa_el_bloque_fiscal_del_ejercicio(db, question, year, realized):
    response = _ask(db, question)
    assert (response.llm_trace or {}).get("path") == "personal_context", response.answer
    assert f"Ejercicio {year}" in response.answer
    assert f"realizada {realized}" in response.answer


@pytest.mark.parametrize("question", [
    "¿Cuánto he ganado?",
    "¿Qué ganancias tengo?",
    "¿Cuál es la rentabilidad de mi cartera?",
])
def test_sin_ejercicio_sigue_la_rentabilidad_de_hoy(db, question):
    assert (_ask(db, question).llm_trace or {}).get("path") == "portfolio_performance"


@pytest.mark.parametrize("question", [
    "¿Qué son las ganancias patrimoniales?",
    "¿Cuánto IRPF se paga por dividendos?",
    "¿Cuánto pago de comisión en el broker?",
])
def test_conceptos_y_otros_pagos_no_son_el_bloque_fiscal(question):
    from app.services.personal_answer import detect_personal_intent

    intent = detect_personal_intent(question)
    assert intent is None or intent.kind != "fiscal"
