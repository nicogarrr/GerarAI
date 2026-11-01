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
    assert resp.answer.startswith("No tienes AAPL en cartera, así que no puedo calcular tu IRPF real.")


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


def test_lotes_en_dolares_al_cambio_de_la_venta(db):
    """Same FX criterion as the tax report (DGT V0152-26, see
    memory/gerarai_tax_facts and tax_report_service.replay_tax_fifo): the gain
    is computed in the share's currency and converted ONCE at the sale-date
    rate; the purchase-date rate (0,90) no longer prices the cost.
    """
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
    # Cambio de la venta implícito en la posición: 2.400 € / 2.700 $.
    # Coste 2.250 $ × 2.400/2.700 = 2.000 €; ganancia 2.400 − 2.000 = 400 €
    # (= (2.700 − 2.250) $ × 2.400/2.700). Antes: 2.250 × 0,90 = 2.025 € y 375 €.
    assert resp.llm_trace["method"] == "fifo"
    assert "coste 2.000,00 €" in resp.answer
    assert "ganancia de 400,00 €" in resp.answer


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


def test_la_escala_del_ahorro_no_se_presenta_como_vigente_sin_verificar(db):
    """Solo la escala de 2025 está verificada: en años posteriores el texto lo dice."""
    _uber(db)
    answer = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?").answer
    year = date.today().year
    if year <= 2025:
        assert f"escala del ahorro {year}" in answer
    else:
        assert "escala del ahorro de 2025 (la última verificada" in answer
        assert f"la de {year} no está confirmada" in answer
        assert f"escala del ahorro {year}:" not in answer
    assert "IRPF estimado: 94,10 €" in answer


# ------------------------------------------- sin posición e hipotético
# Revisión de Nico: «¿cuánto IRPF pagaría si vendo AAPL?» sin AAPL en
# cartera cambiaba a la información de la empresa sin decir que no calculaba
# el impuesto. Ahora lo dice, ofrece la estimación y, con los lotes, la hace.

_NO_AAPL = (
    "No tienes AAPL en cartera, así que no puedo calcular tu IRPF real. "
    "Si me dices cuántas acciones, a qué precio y cuándo las compraste, te hago la estimación."
)


def _aapl_con_cotizacion(db):
    from app.models.entities import MarketPrice

    comp = _company(db, "AAPL", "Apple Inc.")
    db.add(MarketPrice(company_id=comp.id, date=date(2026, 10, 23), open=Decimal("230"), high=Decimal("231"),
                       low=Decimal("229"), close=Decimal("230"), source="yahoo"))
    db.commit()
    return comp


def test_aapl_sin_posicion_dice_que_no_calcula_y_ofrece_estimacion(db):
    _uber(db)
    _aapl_con_cotizacion(db)
    resp = _ask(db, "¿cuánto IRPF pagaría si vendo AAPL?")
    assert resp.answer == _NO_AAPL
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["no_position"] is True
    assert resp.llm_trace["provider_calls"] == 0
    # Nada de la ficha de la empresa: ni cotización ni fuentes ajenas.
    assert "cotiza" not in resp.answer
    assert resp.sources == []


def test_aapl_fuera_del_maestro_no_cae_en_ticker_desconocido(db):
    _uber(db)
    resp = _ask(db, "¿cuánto IRPF pagaría si vendo AAPL?")
    assert resp.answer == _NO_AAPL
    assert resp.llm_trace["path"] == "portfolio_sale_tax"


def test_aapl_por_su_nombre_sin_posicion(db):
    _uber(db)
    _aapl_con_cotizacion(db)
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo mis acciones de Apple?")
    assert resp.answer == _NO_AAPL


