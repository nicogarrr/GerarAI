"""Nombre ambiguo que solo encaja con UNA empresa tuya (benchmark Cerebro, 2026-11-08).

«¿Cuántas acciones tengo de Brookfield?» con BN en cartera contestaba «¿te
refieres a BN o a BAM?»: «Brookfield» casa con dos empresas del maestro. Si
solo una de ellas es tuya (posición o lista de seguimiento), el nombre se
refiere a esa; si son tuyas las dos, o ninguna, se sigue preguntando.
"""

import pytest

from app.models.entities import Company, WatchItem
from app.services.chat_service import ChatService
from tests.test_chat_english_sale_tax import _session


@pytest.fixture
def db():
    session = _session("es")
    for ticker, name in (("BN", "Brookfield Corporation"), ("BAM", "Brookfield Asset Management Ltd")):
        if session.query(Company).filter_by(ticker=ticker).one_or_none() is None:
            session.add(
                Company(
                    ticker=ticker,
                    name=name,
                    exchange="NYSE",
                    company_type="financial",
                    valuation_model="unassigned",
                    currency="USD",
                )
            )
        else:
            session.query(Company).filter_by(ticker=ticker).one().name = name
    session.commit()
    yield session
    session.close()


def _company(db, question):
    company = ChatService()._resolve_company(db, question, "portfolio", None)
    return company.ticker if company is not None else None


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuántas acciones tengo de Brookfield?",
        "¿Qué tal va Brookfield?",
    ],
)
def test_ambiguous_name_resolves_to_the_only_company_you_follow(db, question):
    db.add(WatchItem(tenant_id=1, symbol="BN"))
    db.commit()
    assert _company(db, question) == "BN"


def test_still_ambiguous_when_none_or_both_are_yours(db):
    assert _company(db, "¿Qué tal va Brookfield?") is None
    db.add_all([WatchItem(tenant_id=1, symbol="BN"), WatchItem(tenant_id=1, symbol="BAM")])
    db.commit()
    assert _company(db, "¿Qué tal va Brookfield?") is None
