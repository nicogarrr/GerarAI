"""Deduplicación de noticias en lote (NewsDedupBatch): mismo resultado que las
consultas sueltas por noticia (url exacta y top-50 por «host/path»)."""

import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent
from app.services.news_identity import equivalent_news_event, prefetch_news_dedup
from app.services.news_service import NewsService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="DDUP", name="Dedup Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


_HOSTS = ["news.example.com", "NEWS.Example.com", "www.reuters.com", "a_b.example.org"]
_PATHS = ["", "/", "/deal", "/deal/", "/Deal", "/deal%20today", "/deal_x", "/a_b", "/a/b", "/deal/x?q=1"]


def _random_url(rng: random.Random) -> str:
    scheme = rng.choice(["https", "http", "HTTPS", "ftp"])
    suffix = rng.choice(["", "?utm=x", "#frag", "/more", str(rng.randint(0, 3))])
    return f"{scheme}://{rng.choice(_HOSTS)}{rng.choice(_PATHS)}{suffix}"


def _seed(db: Session, rng: random.Random, n: int) -> Company:
    company = _company(db)
    for i in range(n):
        url = _random_url(rng) if rng.random() > 0.05 else None
        tenant = 1 if rng.random() > 0.2 else 2
        _add(db, NewsEvent(company_id=company.id, title=f"t{i}", source="rss", url=url,
                           summary=""), tenant)
    db.commit()
    return company


def _add(db: Session, event: NewsEvent, tenant: int) -> None:
    # Filas de otro tenant: se escriben con su contexto y se vuelve al tenant 1.
    db.info["tenant_id"] = tenant
    event.tenant_id = tenant
    db.add(event)
    db.flush()
    db.info["tenant_id"] = 1


def test_equivalent_news_event_en_lote_igual_que_suelto(db):
    rng = random.Random(7)
    company = _seed(db, rng, 400)  # muchos más de 50 candidatos por patrón
    probes = [_random_url(rng) for _ in range(150)] + [None, "", "no-url", "https://"]
    batch = prefetch_news_dedup(db, probes, pattern_urls=probes)
    for url in probes:
        single = equivalent_news_event(db, company_id=company.id, url=url, title=None)
        batched = equivalent_news_event(db, company_id=company.id, url=url, title=None, batch=batch)
        assert (single.id if single else None) == (batched.id if batched else None), url


def test_filas_insertadas_durante_la_tanda_cuentan(db):
    rng = random.Random(11)
    company = _seed(db, rng, 120)
    probes = [_random_url(rng) for _ in range(60)]
    batch = prefetch_news_dedup(db, probes, pattern_urls=probes)
    service = NewsService()
    for i, url in enumerate(probes):
        # Igual que la ingesta: cada noticia nueva se guarda antes de la siguiente.
        if i % 3 == 0:
            db.add(NewsEvent(company_id=company.id, title=f"n{i}", source="rss", url=url,
                             summary="", tenant_id=1))
            db.flush()
        for title_is_identity in (True, False):
            single = service._is_duplicate(db, company, f"x{i}", url,
                                           title_is_identity=title_is_identity)
            batched = service._is_duplicate(db, company, f"x{i}", url,
                                            title_is_identity=title_is_identity,
                                            dedup_batch=batch)
            assert single == batched, url
        single_eq = equivalent_news_event(db, company_id=None, url=url, title=None)
        batched_eq = equivalent_news_event(db, company_id=None, url=url, title=None, batch=batch)
        assert (single_eq.id if single_eq else None) == (batched_eq.id if batched_eq else None)


def test_url_exacta_respeta_tenant(db):
    company = _company(db)
    _add(db, NewsEvent(company_id=company.id, title="otro", source="rss",
                       url="https://x.example.com/solo-t2", summary=""), 2)
    db.commit()
    url = "https://x.example.com/solo-t2"
    batch = prefetch_news_dedup(db, [url])
    assert url not in batch.known_urls
    service = NewsService()
    assert service._is_duplicate(db, company, "z", url, title_is_identity=False) is False
    assert service._is_duplicate(db, company, "z", url, title_is_identity=False,
                                 dedup_batch=batch) is False


def test_patron_no_precargado_usa_la_consulta_suelta(db):
    company = _company(db)
    real = NewsEvent(company_id=company.id, title="r", source="rss",
                     url="https://y.example.com/p?a=1", summary="", tenant_id=1)
    db.add(real)
    db.commit()
    batch = prefetch_news_dedup(db, [])  # sin patrones
    found = equivalent_news_event(db, company_id=None, url="https://y.example.com/p",
                                  title=None, batch=batch)
    assert found is not None and found.id == real.id
