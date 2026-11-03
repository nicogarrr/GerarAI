"""Erratas en el nombre de una empresa tuya (prueba real 2026-11-03).

«micrsoft esta cara?» no se reconocía: respuesta genérica sin tus datos de
Microsoft. Ahora una errata pequeña en el nombre de una empresa que tienes o
sigues se resuelve, solo con pista de consulta de inversión.
"""

import pytest

from app.models.entities import Company, WatchItem
from app.services.chat_service import ChatService
from app.services.company_names import _osa_distance
from tests.test_chat_english_sale_tax import _session


@pytest.fixture
def db():
    session = _session("es")
    for ticker, name in (("MSFT", "Microsoft Corporation"), ("UBER", "Uber Technologies"),
                         ("ASTS", "AST SpaceMobile"), ("KO", "The Coca-Cola Company")):
        session.query(Company).filter_by(ticker=ticker).one().name = name
    session.add(Company(ticker="AMZN", name="Amazon.com Inc", exchange="NASDAQ", company_type="platform",
                        valuation_model="unassigned", currency="USD"))
    session.add(Company(ticker="NVDA", name="Nvidia Corporation", exchange="NASDAQ", company_type="platform",
                        valuation_model="unassigned", currency="USD"))
    session.add(WatchItem(tenant_id=1, symbol="NVDA"))
    session.commit()
    yield session
    session.close()


def _company(db, question):
    company = ChatService()._resolve_company(db, question, "portfolio", None)
    return company.ticker if company is not None else None


@pytest.mark.parametrize(("question", "ticker"), [
    ("micrsoft esta cara?", "MSFT"),
    ("Micrsoft está cara?", "MSFT"),
    ("¿Qué opinas de Mircosoft?", "MSFT"),
    ("¿qué tal va mi posición en microsfot?", "MSFT"),
    ("microsoft esta cara?", "MSFT"),
    ("¿nvidai está barata?", "NVDA"),  # en tu lista de seguimiento
    ("Microsoft esta cara?", "MSFT"),  # lo de siempre sigue igual
])
def test_typos_in_your_companies_are_resolved(db, question, ticker):
    assert _company(db, question) == ticker


@pytest.mark.parametrize("question", [
    "micrsoft",  # sin pista de consulta
    "¿Está cara Amazn?",  # no la tienes ni la sigues
    "¿Cómo va mi cartera?",
    "¿Qué opinas de comprar más acciones?",
    "ubre está cara?",  # palabra corta: no se adivina
])
def test_no_guessing_without_cue_or_outside_your_companies(db, question):
    assert _company(db, question) is None


def test_osa_distance():
    assert _osa_distance("micrsoft", "microsoft", 2) == 1
    assert _osa_distance("mircosoft", "microsoft", 2) == 1
    assert _osa_distance("cartera", "carters", 1) == 1
    assert _osa_distance("abcdefgh", "zzzzzzzz", 2) == 3
