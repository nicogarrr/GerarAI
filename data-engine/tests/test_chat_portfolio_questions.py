"""Preguntas de cartera sin la formula "mi cartera" (recuento, peso, neto).

Siguen la misma ruta determinista que "mi cartera" (#1188): datos guardados
del tenant, sin LLM y sin recomendaciones.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Company, FXRate, Position
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker, name):
    comp = Company(ticker=ticker, name=name, exchange="NYSE", company_type="holding", valuation_model="unassigned")
    db.add(comp)
    db.flush()
    return comp


def _position(db, company, qty, cost, value, currency="EUR"):
    pos = Position(
        tenant_id=1, company_id=company.id, quantity=Decimal(str(qty)),
        average_cost=Decimal(str(cost)), market_value=Decimal(str(value)),
        currency=currency, base_currency="EUR",
        as_of=date(2026, 10, 16),
    )
    db.add(pos)
    return pos


def test_cuantas_posiciones_sin_mi_cartera(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    _position(db, a, 10, 5, 300)
    _position(db, b, 2, 50, 100)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Cuántas posiciones tengo y cuál pesa más?", "portfolio", None))
    assert resp.model == "deterministic"
    assert resp.llm_trace["provider_calls"] == 0
    assert "2 posiciones" in resp.answer
    # La mayor primero: responde tambien a "cual pesa mas".
    assert resp.answer.index("AAA") < resp.answer.index("BBB")
    assert "75 %" in resp.answer


def test_patrimonio_neto_con_caja_y_margen(db):
    a = _company(db, "AAA", "Alpha")
    _position(db, a, 10, 5, 16237.91)
    db.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("7933.60"), as_of=date(2026, 10, 16)))
    db.add(CashBalance(tenant_id=1, currency="USD", balance=Decimal("-17541.34"), as_of=date(2026, 10, 16)))
    db.add(FXRate(tenant_id=1, base_currency="EUR", quote_currency="USD", rate=Decimal("1"), rate_date=date(2026, 10, 16)))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Cuánto vale mi patrimonio neto?", "portfolio", None))
    assert resp.llm_trace["provider_calls"] == 0
    assert "caja 7.933,60 €" in resp.answer
    assert "deuda de margen 17.541,34 €" in resp.answer
    assert "patrimonio neto 6.630,17 €" in resp.answer
    assert "recomendación" not in resp.answer


def test_peso_de_ticker_responde_con_la_posicion(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    b = _company(db, "BBB", "Beta")
    _position(db, a, 100, 40, 4066)
    _position(db, b, 2, 50, 12194)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué peso tiene ASTS en mi cartera?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "ASTS" in resp.answer
    assert "25 %" in resp.answer
    assert "100 acciones" in resp.answer
    assert {s["type"] for s in resp.sources} == {"position"}


def test_peso_y_patrimonio_en_la_misma_pregunta(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    _position(db, a, 100, 40, 4066)
    db.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("1000"), as_of=date(2026, 10, 16)))
    db.commit()
    resp = asyncio.run(ChatService().answer(
        db, "¿Cuál es el peso de ASTS en mi cartera y cuánto vale mi patrimonio neto?", "portfolio", None,
    ))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "100 %" in resp.answer
    assert "patrimonio neto 5.066,00 €" in resp.answer


def test_ticker_sin_posicion_lo_dice_sin_inventar(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    b = _company(db, "BBB", "Beta")
    _position(db, b, 2, 50, 100)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué peso tiene ASTS en mi cartera?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "No tienes ninguna posición guardada en ASTS" in resp.answer
    assert "1 posiciones" in resp.answer
    assert resp.sources == []


def test_divisa_sin_tipo_de_cambio_no_se_inventa_el_neto(db):
    a = _company(db, "AAA", "Alpha")
    _position(db, a, 10, 5, 300)
    db.add(CashBalance(tenant_id=1, currency="USD", balance=Decimal("500"), as_of=date(2026, 10, 16)))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Cuál es mi patrimonio neto?", "portfolio", None))
    assert "Sin tipo de cambio guardado para USD" in resp.answer
    assert "patrimonio neto" not in resp.answer


def test_orden_sigue_fuera_de_la_ruta_determinista(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    _position(db, a, 100, 40, 4066)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "Vende mi posición de ASTS", "portfolio", None))
    assert resp.llm_trace.get("path") != "portfolio_position"


def test_otro_tenant_no_aparece_en_peso_ni_neto(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    b = _company(db, "SECRET", "Other tenant co")
    _position(db, a, 100, 40, 4066)
    db.commit()
    db.info["tenant_id"] = 2
    db.add(Position(tenant_id=2, company_id=b.id, quantity=Decimal("9"), average_cost=Decimal("1"), market_value=Decimal("9999")))
    db.add(CashBalance(tenant_id=2, currency="EUR", balance=Decimal("9999"), as_of=date(2026, 10, 16)))
    db.commit()
    db.info["tenant_id"] = 1
    resp = asyncio.run(ChatService().answer(db, "peso de ASTS y patrimonio neto", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "9.999" not in resp.answer
    assert "SECRET" not in resp.answer


def test_currency_symbol_only_for_eur_unknown_preserved():
    from app.services.chat_service import _currency_display
    assert _currency_display("EUR") == "€"
    assert _currency_display("USD") == "USD"
    assert _currency_display("XYZ") == "XYZ"


def test_posicion_con_mas_peso_respuesta_directa(db):
    a = _company(db, "GOOGL", "Alphabet")
    b = _company(db, "JPM", "JPMorgan")
    _position(db, a, 15, 360, 300)
    _position(db, b, 7, 310, 100)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Cuál es mi posición con más peso?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_ranking"
    assert "GOOGL" in resp.answer
    assert "el 75 % de tu cartera" in resp.answer
    # Respuesta directa: no el volcado de la tabla completa.
    assert "acciones, coste medio" not in resp.answer


def test_posicion_que_pesa_menos_respuesta_directa(db):
    a = _company(db, "GOOGL", "Alphabet")
    b = _company(db, "JPM", "JPMorgan")
    _position(db, a, 15, 360, 300)
    _position(db, b, 7, 310, 100)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué posición pesa menos?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_ranking"
    assert resp.answer.startswith("Tu posición con el peso más bajo es JPM")


def test_rentabilidad_cartera_simple_sobre_coste(db):
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    _position(db, a, 10, 5, 300)   # coste 50, valor 300
    _position(db, b, 2, 50, 100)   # coste 100, valor 100
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué rentabilidad tiene mi cartera?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert "+166,67 %" in resp.answer
    assert "no TWR" in resp.answer
    assert "no cuenta caja, dividendos ni ventas cerradas" in resp.answer


def test_rentabilidad_posicion_concreta_y_no_tenida(db):
    a = _company(db, "AMZN", "Amazon.com")
    b = _company(db, "KO", "Coca-Cola")
    _position(db, a, 10, 100, 1250)  # coste 1000, valor 1250 -> +25 %
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué rentabilidad tiene AMZN?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert "tu posición en AMZN" in resp.answer
    assert "+25 %" in resp.answer
    resp_ko = asyncio.run(ChatService().answer(db, "¿Qué rentabilidad tiene KO?", "portfolio", None))
    assert resp_ko.llm_trace["path"] == "portfolio_performance"
    assert "No tienes ninguna posición abierta en KO" in resp_ko.answer
def test_cuanto_pesa_ticker_sin_posicion_lo_dice_sin_inventar(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    b = _company(db, "BBB", "Beta")
    _position(db, b, 2, 50, 100)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Cuánto pesa ASTS en mi cartera?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "No tienes ninguna posición guardada en ASTS" in resp.answer


def test_cuanto_pesa_ticker_con_posicion_da_su_peso(db):
    a = _company(db, "ASTS", "AST SpaceMobile")
    b = _company(db, "BBB", "Beta")
    _position(db, a, 100, 40, 4066)
    _position(db, b, 2, 50, 100)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Cuánto pesa ASTS?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "Tu posición guardada en ASTS" in resp.answer
    assert "97,6 %" in resp.answer


def test_rentabilidad_no_cuenta_coste_desconocido_como_cero(db):
    """average_cost=0 (default de la columna) es coste desconocido, no gratis:
    antes la posicion sumaba todo su valor como ganancia ficticia (+400 %)."""
    a = _company(db, "AAA", "Alpha")
    b = _company(db, "BBB", "Beta")
    _position(db, a, 10, 10, 120)   # coste 100, valor 120 -> +20 %
    _position(db, b, 5, 0, 380)     # coste desconocido
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué rentabilidad tiene mi cartera?", "portfolio", None))
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert "+400 %" not in resp.answer
    assert "+20 %" in resp.answer
    assert "BBB" in resp.answer and "Sin coste de compra guardado" in resp.answer


def test_rentabilidad_todas_sin_coste_no_inventa(db):
    a = _company(db, "AAA", "Alpha")
    _position(db, a, 10, 0, 120)
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "¿Qué rentabilidad tiene mi cartera?", "portfolio", None))
    assert "No tengo el coste de compra guardado" in resp.answer
