"""Invalidacion del catalogo por sesion: escrituras de Company y ciclo de
vida de la transaccion.

El cache no puede sobrevivir a un Session.close() si el objeto Session se
reutiliza (db.info no se limpia), ni servir un catalogo sin las empresas
insertadas/actualizadas/borradas en la propia sesion.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.company_catalog import all_companies


def _company(ticker: str, name: str) -> Company:
    return Company(
        ticker=ticker, name=name, currency="USD", exchange="NASDAQ",
        company_type="operating", valuation_model="unassigned",
    )


def _engine(company_count: int = 5):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for i in range(company_count):
        db.add(_company(f"Q{i:03d}", f"Xaa{i:03d} Inc"))
    db.commit()
    db.close()
    return engine


def test_catalog_cache_does_not_survive_session_close_and_reuse():
    """close() + reutilizacion del MISMO objeto Session: el catalogo se relee
    y refleja escrituras de otras sesiones hechas mientras estaba cerrada."""
    engine = _engine()
    db = Session(engine)
    db.info["tenant_id"] = 1
    first = all_companies(db)
    assert len(first) == 5
    db.close()

    other = Session(engine)
    other.add(_company("NEW1", "Nueva Corp"))
    other.commit()
    other.close()

    second = all_companies(db)
    assert "NEW1" in {c.ticker for c in second}, "catalogo obsoleto tras close+reuse"


def test_catalog_invalidated_by_company_insert_in_same_session():
    engine = _engine()
    db = Session(engine)
    db.info["tenant_id"] = 1
    all_companies(db)
    db.add(_company("INS9", "Insertada SA"))
    db.flush()
    assert "INS9" in {c.ticker for c in all_companies(db)}


def test_catalog_invalidated_by_company_update_in_same_session():
    engine = _engine()
    db = Session(engine)
    db.info["tenant_id"] = 1
    companies = all_companies(db)
    companies[0].name = "Renombrada SA"
    db.flush()
    assert any(c.name == "Renombrada SA" for c in all_companies(db))


def test_catalog_still_cached_within_one_transaction():
    """La propiedad de rendimiento se mantiene: una lectura por transaccion."""
    from sqlalchemy import event

    engine = _engine()
    db = Session(engine)
    db.info["tenant_id"] = 1
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM companies" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        all_companies(db)
        all_companies(db)
        all_companies(db)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert len(statements) == 1, f"{len(statements)} lecturas de companies en una transaccion"


def test_catalog_sees_pending_company_without_manual_flush():
    """Un add() sin flush es visible en la siguiente lectura: la consulta
    original forzaba autoflush y el cache no puede cortocircuitar antes."""
    engine = _engine()
    db = Session(engine)
    db.info["tenant_id"] = 1
    all_companies(db)
    db.add(_company("WAIT", "Pendiente SA"))
    assert "WAIT" in {c.ticker for c in all_companies(db)}
