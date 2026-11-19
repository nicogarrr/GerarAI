"""Presupuesto de consultas del dedup cruzado de tracked_news (regresion N+1).

Cada noticia candidata pagaba 1 SELECT de alertas-noticia de su compania
(tope 300) + 1 db.get por NewsEvent referenciado, en cada pasada de 15 min
sobre la ventana de 48 h. Las alertas-noticia de las companias de la pagina
se precargan ahora en UNA consulta (mismo tope y orden por compania, con
funcion ventana) y sus NewsEvent en otra, con referencias fuertes (el
identity map es debil y sin ellas el recolector soltaba la precarga).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    NewsEvent,
    ResearchAlert,
    WatchItem,
)

N_CANDIDATES = 30
N_PRIOR_ALERTS = 40


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def _seed(db):
    now = datetime.now(UTC)
    db.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="PAYER", name="Payer Industries", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="research_candidate",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    db.add(WatchItem(symbol="PAYER", company="Payer Industries"))
    for i in range(N_PRIOR_ALERTS):
        event = NewsEvent(
            tenant_id="tenant-test", company_id=company.id,
            date=now - timedelta(days=3, minutes=i), title=f"PAYER old filing {i}",
            source="rss", url=f"https://site.example/old{i}",
            metadata_={"connector": "rss", "date_source": "source",
                       "source_headline": f"PAYER old filing {i}"},
        )
        db.add(event)
        db.flush()
        db.add(ResearchAlert(
            tenant_id="tenant-test", company_id=company.id, alert_type="tracked_news",
            title=f"Old {i}", message="vieja", fingerprint=f"old-{i}", channels=["in_app"],
            created_at=now - timedelta(days=3), last_triggered_at=now - timedelta(days=3),
            metadata_={"news_event_id": event.id, "source_url": f"https://site.example/old{i}"},
        ))
    for i in range(N_CANDIDATES):
        db.add(NewsEvent(
            tenant_id="tenant-test", company_id=company.id,
            date=now - timedelta(hours=1, minutes=i),
            title=f"PAYER announces contract {i}",
            source="rss", url=f"https://site.example/new{i}",
            metadata_={"connector": "rss", "date_source": "source",
                       "source_headline": f"PAYER announces contract {i}"},
        ))
    db.commit()
    return company, now


def test_evaluate_statement_budget(db):
    from app.services.tracked_news_alerts import evaluate

    _, now = _seed(db)
    statements = 0

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        nonlocal statements
        statements += 1

    stats = evaluate(db, now=now)
    assert stats["examined"] == N_CANDIDATES
    assert stats["created"] == 1  # la primera; el cooldown frena las demas
    # ANTES: 1250. DESPUES: ~52 (precarga de la pagina + cooldown por
    # candidata superviviente + la escritura de la alerta creada).
    assert statements <= 120, f"N+1 de dedup cruzado: {statements} sentencias"


def test_prefetched_dedup_matches_same_news(db):
    """La precarga dedupa igual: misma URL ya avisada por otra via = duplicada."""
    from app.services.news_identity import equivalent_news_alert, prefetch_news_alert_dedup

    company, now = _seed(db)
    prefetched = prefetch_news_alert_dedup(db, [company.id], now)
    dup = equivalent_news_alert(
        db, company_id=company.id, url="https://site.example/old0",
        title="otro titular", now=now, _prefetched=prefetched,
    )
    assert dup is not None, "la URL ya avisada no dedupo con la precarga"
    # Y por titular (sin URL):
    dup_title = equivalent_news_alert(
        db, company_id=company.id, url=None, title="PAYER old filing 1",
        now=now, _prefetched=prefetched,
    )
    assert dup_title is not None, "el titular ya avisado no dedupo con la precarga"
    # Una compania no precargada cae a la consulta original:
    other = equivalent_news_alert(
        db, company_id=999999, url="https://site.example/old0", title=None, now=now,
        _prefetched=prefetched,
    )
    assert other is None


def test_prefetch_edge_cases(db):
    """Sin companias: vacio; alerta fuera de la ventana de 7 dias: no dedupa."""
    from app.services.news_identity import equivalent_news_alert, prefetch_news_alert_dedup

    assert prefetch_news_alert_dedup(db, [], None).by_company == {}
    company, now = _seed(db)
    old = db.query(ResearchAlert).filter_by(fingerprint="old-0").first()
    old.created_at = now - timedelta(days=30)  # fuera de _DEDUPE_WINDOW
    db.commit()
    prefetched = prefetch_news_alert_dedup(db, [company.id], now)
    assert equivalent_news_alert(
        db, company_id=company.id, url="https://site.example/old0",
        title=None, now=now, _prefetched=prefetched,
    ) is None, "una alerta fuera de la ventana no debe dedupar"


def test_prefetch_respects_per_company_cap(db):
    """El tope de 300 por compania de la consulta original se mantiene."""
    from app.services.news_identity import prefetch_news_alert_dedup

    company, now = _seed(db)
    for i in range(310):
        db.add(ResearchAlert(
            tenant_id="tenant-test", company_id=company.id, alert_type="tracked_news",
            title=f"Extra {i}", message="x", fingerprint=f"extra-{i}", channels=["in_app"],
            created_at=now - timedelta(days=2),
        ))
    db.commit()
    prefetched = prefetch_news_alert_dedup(db, [company.id], now)
    assert len(prefetched.by_company[company.id]) == 300
    ids = [alert.id for alert in prefetched.by_company[company.id]]
    assert ids == sorted(ids, reverse=True), "orden id desc de la consulta original roto"
