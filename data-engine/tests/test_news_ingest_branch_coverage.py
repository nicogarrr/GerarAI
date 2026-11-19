"""Cobertura de ramas de ingest_news_items: filtros de fila, foto tracked
preexistente (tanda anidada en otra tanda) y helpers de titulares 13F."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, WatchItem
from app.schemas.api import NewsFeedItem
from app.services.materiality_service import POSITIONS_SNAPSHOT_KEY
from app.services.news_service import (
    _TRACKED_SNAPSHOT_KEY,
    NewsService,
    is_position_change_headline,
    position_change_cluster_title,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = 1
        session.add(Company(
            ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
            sector="S", industry="I", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        ))
        session.commit()
        yield session


def _items():
    return [
        NewsFeedItem(title="Apple headline 1", text="Apple body 1", url="https://e.com/1",
                     source="gdelt", ticker="AAPL"),
        # Captacion de despachos: se descarta antes de cualquier analisis.
        NewsFeedItem(title="Rosen Law Firm announces investigation of Apple", text="x",
                     url="https://e.com/law", source="gdelt", ticker="AAPL"),
    ]


def test_position_change_headline_helpers():
    assert is_position_change_headline("Renaissance raises stake in Apple")
    assert is_position_change_headline("Vanguard sells shares of Apple")
    assert is_position_change_headline("13F: shares purchased by Vanguard")
    assert not is_position_change_headline("Apple launches new iPhone")
    assert not is_position_change_headline("")
    assert not is_position_change_headline(None)
    assert position_change_cluster_title("AAPL", "gdelt", 7).startswith("7 movimientos")
    assert "AAPL" in position_change_cluster_title("AAPL", "gdelt", 7)
    assert " en " not in position_change_cluster_title(None, "gdelt", 3)


def test_ingest_skips_law_firm_rows(db):
    resp = NewsService().ingest_news_items(db, _items(), connector="gdelt", default_source="gdelt")
    assert resp.created == 1


def test_ingest_with_preexisting_snapshots_keeps_them(db):
    """Tanda anidada: las fotos ya estaban en db.info -> no se repueblan ni se retiran."""
    company = next(c for c in db.query(Company).all() if c.ticker == "AAPL")
    db.info[POSITIONS_SNAPSHOT_KEY] = []
    db.info[_TRACKED_SNAPSHOT_KEY] = ({company.id}, {"AAPL"})
    resp = NewsService().ingest_news_items(db, _items(), connector="gdelt", default_source="gdelt")
    assert resp.created == 1
    # Las fotos ajenas sobreviven a la tanda (no eran suyas).
    assert db.info[_TRACKED_SNAPSHOT_KEY] == ({company.id}, {"AAPL"})
    assert db.info[POSITIONS_SNAPSHOT_KEY] == []


def test_ingest_repopulates_own_snapshots_and_cleans_up(db):
    """Sin fotos previas: la tanda las crea (rama owns_*) y las retira al salir."""
    resp = NewsService().ingest_news_items(db, _items(), connector="gdelt", default_source="gdelt")
    assert resp.created == 1
    assert _TRACKED_SNAPSHOT_KEY not in db.info
    assert POSITIONS_SNAPSHOT_KEY not in db.info


def test_ingest_tracked_flag_from_snapshot_watch_symbol(db):
    """La foto por symbol de WatchItem marca tracked sin EXISTS por noticia."""
    db.add(WatchItem(symbol="AAPL"))
    db.flush()
    service = NewsService()
    resp = service.ingest_news_items(db, _items(), connector="gdelt", default_source="gdelt")
    assert resp.created == 1


def test_change_summary_variants():
    from app.services.news_service import _change_summary

    # Cuerpo que ya empieza por el titular: se devuelve tal cual.
    assert _change_summary("Apple cae", "Apple cae un 5% por el guidance") == "Apple cae un 5% por el guidance"
    # Sin cuerpo: prefijo + titular.
    assert _change_summary("Apple cae", "") == "Noticia material que requiere revisión de la tesis: Apple cae."
    # Cuerpo distinto: prefijo + titular + cuerpo.
    out = _change_summary("Apple cae", "El guidance decepciona")
    assert "Apple cae." in out and "guidance" in out


def test_ticker_candidates_cache_hit(db):
    """Segunda llamada con el mismo catalogo: sirve el preparado en db.info."""
    from app.services.news_service import _ticker_candidates

    first = _ticker_candidates(db)
    second = _ticker_candidates(db)
    assert first is second


def test_ingest_duplicate_url_counts_as_skipped(db):
    service = NewsService()
    service.ingest_news_items(db, _items(), connector="gdelt", default_source="gdelt")
    again = NewsFeedItem(title="Apple headline otro", text="Apple body otro",
                         url="https://e.com/1", source="gdelt", ticker="AAPL")
    resp = service.ingest_news_items(db, [again], connector="gdelt", default_source="gdelt")
    assert resp.created == 0 and resp.skipped_duplicates == 1
