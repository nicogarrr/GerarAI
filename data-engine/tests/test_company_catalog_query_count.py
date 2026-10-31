"""El catalogo de empresas se lee UNA vez por sesion de chat.

Un mensaje al Cerebro puede recorrer varios detectores de empresa por
texto (ticker, nombre, ambiguedad, contexto); cada uno cargaba la tabla
companies entera (~2.100 filas). Con el catalogo por sesion la tabla se
lee una sola vez por peticion.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.brain_data_tools import _company_in_question
from app.services.chat_service import ChatService


def _session(company_count: int = 30):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    for i in range(company_count):
        db.add(Company(
            ticker=f"Q{i:03d}", name="Zerium SA" if i == 7 else f"Xaa{i:03d} Inc", currency="USD",
            exchange="NASDAQ", company_type="operating", valuation_model="unassigned",
        ))
    db.commit()
    return db, engine


def test_company_lookups_share_one_catalog_read_per_session():
    db, engine = _session()
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM companies" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        assert _company_in_question(db, "¿Qué tal va Q005?") is not None
        assert ChatService()._company_by_name(db, "mis acciones de Zerium") is not None
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert len(statements) == 1, f"{len(statements)} lecturas de companies en una sesion"
