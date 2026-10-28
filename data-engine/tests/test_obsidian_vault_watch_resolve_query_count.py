"""/obsidian/vault.zip: simbolos de watchlist sin match exacto se resuelven en lote.

Cada simbolo que no casaba exacto (sufijo de mercado, clase de accion o sin
empresa en el universo) caia a ``resolve_company``: 2+ queries por simbolo.
Ahora esos simbolos van por ``resolve_companies`` (1-2 IN).
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.obsidian import export_obsidian_vault
from app.models.entities import Base, Company, WatchItem


def _run(n: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Company(ticker="SAN", name="Santander", exchange="BME", currency="EUR", sector="Fin",
                   industry="Banks", company_type="holding", valuation_model="unassigned",
                   special_sources=[], special_risks=[], factor_tags=[]))
    db.add(WatchItem(symbol="san.mc", company="Santander"))
    for i in range(n):
        db.add(WatchItem(symbol=f"NOCO{i:03d}", company=f"NOCO{i}"))
    db.commit()
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    response = export_obsidian_vault(db=db)
    db.close()
    return len(statements), response


def test_vault_queries_do_not_scale_with_unresolved_watch_symbols():
    few, _ = _run(3)
    many, response = _run(30)
    assert many == few, (few, many)
    assert response.status_code == 200
