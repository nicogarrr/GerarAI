"""Chat: los tickers conocidos salen del catalogo en cache de la transaccion.

`_mentions_unknown_ticker` ya lee el catalogo completo (companies_named_in) y
despues hacia OTRO scan entero de companies solo para la lista de tickers:
dos full-table por mensaje de chat. Con el catalogo en cache de transaccion
(company_catalog), la segunda lectura sobra.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.core.database  # noqa: F401 - registra los listeners de tenant
from app.models.entities import Base, Company, Tenant
from app.services.company_catalog import all_companies


@pytest.fixture
def db_counter():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.flush()
        for i, ticker in enumerate(("ACME", "BN", "FER")):
            session.add(Company(
                ticker=ticker, name=f"Comp {ticker}", exchange="NASDAQ", currency="USD",
                sector="Tech", industry="Tech", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
            ))
        session.commit()
        yield session, counter
    engine.dispose()


def test_unknown_ticker_check_reuses_the_transaction_catalog(db_counter):
    from app.services.chat_service import ChatService

    db, counter = db_counter
    all_companies(db)  # el propio detector de nombres ya la leyo en esta tx
    counter["n"] = 0

    service = ChatService()
    assert service._mentions_unknown_ticker(db, "¿Está barata ZZZZ?", None) is True
    assert service._mentions_unknown_ticker(db, "¿Está barata ACME?", None) is False
    # Ni una query mas: tickers y nombres salen del catalogo en cache.
    assert counter["n"] == 0, f"deteccion de ticker uso {counter['n']} queries (!=0)"
