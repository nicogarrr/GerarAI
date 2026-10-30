"""Seguimientos conversacionales del Cerebro: empresa desde el hilo, verbos de
orden, singular de cartera y formato monetario.

Conversaciones reales (arnes 30 oct 2026): «cuéntame de ASTS» → «¿cuánta
deuda tiene?» caia en la abstencion general; «vende mis acciones de ASTS»
volcaba los datos de la empresa; «1 posiciones abiertas»; «coste medio
25,1 USD».
"""

import asyncio
from datetime import UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm.general_concepts import DEFINITIONS
from app.models.entities import Base, Company, FinancialFact, Position
from app.schemas import ChatTurn
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker="ASTS", name="AST SpaceMobile"):
    comp = Company(ticker=ticker, name=name, exchange="NASDAQ", currency="USD",
                   company_type="holding", valuation_model="unassigned")
    db.add(comp)
    db.flush()
    return comp


def _fact(db, company, metric, value, year=2024):
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)),
                         unit="USD", period=f"FY{year}", fiscal_year=year, source_type="filing"))
    db.commit()


def _history(*pairs):
    turns = []
    for user, assistant in pairs:
        turns.append(ChatTurn(role="user", content=user))
        turns.append(ChatTurn(role="assistant", content=assistant))
    return turns


