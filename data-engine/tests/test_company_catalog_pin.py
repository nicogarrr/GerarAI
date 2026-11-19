"""Pin del catalogo de empresas por tanda de ingesta (regresion N+1).

_analyze_news commitea por item y el cache del catalogo es por transaccion:
una tanda de N noticias re-leia las ~2.100 filas de companies N veces y
reconstruia el matcher de alias por noticia (medido: 25 lecturas completas
y ~154 ms/item en SQLite con 2.100 empresas -> 1 lectura y ~15 ms/item).
El pin (pinned_catalog) la fija para la tanda; la tanda de ingesta no
escribe Company y un rollback retira el pin (los objetos quedan expirados
y servirlos dispararia un SELECT por fila).
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company
from app.services.company_catalog import _PIN_KEY, all_companies, pinned_catalog


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.add(_company("AAPL"))
        session.commit()
        yield session


def _full_reads(db):
    counter = {"n": 0}

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        s = statement.lower()
        if "from companies" in s and "where" not in s:
            counter["n"] += 1

    return counter


def test_pin_survives_commits(db):
    """Con pin: commits intermedios no fuerzan re-lectura del catalogo."""
    counter = _full_reads(db)
    with pinned_catalog(db):
        all_companies(db)
        db.commit()  # la tanda de ingesta commitea por item
        all_companies(db)
        db.commit()
        all_companies(db)
    assert counter["n"] == 1, f"catalogo re-leido bajo pin: {counter['n']} lecturas completas"


def test_pin_removed_after_block(db):
    """Sin pin, cada transaccion nueva re-lee (comportamiento de siempre)."""
    with pinned_catalog(db):
        pass
    assert _PIN_KEY not in db.info
    db.commit()  # cierra la transaccion del pin: la siguiente lectura es nueva
    counter = _full_reads(db)
    all_companies(db)
    db.commit()
    all_companies(db)
    assert counter["n"] == 2


def test_company_write_invalidates_pin(db):
    """Una escritura de Company en la propia sesion fuerza lectura fresca."""
    with pinned_catalog(db):
        all_companies(db)
        db.add(_company("MSFT"))
        db.flush()
        fresh = all_companies(db)
    assert any(c.ticker == "MSFT" for c in fresh), "el pin escondio una Company escrita en la sesion"


def test_pending_company_write_bypasses_pin(db):
    """Company aun sin flush: el SELECT autoflushea y la veria; el pin no."""
    with pinned_catalog(db) as pinned:
        db.add(_company("NVDA"))
        assert all_companies(db) is not pinned
        db.rollback()


def test_rollback_drops_pin(db):
    """Rollback: los objetos pineados expiran; el pin se retira solo."""
    with pinned_catalog(db):
        db.add(_company("MSFT"))
        db.rollback()
        assert _PIN_KEY not in db.info
        counter = _full_reads(db)
        rows = all_companies(db)
        assert counter["n"] == 1
        assert all(c.ticker != "MSFT" for c in rows)


def test_ingest_news_items_reads_catalog_once(db):
    """La tanda real: 3 noticias con commit por item -> 1 lectura completa."""
    from app.schemas.api import NewsFeedItem
    from app.services.news_service import NewsService

    db.info["tenant_id"] = 1
    items = [
        NewsFeedItem(title=f"AAPL headline {i}", text=f"AAPL body {i}",
                     url=f"https://e.com/{i}", source="gdelt", ticker="AAPL")
        for i in range(3)
    ]
    counter = _full_reads(db)
    NewsService().ingest_news_items(db, items, connector="gdelt", default_source="gdelt")
    assert counter["n"] == 1, f"N+1 del catalogo en ingesta: {counter['n']} lecturas completas"
    assert _PIN_KEY not in db.info
