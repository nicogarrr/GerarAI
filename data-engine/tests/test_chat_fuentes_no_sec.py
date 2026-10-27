"""Fuentes primarias según el mercado: la SEC no cubre la Bolsa de Londres.

Prueba real 2026-10-27: para CGEO.L (LSE) el Cerebro decía «ingiere sus
fuentes primarias (SEC/FMP)», un consejo imposible, y «Todavia» sin tilde.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.chat_service import ChatService, files_with_sec, primary_sources_hint


def _co(ticker: str, exchange: str, cik: str | None = None) -> Company:
    return Company(
        ticker=ticker, name=ticker, exchange=exchange, currency="USD", cik=cik,
        sector="x", industry="x", company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )


@pytest.mark.parametrize(
    "ticker,exchange,cik,expected",
    [
        ("AAPL", "NASDAQ", None, True),
        ("UBER", "NYSE", "0001543151", True),
        ("BABA", "NYSE", "0001577552", True),  # extranjera que presenta 20-F: sí SEC
        ("CGEO.L", "LSE", None, False),
        ("SAN.MC", "BME", None, False),
        ("KRKNF", "OTC", None, False),  # canadiense en OTC, sin CIK
        ("CGEO.L", "NASDAQ", None, False),  # sufijo extranjero manda aunque la bolsa venga mal
    ],
)
def test_files_with_sec(ticker, exchange, cik, expected):
    assert files_with_sec(_co(ticker, exchange, cik)) is expected


def test_pista_sin_sec_para_lse():
    hint = primary_sources_hint(_co("CGEO.L", "LSE"))
    assert "SEC no cubre LSE" in hint
    assert "SEC/FMP" not in hint
    assert "SEC/FMP" in primary_sources_hint(_co("AAPL", "NASDAQ"))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def test_cerebro_no_manda_a_la_sec_un_valor_de_londres(db):
    db.add(_co("CGEO.L", "LSE"))
    db.commit()
    response = ChatService()._deterministic_answer(db, "¿Qué tal CGEO.L?", "company", "CGEO.L")
    assert "Todavía no tengo hechos financieros fiables almacenados para CGEO.L" in response.answer
    assert "SEC/FMP" not in response.answer
    assert "la SEC no cubre LSE" in response.answer
    assert not any("SEC/FMP" in action for action in response.proposed_actions)
    assert any("informes de CGEO.L" in action for action in response.proposed_actions)
