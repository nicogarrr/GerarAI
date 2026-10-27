"""IRPF de una venta con la posición guardada (prueba real realqa-23) y FIFO.

«¿Cuánto IRPF pagaría si vendo hoy todo UBER?» respondía «no tengo su
posición» con 30 UBER guardadas: el verbo «vendo» sacaba la pregunta de la
ruta de posición y el sintetizador de empresa no recibía la cartera. Además
trataba de usted.

Revisión de Nico: la primera versión usaba el coste medio. El art. 37.2 LIRPF
exige FIFO: comprar 10 a 100 € y 10 a 200 € y vender 10 a 180 € es una
ganancia de 800 €, no de 300 €.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Position, Transaction
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


# --------------------------------------------------------------- FIFO

def _eur_company(db, ticker="NICO"):
    comp = Company(ticker=ticker, name="Caso Nico", exchange="BME", company_type="standard",
                   valuation_model="unassigned", currency="EUR")
    db.add(comp)
    db.flush()
    return comp


def _tx(db, comp, day, action, qty, price, currency="EUR"):
    db.add(Transaction(tenant_id=1, company_id=comp.id, trade_date=day, action=action,
                       quantity=Decimal(str(qty)), price=Decimal(str(price)), fees=Decimal("0"),
                       currency=currency))


def _eur_position(db, comp, qty, price_now, avg_cost):
    db.add(Position(
        tenant_id=1, company_id=comp.id, quantity=Decimal(str(qty)), average_cost=Decimal(str(avg_cost)),
        market_value=Decimal(str(qty * price_now)), market_value_native=Decimal(str(qty * price_now)),
        market_value_base=Decimal(str(qty * price_now)),
        cost_basis_native=Decimal(str(qty * avg_cost)), cost_basis_base=Decimal(str(qty * avg_cost)),
        currency="EUR", base_currency="EUR", as_of=date.today(),
    ))


def _caso_nico(db):
    comp = _eur_company(db)
    _tx(db, comp, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, comp, date(2025, 3, 10), "buy", 10, 200)
    _eur_position(db, comp, 20, 180, 150)
    db.commit()
    return comp


def test_caso_de_nico_fifo_da_800_y_no_300(db):
    _caso_nico(db)
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo 10 acciones de NICO?")
    assert resp.llm_trace["method"] == "fifo"
    assert "valor 1.800,00 €, coste 1.000,00 €" in resp.answer
    assert "ganancia de 800,00 €" in resp.answer
    assert "ganancia de 300,00 €" not in resp.answer
    assert "IRPF estimado: 152,00 €" in resp.answer
    assert "Método FIFO, obligatorio en IRPF" in resp.answer
    assert "10 ene 2025, 10 acciones, coste 1.000,00 €" in resp.answer
    assert "coste medio" not in resp.answer


def test_venta_que_cruza_dos_lotes(db):
    _caso_nico(db)
    resp = _ask(db, "IRPF si vendo 15 acciones de NICO")
    # 10 × 100 € + 5 × 200 € = 2.000 €; 15 × 180 € = 2.700 €.
    assert "coste 2.000,00 €" in resp.answer
    assert "ganancia de 700,00 €" in resp.answer
    assert "10 ene 2025, 10 acciones, coste 1.000,00 €" in resp.answer
    assert "10 mar 2025, 5 acciones, coste 1.000,00 €" in resp.answer


def test_venta_total_tras_una_venta_parcial_previa(db):
    comp = _eur_company(db)
    _tx(db, comp, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, comp, date(2025, 3, 10), "buy", 10, 200)
    _tx(db, comp, date(2025, 6, 2), "sell", 5, 150)  # ya consumió 5 del lote de 100 €
    _eur_position(db, comp, 15, 180, 2500 / 15)
    db.commit()
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo todo NICO?")
    assert "todas tus 15 acciones de NICO" in resp.answer
    # 5 × 100 € + 10 × 200 € = 2.500 €; 15 × 180 € = 2.700 €.
    assert "coste 2.500,00 €" in resp.answer
    assert "ganancia de 200,00 €" in resp.answer
    assert "10 ene 2025, 5 acciones, coste 500,00 €" in resp.answer


def test_perdida_con_recompra_en_dos_meses_se_aplaza(db):
    comp = _eur_company(db)
    reciente = date.today() - timedelta(days=20)
    _tx(db, comp, date(2025, 1, 10), "buy", 10, 200)
    _tx(db, comp, reciente, "buy", 10, 100)
    _eur_position(db, comp, 20, 150, 150)
    db.commit()
    resp = _ask(db, "IRPF si vendo 10 acciones de NICO")
    # FIFO vende el lote de 200 €: pérdida de 500 €, bloqueada por la compra
    # de hace 20 días, que sigue en cartera.
    assert "pérdida de 500,00 €" in resp.answer
    assert "regla de los dos meses" in resp.answer
    assert "500,00 € de la pérdida no se pueden compensar ahora" in resp.answer
    assert resp.llm_trace["wash_sale_blocked_qty"] == 10.0


def test_perdida_sin_recompra_avisa_del_plazo(db):
    comp = _eur_company(db)
    _tx(db, comp, date(2025, 1, 10), "buy", 10, 200)
    _eur_position(db, comp, 10, 150, 200)
    db.commit()
    resp = _ask(db, "IRPF si vendo todo NICO")
    assert "pérdida de 500,00 €" in resp.answer
    assert "no se pueden compensar" not in resp.answer
    assert "siempre que no recompres NICO antes del" in resp.answer


def test_lotes_en_dolares_al_tipo_de_la_fecha_de_compra(db):
    comp = _company(db)
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=date(2026, 3, 2),
                  rate=Decimal("0.90"), source="test"))
    _tx(db, comp, date(2026, 3, 2), "buy", 30, 75, currency="USD")
    db.add(Position(
        tenant_id=1, company_id=comp.id, quantity=Decimal("30"), average_cost=Decimal("75"),
        market_value=Decimal("2700"), market_value_native=Decimal("2700"), market_value_base=Decimal("2400"),
        cost_basis_native=Decimal("2250"), cost_basis_base=Decimal("2025"),
        currency="USD", base_currency="EUR", as_of=date.today(),
    ))
    db.commit()
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?")
    # 30 × 75 $ × 0,90 = 2.025 € de coste; 2.400 − 2.025 = 375 €.
    assert resp.llm_trace["method"] == "fifo"
    assert "coste 2.025,00 €" in resp.answer
    assert "ganancia de 375,00 €" in resp.answer


def test_sin_historial_de_lotes_lo_dice_y_usa_coste_medio(db):
    _uber(db)
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?")
    assert resp.llm_trace["method"] == "average_cost"
    assert "sin historial de lotes; estimación con coste medio, puede diferir de FIFO" in resp.answer
    assert "Método FIFO" not in resp.answer


def test_lotes_que_no_cuadran_con_la_posicion_no_se_usan(db):
    comp = _eur_company(db)
    _tx(db, comp, date(2025, 1, 10), "buy", 5, 100)  # faltan compras: la posición tiene 20
    _eur_position(db, comp, 20, 180, 150)
    db.commit()
    resp = _ask(db, "IRPF si vendo 10 acciones de NICO")
    assert resp.llm_trace["method"] == "average_cost"
    assert "sin historial de lotes" in resp.answer
