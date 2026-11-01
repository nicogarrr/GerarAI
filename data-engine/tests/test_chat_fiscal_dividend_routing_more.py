"""Más preguntas fiscales y de dividendos que caían en la ruta equivocada.

- «¿Cuánto me retienen en los dividendos?», «¿Cuánto debo declarar de
  dividendos en 2026?», «¿Tengo pérdidas compensables?» o «¿Puedo compensar
  pérdidas este año?» no llegaban al bloque fiscal (abstención o rentabilidad
  sobre coste).
- «¿Cuál es mi plusvalía latente?» daba la ganancia realizada del último
  ejercicio (bloque fiscal) en vez de lo no realizado de las posiciones.
- «¿Cuál es mi rentabilidad por dividendo?» devolvía la rentabilidad sobre
  coste, que precisamente excluye los dividendos.
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
        (date(2026, 4, 1), "dividend", "1", "10"),
        (date(2026, 4, 1), "withholding", "1", "1.5"),
    ):
        session.add(Transaction(
            tenant_id=1, company_id=company.id, trade_date=trade_date, action=action,
            quantity=Decimal(qty), price=Decimal(price), fees=Decimal("0"), currency="EUR",
        ))
    session.add(Position(
        tenant_id=1, company_id=company.id, quantity=Decimal("30"), average_cost=Decimal("50"),
        market_value=Decimal("1800"), market_value_native=Decimal("1800"), market_value_base=Decimal("1800"),
        cost_basis_native=Decimal("1500"), cost_basis_base=Decimal("1500"), currency="EUR",
        base_currency="EUR", as_of=date(2026, 10, 30),
    ))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _ask(db, question):
    from app.services.chat_service import ChatService

    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize(("question", "year"), [
    ("¿Cuánto me retienen en los dividendos?", 2025),
    ("¿Cuánto me han retenido este año?", 2026),
    ("¿Cuánto debo declarar de dividendos en 2026?", 2026),
    ("¿Tengo pérdidas compensables?", 2025),
    ("¿Puedo compensar pérdidas este año?", 2026),
])
def test_van_al_bloque_fiscal(db, question, year):
    response = _ask(db, question)
    assert (response.llm_trace or {}).get("path") == "personal_context", response.answer
    assert f"Ejercicio {year}" in response.answer


def test_rentabilidad_por_dividendo_no_es_la_rentabilidad_sobre_coste(db):
    response = _ask(db, "¿Cuál es mi rentabilidad por dividendo?")
    assert (response.llm_trace or {}).get("path") == "portfolio_dividends", response.answer


@pytest.mark.parametrize("question", [
    "¿Cuál es mi plusvalía latente?",
    "¿Qué plusvalías no realizadas tengo?",
    "¿Cuánta minusvalía latente tengo?",
])
def test_lo_latente_es_la_rentabilidad_de_hoy_no_el_bloque_fiscal(db, question):
    response = _ask(db, question)
    assert (response.llm_trace or {}).get("path") == "portfolio_performance", response.answer


def test_la_plusvalia_realizada_sigue_en_el_bloque_fiscal(db):
    response = _ask(db, "¿Cuál es mi plusvalía realizada?")
    assert (response.llm_trace or {}).get("path") == "personal_context"


def test_la_rentabilidad_de_la_cartera_sigue_igual(db):
    response = _ask(db, "¿Cuál es la rentabilidad de mi cartera?")
    assert (response.llm_trace or {}).get("path") == "portfolio_performance"
