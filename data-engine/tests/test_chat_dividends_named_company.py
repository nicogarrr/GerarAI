"""«¿Cuántos dividendos he cobrado de MSFT?» listaba toda la cartera.

La rama de cartera de _dividend_answer (activada por «cobr…», «mis
dividendos»…) ignoraba la empresa nombrada en la pregunta y sumaba todas las
posiciones abiertas.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, Position

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def db(monkeypatch):
    import app.core.local_date as local_date

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    companies = {}
    for ticker, name in (("KO", "Coca-Cola"), ("MSFT", "Microsoft"), ("PEP", "PepsiCo")):
        company = Company(ticker=ticker, name=name, currency="USD", exchange="NYSE",
                          company_type="operating", valuation_model="unassigned")
        session.add(company)
        session.flush()
        companies[ticker] = company
    for ticker, qty in (("KO", "10"), ("MSFT", "4")):
        session.add(Position(tenant_id=1, company_id=companies[ticker].id, quantity=Decimal(qty),
                             average_cost=Decimal("50"), currency="USD"))
    for ticker, amount in (("KO", "0.51"), ("MSFT", "0.83"), ("PEP", "1.35")):
        session.add(DividendRecord(company_id=companies[ticker].id, tenant_id=1, ex_date=date(2026, 3, 13),
                                   amount=Decimal(amount), currency="USD", source="fmp"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.mark.parametrize("question", [
    "¿Cuántos dividendos he cobrado de MSFT?",
    "¿Cuánto he cobrado de dividendos de Microsoft este año?",
])
def test_la_cartera_se_limita_a_la_empresa_nombrada(db, question):
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(db, question, 1)
    assert response is not None
    assert "MSFT: 1 pago(s) en 2026" in response.answer
    assert "KO" not in response.answer
    assert "3,32" in response.answer or "3.32" in response.answer


def test_empresa_nombrada_sin_posicion_no_lista_la_cartera(db):
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(db, "¿Cuántos dividendos he cobrado de PEP?", 1)
    assert response is not None
    assert "No tienes PEP" in response.answer
    assert "KO" not in response.answer and "MSFT" not in response.answer


def test_sin_empresa_sigue_toda_la_cartera(db):
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(db, "¿Cuántos dividendos he cobrado este año?", 1)
    assert response is not None
    assert "KO: 1 pago(s)" in response.answer and "MSFT: 1 pago(s)" in response.answer
