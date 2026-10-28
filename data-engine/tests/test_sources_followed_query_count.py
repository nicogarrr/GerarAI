"""/sources/documents y /count: el universo seguido no lanza queries por simbolo.

``_followed_company_ids`` llamaba a ``resolve_company`` una vez por cada
simbolo de la watchlist (2 queries por simbolo aunque no hubiera documentos):
con 30 simbolos, 63 sentencias por peticion, y la UI pide listado y recuento.
Ahora se resuelven todos con ``resolve_companies`` (1-2 IN). El resultado es el
mismo, incluido el alias con sufijo de mercado (SAN.MC -> SAN).
"""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.api.routes.sources import documents_count
from app.models.entities import Base, Company, WatchItem


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _db(n: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    for i in range(n):
        _company(session, f"W{i:03d}")
        session.add(WatchItem(symbol=f"W{i:03d}", company=f"W{i}"))
    _company(session, "SAN")
    session.add(WatchItem(symbol="san.mc", company="Santander"))
    session.commit()
    return engine, session


def _count_statements(n: int) -> int:
    engine, session = _db(n)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    assert documents_count(db=session) == {"total": 0}
    session.close()
    return len(statements)


def test_followed_scope_queries_do_not_scale_with_watchlist():
    few = _count_statements(3)
    many = _count_statements(30)
    assert many == few, (few, many)


def test_followed_scope_keeps_market_suffix_alias():
    from app.api.routes.sources import _followed_company_ids

    _, session = _db(2)
    ids = set(session.scalars(select(_followed_company_ids(session).subquery())).all())
    san = session.scalar(select(Company.id).where(Company.ticker == "SAN"))
    assert san in ids
    assert len(ids) == 3
    session.close()


@pytest.mark.parametrize("n", [0])
def test_followed_scope_empty_watchlist(n):
    _, session = _db(n)
    assert documents_count(db=session) == {"total": 0}
    session.close()
