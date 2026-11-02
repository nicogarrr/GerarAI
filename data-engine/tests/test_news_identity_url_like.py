"""equivalent_news_event: el «%»/«_» de una URL no hace de comodín y el host
casa sin importar mayúsculas (Postgres distingue mayúsculas en LIKE)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent
from app.services.news_identity import equivalent_news_event


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="WILD", name="Wildcard Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _event(db: Session, company: Company, title: str, url: str) -> NewsEvent:
    event = NewsEvent(company_id=company.id, title=title, source="rss", url=url, summary="")
    db.add(event)
    db.commit()
    return event


def test_porcentaje_de_la_url_no_hace_de_comodin(db):
    company = _company(db)
    # 60 noticias que solo casan si «%20» actúa como comodín («%» = cualquier cosa).
    for i in range(60):
        _event(db, company, f"Decoy {i}", f"https://news.example.com/deal{i}x20today")
    real = _event(db, company, "Real deal", "https://news.example.com/deal%20today")
    found = equivalent_news_event(
        db, company_id=None, url="https://news.example.com/deal%20today?utm=x", title=None
    )
    assert found is not None and found.id == real.id


def test_guion_bajo_de_la_url_no_hace_de_comodin(db):
    company = _company(db)
    for i in range(60):
        _event(db, company, f"Decoy {i}", f"https://news.example.com/a{i % 10}b/{i}")
    real = _event(db, company, "Real", "https://news.example.com/a_b")
    found = equivalent_news_event(db, company_id=None, url="https://news.example.com/a_b", title=None)
    assert found is not None and found.id == real.id


def test_host_en_mayusculas_casa(db):
    company = _company(db)
    real = _event(db, company, "Upper host", "https://WWW.Reuters.COM/markets/story-1")
    found = equivalent_news_event(
        db, company_id=None, url="https://www.reuters.com/markets/story-1/", title=None
    )
    assert found is not None and found.id == real.id
