"""«¿Cuántos dividendos he cobrado en 2025?» respondía con el año en curso.

La rama de cartera de _dividend_answer filtraba siempre por el año de hoy
(«No hay dividendos guardados de tus posiciones para 2026») aunque la
pregunta nombrara 2025 o «el año pasado».
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
    company = Company(
        ticker="KO", name="Coca-Cola", currency="USD", exchange="NYSE",
        company_type="operating", valuation_model="unassigned",
    )
    session.add(company)
    session.flush()
    session.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal("10"),
                         average_cost=Decimal("50"), currency="USD"))
    for ex_date, amount in ((date(2025, 3, 14), "0.485"), (date(2025, 6, 13), "0.485"), (date(2026, 3, 13), "0.51")):
        session.add(DividendRecord(company_id=company.id, tenant_id=1, ex_date=ex_date,
                                   amount=Decimal(amount), currency="USD", source="fmp"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.mark.parametrize("question", [
    "¿Cuántos dividendos he cobrado en 2025?",
    "¿Qué dividendos cobró mi cartera el año pasado?",
])
def test_la_cartera_usa_el_anio_de_la_pregunta(db, question):
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(db, question, 1)
    assert response is not None
    assert "en 2025" in response.answer
    assert "2 pago(s) en 2025" in response.answer
    assert "2026" not in response.answer


def test_sin_anio_sigue_el_anio_en_curso(db):
    from app.services.brain_data_tools import _dividend_answer

    response = _dividend_answer(db, "¿Qué dividendos cobrará mi cartera este año?", 1)
    assert response is not None
    assert "1 pago(s) en 2026" in response.answer
