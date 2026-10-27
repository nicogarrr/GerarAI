"""IRPF de una venta con la posición guardada (prueba real realqa-23).

«¿Cuánto IRPF pagaría si vendo hoy todo UBER?» respondía «no tengo su
posición» con 30 UBER guardadas: el verbo «vendo» sacaba la pregunta de la
ruta de posición y el sintetizador de empresa no recibía la cartera. Además
trataba de usted.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services import prompt_registry
from app.services.chat_service import ChatService
from app.services.personal_answer import CHAT_PERSONAL


class _NoLLM:
    name = "no-llm"

    async def complete(self, *args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("la simulación de IRPF no llama al LLM")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker="UBER", name="Uber Technologies"):
    comp = Company(ticker=ticker, name=name, exchange="NYSE", company_type="platform", valuation_model="unassigned")
    db.add(comp)
    db.flush()
    return comp


def _uber(db, *, value_base: str | None = "2400", cost_base: str | None = "1904.76"):
    comp = _company(db)
    db.add(Position(
        tenant_id=1, company_id=comp.id, quantity=Decimal("30"), average_cost=Decimal("75"),
        market_value=Decimal("2700"), market_value_native=Decimal("2700"),
        market_value_base=None if value_base is None else Decimal(value_base),
        cost_basis_native=Decimal("2250"),
        cost_basis_base=None if cost_base is None else Decimal(cost_base),
        currency="USD", base_currency="EUR", as_of=date(2026, 10, 27),
    ))
    db.commit()
    return comp


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_irpf_si_vendo_todo_uber_usa_la_posicion(db):
    _uber(db)
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["provider_calls"] == 0
    assert "no tengo" not in resp.answer.lower()
    assert "30 acciones de UBER" in resp.answer
    # 2.400 − 1.904,76 = 495,24 € de ganancia; 19 % → 94,10 €.
    assert "ganancia de 495,24 €" in resp.answer
    assert "IRPF estimado: 94,10 €" in resp.answer
    assert {s["type"] for s in resp.sources} == {"position"}


def test_irpf_responde_de_tu_nunca_de_usted(db):
    _uber(db)
    answer = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?").answer.lower()
    assert "usted" not in answer
    assert "su posición" not in answer
    assert "tus 30 acciones" in answer


def test_venta_parcial_prorratea_coste_y_valor(db):
    _uber(db)
    resp = _ask(db, "Si vendo 10 acciones de UBER, ¿cuánto pago a Hacienda?")
    assert "10 de tus 30 acciones de UBER" in resp.answer
    assert "valor 800,00 €" in resp.answer
    assert "coste 634,92 €" in resp.answer


def test_venta_en_perdidas_no_paga_y_avisa_de_los_dos_meses(db):
    _uber(db, value_base="1500")
    resp = _ask(db, "IRPF si vendo todo UBER")
    assert "pérdida de 404,76 €" in resp.answer
    assert "No pagarías IRPF" in resp.answer
    assert "dos meses" in resp.answer


def test_sin_coste_en_euros_lo_dice_y_no_inventa_cuota(db):
    _uber(db, cost_base=None)
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert "IRPF estimado" not in resp.answer
    assert "falta el coste en euros" in resp.answer
    assert "30 acciones de UBER" in resp.answer
    assert "ganancia de 450,00 USD" in resp.answer


def test_sin_posicion_en_el_ticker_lo_dice(db):
    _uber(db)
    _company(db, "AAPL", "Apple")
    db.commit()
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo AAPL?")
    assert "No tienes ninguna posición guardada en AAPL" in resp.answer


def test_impuestos_de_la_empresa_no_es_tu_irpf(db):
    from app.services.chat_service import _SALE_CONTEXT_RE, _SALE_TAX_RE

    question = "¿Cuántos impuestos paga UBER al año?"
    assert _SALE_TAX_RE.search(question)
    assert not _SALE_CONTEXT_RE.search(question)


def test_los_prompts_del_cerebro_exigen_tuteo():
    for text in (prompt_registry.CHAT_SOURCE_SYNTHESIS, prompt_registry.CHAT_GENERAL, CHAT_PERSONAL):
        assert "usted" in text.lower()
        assert "tú" in text
