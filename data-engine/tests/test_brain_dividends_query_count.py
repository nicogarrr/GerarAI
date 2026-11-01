"""N+1 en la respuesta de chat «dividendos de mi cartera»: lote por tenant.

La rama de cartera de _dividend_answer hacia una consulta de
DividendRecord por posicion; con la cartera real (19 posiciones) cada
pregunta al Cerebro costaba ~20 consultas. Ahora sale una consulta para
todas las empresas y se agrupa en memoria; la respuesta no cambia.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, Position
from app.services.brain_data_tools import _dividend_answer


def _session(position_count: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    today = date.today()
    for i in range(position_count):
        company = Company(
            ticker=f"D{i:02d}", name=f"D{i:02d} Inc", currency="USD", exchange="NASDAQ",
            company_type="operating", valuation_model="unassigned",
        )
        db.add(company)
        db.flush()
        db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal("10"),
                        average_cost=Decimal("90"), currency="USD"))
        for days in (60, 240):
            db.add(DividendRecord(
                company_id=company.id, tenant_id=1, ex_date=today - timedelta(days=days),
                amount=Decimal("0.50"), currency="USD", source="fmp",
            ))
    db.commit()
    return db, engine


def test_portfolio_dividend_answer_queries_are_constant_in_position_count():
    db, engine = _session(position_count=12)
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        response = _dividend_answer(db, "¿Qué dividendos cobrará mi cartera este año?", 1)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert response is not None
    assert "Total:" in response.answer
    # posiciones+empresas (1) + lote de dividendos (1): nunca 1 por posicion.
    assert len(statements) <= 3, f"{len(statements)} sentencias para 12 posiciones"
