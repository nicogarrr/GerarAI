"""Foto de posiciones por tanda de ingesta (regresion N+1 de materiality).

Cada noticia con empresa pagaba un select(Position) completo en
portfolio_weight: un barrido GDELT de N items nuevos costaba N lecturas
de toda la cartera. La tanda (ingest_news_items) la precarga una vez via
db.info[POSITIONS_SNAPSHOT_KEY]; fuera de tanda (noticia suelta por API)
se lee como siempre. La foto solo guarda datos LEIDOS: un rollback a
media tanda no deja fantasmas, y la clave se retira al terminar.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Portfolio, Position
from app.services.materiality_service import (
    POSITIONS_SNAPSHOT_KEY,
    MaterialityService,
)

N = 25


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def company(db):
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    portfolio = Portfolio(name="p")
    db.add(company)
    db.add(portfolio)
    db.commit()
    db.add(Position(
        portfolio_id=portfolio.id, company_id=company.id, quantity=Decimal("10"),
        average_cost=Decimal("150"), market_price=Decimal("200"),
        market_value=Decimal("2000"), unrealized_pnl=Decimal("500"),
        realized_pnl=Decimal("0"), as_of=date.today(), currency="USD",
    ))
    db.commit()
    return company


def _count_selects(db):
    engine = db.get_bind()
    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    return counter


def test_batch_assessments_read_positions_once(db, company):
    """N evaluaciones con la tanda activa: 1 lectura de Position, no N."""
    service = MaterialityService()
    db.info[POSITIONS_SNAPSHOT_KEY] = None  # lo hace ingest_news_items
    counter = _count_selects(db)
    weights = {
        service.assess_news(db, company, f"Apple earnings v{i}", "gdelt", f"https://e.com/{i}",
                            use_jev=False).portfolio_weight
        for i in range(N)
    }
    assert counter["n"] == 1, f"N+1 de portfolio_weight: {counter['n']} lecturas para {N} noticias"
    assert weights == {1.0}


def test_single_assessment_without_batch_reads_fresh(db, company):
    """Sin tanda (noticia suelta): cada evaluacion lee la cartera fresca."""
    service = MaterialityService()
    counter = _count_selects(db)
    service.assess_news(db, company, "Apple earnings", "gdelt", "https://e.com/1", use_jev=False)
    service.assess_news(db, company, "Apple guidance", "gdelt", "https://e.com/2", use_jev=False)
    assert counter["n"] == 2
    assert POSITIONS_SNAPSHOT_KEY not in db.info


def test_ingest_news_items_cleans_up_snapshot_key(db, company):
    """ingest_news_items retira la clave al terminar, tambien con lista vacia."""
    from app.services.news_service import NewsService

    NewsService().ingest_news_items(db, [], default_source="gdelt")
    assert POSITIONS_SNAPSHOT_KEY not in db.info