def test_followup_metric_resuelve_empresa_desde_el_hilo(db):
    c = _company(db)
    _fact(db, c, "net_debt", 180_000_000)
    history = _history(("cuéntame de ASTS", "ASTS cotiza a $61.23 ..."))
    resp = asyncio.run(
        ChatService().answer(db, "¿cuánta deuda tiene?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert resp.prompt_version != "chat-general-v4"
    assert "ASTS" in resp.answer and "euda" in resp.answer


def test_followup_efectivo_resuelve_empresa_desde_el_hilo(db):
    c = _company(db)
    _fact(db, c, "cash_and_equivalents", 567_000_000)
    history = _history(("a cuánto cotiza ASTS", "Último precio almacenado: $61.23 ..."))
    resp = asyncio.run(
        ChatService().answer(db, "¿y el efectivo?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert "ASTS" in resp.answer and "567" in resp.answer


def test_sin_historial_el_seguimiento_sigue_absteniendose(db):
    c = _company(db)
    _fact(db, c, "net_debt", 180_000_000)
    resp = asyncio.run(
        ChatService().answer(db, "¿cuánta deuda tiene?", "portfolio", None, use_jev=False)
    )
    assert resp.prompt_version == "chat-general-v4"


def test_no_arrastra_empresa_si_el_ultimo_tramo_es_de_cartera(db):
    c = _company(db)
    _fact(db, c, "cash_and_equivalents", 567_000_000)
    db.add(Position(tenant_id=1, company_id=c.id, quantity=Decimal("10"),
                    average_cost=Decimal("25"), market_value=Decimal("600")))
    db.commit()
    history = _history(
        ("cuéntame de ASTS", "ASTS cotiza a $61.23 ..."),
        ("qué tengo en mi cartera", "Tu cartera guardada tiene 1 posición abierta ..."),
    )
    resp = asyncio.run(
        ChatService().answer(db, "¿y el efectivo?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert "ASTS" not in resp.answer


def test_ticker_desconocido_gana_al_arrastre_del_hilo(db):
    _company(db)
    history = _history(("cuéntame de ASTS", "ASTS cotiza a $61.23 ..."))
    resp = asyncio.run(
        ChatService().answer(db, "¿y la deuda de RKLB?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert resp.prompt_version == "unknown-ticker-v1"
    assert "RKLB" in resp.answer


def test_verbo_de_orden_con_empresa_respuesta_honesta_sin_volcado(db):
    _company(db)
    resp = asyncio.run(
        ChatService().answer(db, "vende mis acciones de ASTS", "portfolio", None, use_jev=False)
    )
    assert resp.prompt_version == "order-verb-v1"
    assert "no ejecuto órdenes" in resp.answer.lower()
    assert "Datos almacenados" not in resp.answer
    assert resp.llm_trace["provider_calls"] == 0


def test_verbo_de_orden_no_rompe_la_ruta_de_irpf(db):
    c = _company(db)
    db.add(Position(tenant_id=1, company_id=c.id, quantity=Decimal("10"),
                    average_cost=Decimal("25"), market_value=Decimal("600"),
                    currency="USD"))
    db.commit()
    resp = asyncio.run(
        ChatService().answer(db, "¿cuánto IRPF pagaría si vendo ASTS?", "portfolio", None,
                             use_jev=False)
    )
    assert resp.prompt_version != "order-verb-v1"


def test_resumen_cartera_singular(db):
    c = _company(db)
    db.add(Position(tenant_id=1, company_id=c.id, quantity=Decimal("50"),
                    average_cost=Decimal("25.10"), market_value=Decimal("600")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿qué tengo en mi cartera?", "portfolio", None))
    assert "1 posición abierta" in resp.answer
    assert "1 posiciones" not in resp.answer


def test_coste_medio_con_dos_decimales_fijos(db):
    c = _company(db)
    db.add(Position(tenant_id=1, company_id=c.id, quantity=Decimal("50"),
                    average_cost=Decimal("25.10"), market_value=Decimal("600")))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿qué tengo en mi cartera?", "portfolio", None))
    assert "coste medio 25,10 USD" in resp.answer


def test_seguimiento_de_concepto_tras_pregunta_de_concepto(db):
    history = _history(("que es el PER", DEFINITIONS["PER"]))
    resp = asyncio.run(
        ChatService().answer(db, "¿y el FCF?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert resp.prompt_version == "local-glossary-v1"
    assert resp.answer == DEFINITIONS["flujo de caja libre"]


def test_seguimiento_de_concepto_exige_ancla_de_concepto(db):
    history = _history(("cuéntame de ASTS", "ASTS cotiza a $61.23 ..."))
    resp = asyncio.run(
        ChatService().answer(db, "¿y el FCF?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert resp.prompt_version != "local-glossary-v1"


def test_seguimiento_metrica_con_contexto_de_pagina(db):
    from datetime import date

    from app.models.entities import MarketPrice
    from app.schemas import ChatPageContext

    c = _company(db)
    _fact(db, c, "net_debt", 180_000_000)
    db.add(MarketPrice(company_id=c.id, date=date(2026, 10, 29), open=Decimal("60"),
                       high=Decimal("63"), low=Decimal("59"), close=Decimal("61.23"),
                       volume=1000, source="yahoo"))
    db.commit()
    page = ChatPageContext(path="/research/ASTS", label="Ficha de ASTS", ticker="ASTS")
    resp = asyncio.run(
        ChatService().answer(db, "¿y su deuda?", "research", None, page=page, use_jev=False)
    )
    assert "ASTS" in resp.answer and "euda" in resp.answer
    assert resp.prompt_version != "chat-general-v4"


def test_que_es_gerarai_tras_saludo_es_capacidades(db):
    resp = asyncio.run(
        ChatService().answer(db, "buenos días, ¿qué es GerarAI?", "portfolio", None, use_jev=False)
    )
    assert resp.prompt_version == "capabilities-v1"
    assert "Cerebro de GerarAI" in resp.answer


def test_seguimiento_irpf_tras_respuesta_irpf(db):
    c = _company(db)
    db.add(Position(tenant_id=1, company_id=c.id, quantity=Decimal("50"),
                    average_cost=Decimal("25.10"), market_price=Decimal("61.23"),
                    market_value=Decimal("3061.50"), currency="USD"))
    db.commit()
    first = asyncio.run(
        ChatService().answer(db, "¿cuánto IRPF pagaría si vendo ASTS?", "portfolio", None,
                             use_jev=False)
    )
    assert "IRPF" in first.answer
    history = [
        ChatTurn(role="user", content="¿cuánto IRPF pagaría si vendo ASTS?"),
        ChatTurn(role="assistant", content=first.answer),
    ]
    resp = asyncio.run(
        ChatService().answer(db, "¿y si vendo la mitad?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert resp.prompt_version == "portfolio-sale-tax-v3"
    assert "25 de tus 50 acciones" in resp.answer


def test_seguimiento_de_venta_sin_irpf_previo_no_se_inventa_ruta(db):
    _company(db)
    history = _history(("cuéntame de ASTS", "ASTS cotiza a $61.23 ..."))
    resp = asyncio.run(
        ChatService().answer(db, "¿y si vendo la mitad?", "portfolio", None,
                             history=history, use_jev=False)
    )
    assert resp.prompt_version != "portfolio-sale-tax-v3"


def test_pregunta_de_noticias_abre_con_las_noticias(db):
    from datetime import datetime

    from app.models.entities import NewsEvent

    c = _company(db)
    db.add(NewsEvent(tenant_id=1, company_id=c.id,
                     date=datetime(2026, 10, 27, tzinfo=UTC),
                     title="AST SpaceMobile presenta la solicitud definitiva a la FCC",
                     source="sec.gov", summary="s", event_type="filing"))
    db.commit()
    resp = asyncio.run(
        ChatService().answer(db, "¿qué noticias hay de ASTS?", "portfolio", None, use_jev=False)
    )
    assert resp.answer.startswith("Últimas noticias guardadas:")
    assert resp.answer.count("Últimas noticias guardadas") == 1