def test_aapl_con_posicion_calcula_fifo(db):
    comp = _company(db, "AAPL", "Apple Inc.")
    comp.currency = "EUR"
    _tx(db, comp, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, comp, date(2025, 3, 10), "buy", 10, 200)
    _eur_position(db, comp, 20, 180, 150)
    db.commit()
    resp = _ask(db, "¿cuánto IRPF pagaría si vendo 10 AAPL?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["method"] == "fifo"
    assert "No tienes" not in resp.answer
    assert "ganancia de 800,00 €" in resp.answer
    assert "IRPF estimado: 152,00 €" in resp.answer


def test_hipotetico_con_lotes_da_la_cifra_fifo(db):
    _uber(db)
    resp = _ask(
        db,
        "¿Cuánto IRPF pagaría si compré 10 acciones de AAPL a 100 € y otras 10 a 200 € y vendo 10 a 180 €?",
    )
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["hypothetical"] is True
    assert resp.llm_trace["provider_calls"] == 0
    # El caso de Nico, por FIFO: 1.800 − 1.000 = 800 € (no 300 € a coste medio).
    assert "Estimación hipotética de AAPL" in resp.answer
    assert "ganancia de 800,00 €" in resp.answer
    assert "IRPF estimado: 152,00 €" in resp.answer
    assert "Método FIFO" in resp.answer
    assert "en el orden en que me los das" in resp.answer


def test_hipotetico_en_dolares_al_cambio_de_la_venta(db):
    """DGT V0152-26 (criterion of the tax report): native gain × sale-date rate."""
    _aapl_con_cotizacion(db)
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=date(2024, 3, 1),
                  rate=Decimal("0.90"), source="test"))
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=date.today(),
                  rate=Decimal("0.80"), source="test"))
    db.commit()
    resp = _ask(db, "IRPF si vendo AAPL: compré 10 acciones a 150 $ el 1 de marzo de 2024")
    # Venta a la última cotización (230 $ × 10 × 0,80 = 1.840 €); coste al
    # cambio de la venta: 150 $ × 10 × 0,80 = 1.200 € (no 1.350 € al 0,90 de
    # la compra). Ganancia 640 €; IRPF 19 % = 121,60 €.
    assert resp.llm_trace["hypothetical"] is True
    assert "última cotización guardada" in resp.answer
    assert "valor 1.840,00 €" in resp.answer
    assert "coste 1.200,00 €" in resp.answer
    assert "ganancia de 640,00 €" in resp.answer
    assert "IRPF estimado: 121,60 €" in resp.answer


def test_hipotetico_responde_a_la_oferta_del_turno_anterior(db):
    from app.schemas import ChatTurn

    _uber(db)
    history = [
        ChatTurn(role="user", content="¿cuánto IRPF pagaría si vendo AAPL?"),
        ChatTurn(role="assistant", content=_NO_AAPL),
    ]
    resp = asyncio.run(ChatService(provider=_NoLLM()).answer(
        db, "10 acciones a 100 € y las vendo a 150 €", "global", None, history=history,
    ))
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert resp.llm_trace["ticker"] == "AAPL"
    assert "ganancia de 500,00 €" in resp.answer
    assert "IRPF estimado: 95,00 €" in resp.answer


def test_hipotetico_sin_precio_de_venta_lo_pide(db):
    _uber(db)
    resp = _ask(db, "IRPF si vendo AAPL que compré: 10 acciones a 100 € el 3 de marzo de 2024")
    assert resp.llm_trace["hypothetical"] is True
    assert "IRPF estimado" not in resp.answer
    assert "¿a qué precio las venderías?" in resp.answer


def test_impuestos_que_paga_aapl_siguen_en_la_ficha_de_empresa(db):
    _uber(db)
    _aapl_con_cotizacion(db)
    resp = _ask(db, "¿Cuántos impuestos paga AAPL?")
    assert resp.llm_trace.get("path") != "portfolio_sale_tax"
    assert "No tienes AAPL en cartera" not in resp.answer
    assert "AAPL" in resp.answer



