"""N+1 en build_digest: empresas, precios y noticias se cargan en lote.

El digest diario no puede costar 3+ consultas por posicion; el numero de
sentencias queda acotado con cualquier numero de posiciones. El contenido
del digest (items, orden, cobertura) no cambia.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    MarketPrice,
    NewsEvent,
    Portfolio,
    Position,
    Tenant,
)
from app.services.portfolio_moves_service import build_digest


def _session(position_count: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id="t1", name="T1", metadata_={}, status="active")
    db.add(tenant)
    db.flush()
    portfolio = Portfolio(tenant_id=tenant.id, name="A")
    db.add(portfolio)
    db.flush()
    for i in range(position_count):
        company = Company(
            ticker=f"T{i:02d}", name=f"Co {i}", exchange="NASDAQ", currency="USD",
            company_type="holding", valuation_model="unassigned",
        )
        db.add(company)
        db.flush()
        db.add(Position(tenant_id=tenant.id, portfolio_id=portfolio.id, company_id=company.id,
                        quantity=Decimal("2"), average_cost=Decimal("10")))
        db.add_all((
            MarketPrice(company_id=company.id, date=date(2026, 9, 23),
                        close=Decimal("10"), adj_close=Decimal("10"), source="yfinance"),
            MarketPrice(company_id=company.id, date=date(2026, 9, 24),
                        close=Decimal("11"), adj_close=Decimal("11"), source="yfinance"),
        ))
        db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                         date=datetime(2026, 9, 24, 8, tzinfo=UTC),
                         title=f"Article {i}", source="example.com",
                         url=f"https://example.com/{i}", metadata_={"connector": "gdelt"}))
    db.commit()
    db.info["tenant_id"] = tenant.id
    return db, engine


def test_build_digest_queries_are_constant_in_position_count():
    db, engine = _session(position_count=10)
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        digest = build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC))
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert len(digest.items) == 10
    assert all(item["status"] == "disponible" for item in digest.items)
    assert all(len(item["related_news"]) == 1 for item in digest.items)
    # posiciones + empresas + precios + noticias + digest previo + insert = 6;
    # nunca 3+ por posicion (>=31 con 10 posiciones).
    assert len(statements) <= 8, f"{len(statements)} sentencias para 10 posiciones"
