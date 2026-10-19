"""Portada /api/news: agrupación de la misma historia entre medios."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant
from app.services.news_headline_translation import fingerprint

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def _company(ticker: str, name: str) -> Company:
    return Company(
        ticker=ticker,
        name=name,
        exchange="NASDAQ",
        currency="USD",
        company_type="holding",
        valuation_model="unassigned",
    )


def _event(company_id, title, url, source="rss", **kw):
    return NewsEvent(
        tenant_id=1,
        company_id=company_id,
        title=title,
        source=source,
        url=url,
        date=kw.pop("date", NOW),
        metadata_=kw.pop("metadata_", {"connector": "rss", "date_source": "source"}),
        **kw,
    )


def _client(events_by_company):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    db = factory()
    db.add(Tenant(id=1, external_id="t"))
    companies = {}
    for ticker, name, events in events_by_company:
        company = _company(ticker, name)
        db.add(company)
        db.flush()
        companies[ticker] = company
        for event in events:
            event.company_id = company.id
            db.add(event)
    db.commit()

    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_misma_historia_reescrita_se_agrupa_con_cobertura():
    """JPMorgan Coin en dos medios con titulares reescritos -> una sola fila."""
    events = [
        ("JPM", "JPMorgan Chase & Co", [
            _event(None, "JPMorgan brings deposit token JPM Coin to Ethereum for institutional clients",
                   "https://tradingview.example/1", source="TradingView",
                   date=NOW - timedelta(hours=3)),
            _event(None, "JPMorgan Expands Institutional Deposit Token JPM Coin to Ethereum Network",
                   "https://bloomingbit.example/1", source="bloomingbit", date=NOW),
        ]),
    ]
    body = _client(events).get("/api/news").json()
    assert len(body) == 1
    row = body[0]
    # Representante: la más reciente (bloomingbit, fecha NOW).
    assert row["title"] == "JPMorgan Expands Institutional Deposit Token JPM Coin to Ethereum Network"
    assert row["coverage_count"] == 2
    assert row["coverage"] == [
        {
            "source": "TradingView",
            "url": "https://tradingview.example/1",
            "title": "JPMorgan brings deposit token JPM Coin to Ethereum for institutional clients",
        }
    ]


def test_historias_distintas_de_la_misma_empresa_no_se_agrupan():
    events = [
        ("META", "Meta Platforms Inc", [
            _event(None, "Meta Faces Fresh Privacy Scrutiny Over AI Smart Glasses",
                   "https://a.example/1", date=NOW),
            _event(None, "Meta announces new data center in Louisiana",
                   "https://a.example/2", date=NOW - timedelta(hours=2)),
        ]),
    ]
    body = _client(events).get("/api/news").json()
    assert len(body) == 2
    assert all(row["coverage_count"] is None for row in body)


def test_cross_idioma_se_agrupa_con_traduccion_cacheada():
    """Titular EN con traducción ES cacheada se agrupa con la versión ES."""
    en_title = "SpaceX Gets a Buy rating from Bernstein"
    metadata_en = {
        "connector": "rss",
        "date_source": "source",
        "headline_translation": {
            "status": "translated",
            "text": "SpaceX recibe una recomendación de compra de Bernstein",
            "fingerprint": fingerprint(en_title),
        },
    }
    events = [
        ("SPCX", "Space Exploration Technologies", [
            _event(None, "SpaceX recibe recomendación de compra de Bernstein",
                   "https://ms.example/es", source="MarketScreener",
                   date=NOW - timedelta(hours=1)),
            _event(None, en_title, "https://ms.example/en", source="MarketScreener EN",
                   date=NOW, metadata_=metadata_en),
        ]),
    ]
    body = _client(events).get("/api/news").json()
    assert len(body) == 1
    assert body[0]["coverage_count"] == 2


def test_titular_literal_corto_sigue_dedupeado():
    """Titulares de dos palabras idénticos: dedupe literal aunque la firma sea corta."""
    events = [
        ("ACME", "Acme Corp", [
            _event(None, "Acme beats", "https://pub.example/1", date=NOW - timedelta(hours=1)),
            _event(None, "Acme beats", "https://pub.example/2", date=NOW),
        ]),
    ]
    body = _client(events).get("/api/news").json()
    assert len(body) == 1
    assert body[0]["coverage_count"] == 2


def test_ventana_48h_no_agrupa_reescrituras_separadas_en_el_tiempo():
    """Misma historia reescrita fuera de la ventana de 48 h: no se agrupa."""
    events = [
        ("ACME", "Acme Corp", [
            _event(None, "Acme launches fusion reactor prototype in Nevada desert",
                   "https://pub.example/1", date=NOW - timedelta(days=6)),
            _event(None, "Acme unveils fusion reactor prototype at Nevada site",
                   "https://pub.example/2", date=NOW),
        ]),
    ]
    body = _client(events).get("/api/news").json()
    assert len(body) == 2


def test_ficha_empresa_no_agrupa():
    """En la ficha (?ticker=) se conserva todo lo de la empresa, sin agrupar."""
    events = [
        ("JPM", "JPMorgan Chase & Co", [
            _event(None, "JPMorgan brings deposit token JPM Coin to Ethereum for institutional clients",
                   "https://tradingview.example/1", source="TradingView",
                   date=NOW - timedelta(hours=3)),
            _event(None, "JPMorgan Expands Institutional Deposit Token JPM Coin to Ethereum Network",
                   "https://bloomingbit.example/1", source="bloomingbit", date=NOW),
        ]),
    ]
    body = _client(events).get("/api/news?ticker=JPM").json()
    assert len(body) == 2
    assert all(row["coverage_count"] is None for row in body)