def test_sin_coste_guardado_no_dice_coste_medio_cero(db):
    """average_cost=0 (default) es coste desconocido: la respuesta decia
    «a un coste medio de 0,00 USD»."""
    comp = _company(db)
    db.add(Position(
        tenant_id=1, company_id=comp.id, quantity=Decimal("30"), average_cost=Decimal("0"),
        market_value=Decimal("2700"), market_value_native=Decimal("2700"),
        market_value_base=Decimal("2400"), cost_basis_native=None, cost_basis_base=None,
        currency="USD", base_currency="EUR", as_of=date(2026, 10, 27),
    ))
    db.commit()
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo UBER?")
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert "coste medio de 0,00" not in resp.answer
    assert "sin coste medio guardado" in resp.answer
    assert "ganancia de" not in resp.answer


def test_lotes_en_peniques_al_cambio_de_la_venta(db):
    """Londres en peniques («GBp»): mismo criterio que el informe fiscal.

    La divisa de la venta se ponía en mayúsculas («GBP») y dejaba de coincidir
    con la de los lotes («GBp»): el coste salía al cambio de la COMPRA y la
    cifra no cuadraba con la renta. Compra 10 a 2.600 p (cambio 1,10 €/£);
    hoy valen 26.500 p = 300 €: coste 26.000 × 300/26.500 = 294,34 €,
    ganancia 5,66 € (antes 286,00 € y 14,00 €).
    """
    comp = Company(ticker="SHEL.L", name="Shell plc", exchange="LSE", company_type="standard",
                   valuation_model="unassigned", currency="GBp")
    db.add(comp)
    db.flush()
    db.add(FXRate(base_currency="EUR", quote_currency="GBP", rate_date=date(2026, 3, 2),
                  rate=Decimal("1.10"), source="test"))
    _tx(db, comp, date(2026, 3, 2), "buy", 10, 2600, currency="GBp")
    db.add(Position(
        tenant_id=1, company_id=comp.id, quantity=Decimal("10"), average_cost=Decimal("2600"),
        market_value=Decimal("26500"), market_value_native=Decimal("26500"), market_value_base=Decimal("300"),
        cost_basis_native=Decimal("26000"), cost_basis_base=Decimal("286"),
        currency="GBp", base_currency="EUR", as_of=date.today(),
    ))
    db.commit()
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo hoy todo SHEL.L?")
    assert resp.llm_trace["method"] == "fifo"
    assert "coste 294,34 €" in resp.answer
    assert "ganancia de 5,66 €" in resp.answer


def test_precio_en_libras_con_lotes_en_peniques(db):
    """Precio de venta dado en libras («a 30 £») con lotes en peniques.

    «GBP» y «GBp» son la misma divisa: el coste va al cambio de la venta,
    como en el informe fiscal, no al de la compra. Compra 10 a 2.600 p
    (1,10 €/£); hoy 1,15 €/£ y venta a 30 £: valor 345,00 €, coste
    260 £ × 1,15 = 299,00 €, ganancia 46,00 € (antes 286,00 € y 59,00 €).
    """
    comp = Company(ticker="SHEL.L", name="Shell plc", exchange="LSE", company_type="standard",
                   valuation_model="unassigned", currency="GBp")
    db.add(comp)
    db.flush()
    db.add(FXRate(base_currency="EUR", quote_currency="GBP", rate_date=date(2026, 3, 2),
                  rate=Decimal("1.10"), source="test"))
    db.add(FXRate(base_currency="EUR", quote_currency="GBP", rate_date=date.today(),
                  rate=Decimal("1.15"), source="test"))
    _tx(db, comp, date(2026, 3, 2), "buy", 10, 2600, currency="GBp")
    db.add(Position(
        tenant_id=1, company_id=comp.id, quantity=Decimal("10"), average_cost=Decimal("2600"),
        market_value=Decimal("26500"), market_value_native=Decimal("26500"), market_value_base=Decimal("300"),
        cost_basis_native=Decimal("26000"), cost_basis_base=Decimal("286"),
        currency="GBp", base_currency="EUR", as_of=date.today(),
    ))
    db.commit()
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo 10 SHEL.L a 30 £?")
    assert resp.llm_trace["method"] == "fifo"
    assert resp.llm_trace["sale_price_source"] == "usuario"
    assert "coste 299,00 €" in resp.answer
    assert "ganancia de 46,00 €" in resp.answer
