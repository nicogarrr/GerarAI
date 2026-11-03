"""Pasada de 15 min de avisos de noticias: las noticias ya avisadas no cuestan
consultas por fila.

Antes, cada noticia ya avisada de la ventana de 48 h hacía tres consultas en
cada pasada (alerta previa por fingerprint, y dentro de queue_analysis el
evento y el análisis). Ahora la alerta previa y su análisis se leen en lote por
página; el resultado y la reparación del análisis perdido no cambian.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import AlertAnalysis, Base, Company, NewsEvent, Position, ResearchAlert, Tenant
from app.services.tracked_news_alerts import evaluate

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def _held_news(db, count: int, *, offset: int = 0) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.external_id == "batch"))
    if tenant is None:
        tenant = Tenant(external_id="batch", name="Batch", status="active", metadata_={})
        db.add(tenant)
        db.flush()
    for i in range(offset, offset + count):
        ticker = f"TK{i:02d}"
        company = Company(ticker=ticker, name=f"Zeta{i:02d}", exchange="NASDAQ", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add(Position(tenant_id=tenant.id, company_id=company.id, quantity=Decimal("1")))
        title = f"{ticker} files new contract"
        db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id, title=title, source="publisher.example",
                         url=f"https://publisher.example/{ticker}", date=NOW - timedelta(hours=2),
                         metadata_={"date_source": "source", "connector": "rss", "source_headline": title}))
    db.commit()
    db.info["tenant_id"] = tenant.id
    return tenant


def _count_statements(db, fn):
    seen: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        seen.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        result = fn()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    return result, seen


def test_already_alerted_news_cost_constant_queries(db):
    _held_news(db, 5)
    assert evaluate(db, now=NOW)["created"] == 5
    small, small_sql = _count_statements(db, lambda: evaluate(db, now=NOW))
    assert small["duplicates"] == 5 and small["created"] == 0

    _held_news(db, 15, offset=5)
    assert evaluate(db, now=NOW)["created"] == 15
    big, big_sql = _count_statements(db, lambda: evaluate(db, now=NOW))
    assert big["duplicates"] == 20 and big["created"] == 0
    # 4x más noticias ya avisadas, mismas consultas (antes 3 por noticia).
    assert len(big_sql) == len(small_sql)
    assert not [s for s in big_sql if "FROM news_events" in s and "news_events.id =" in s]


def test_prior_alert_without_analysis_is_still_repaired(db):
    _held_news(db, 3)
    assert evaluate(db, now=NOW)["created"] == 3
    alerts = db.scalars(select(ResearchAlert).order_by(ResearchAlert.id)).all()
    assert len(db.scalars(select(AlertAnalysis)).all()) == 3
    db.execute(delete(AlertAnalysis).where(AlertAnalysis.alert_id == alerts[1].id))
    db.commit()

    result = evaluate(db, now=NOW)

    assert result["duplicates"] == 3 and result["created"] == 0
    repaired = db.scalars(select(AlertAnalysis).where(AlertAnalysis.alert_id == alerts[1].id)).all()
    assert len(repaired) == 1
    assert len(db.scalars(select(AlertAnalysis)).all()) == 3


def test_same_url_twice_in_one_page_alerts_once(db):
    tenant = _held_news(db, 1)
    company = db.scalar(select(Company).where(Company.ticker == "TK00"))
    title = "TK00 files new contract again"
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id, title=title, source="publisher.example",
                     url="https://publisher.example/TK00", date=NOW - timedelta(hours=1),
                     metadata_={"date_source": "source", "connector": "rss", "source_headline": title}))
    db.commit()

    result = evaluate(db, now=NOW)

    assert result["created"] == 1 and result["duplicates"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 1
