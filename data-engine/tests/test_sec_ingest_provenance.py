"""Procedencia SEC end-to-end: SECClient -> ingest -> NewsEvent.

La SEC no publica un titular para un filing; el conector genera texto de
display en español («8-K presentado ante la SEC»). Ese texto NO es el
titular original de la fuente y NO debe persistirse como
metadata.source_headline (promesa de verbatim de la fuente, consumida por
las alertas de #574). El display vive en NewsEvent.title; source_headline
queda ausente. Un item con titular real (p.ej. RSS) sí lo conserva.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, NewsEvent, Tenant
from app.schemas import NewsFeedItem
from app.services.async_bridge import run_from_any_context as run_async
from app.services.connectors.sec import SECClient
from app.services.feed_ingestion_service import FeedIngestionService
from app.services.news_service import NewsService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        tenant = Tenant(external_id="t", name="T", metadata_={}, status="active")
        session.add(tenant)
        session.flush()
        session.add(Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
                            company_type="holding", valuation_model="unassigned"))
        session.commit()
        session.info["tenant_id"] = tenant.id
        yield session
    engine.dispose()


def _sec_payload() -> dict:
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000123"],
                "form": ["8-K"],
                "filingDate": ["2026-09-24"],
                "reportDate": ["2026-09-20"],
                "primaryDocument": ["current-report.htm"],
            }
        }
    }


def _ingest_sec(db) -> None:
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_sec_payload(), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sec = SECClient(client=client, requests_per_second=10)
            return await sec.recent_filings("320193", ticker="AAPL")

    result = run_async(probe())
    FeedIngestionService().ingest_news_result(db, result)
    db.commit()


def test_display_title_sec_no_se_persiste_como_source_headline(db):
    _ingest_sec(db)
    events = db.scalars(select(NewsEvent)).all()
    assert len(events) == 1
    event = events[0]
    # El texto display generado por GerarAI vive en title (con el prefijo de
    # ticker de F175 que la UI ya oculta/usa en su columna propia)...
    assert event.title == "AAPL 8-K presentado ante la SEC"
    # ...y NUNCA en source_headline: no es el titular original de la fuente.
    assert "source_headline" not in (event.metadata_ or {})
    assert (event.metadata_ or {}).get("connector") == "sec"
    # El flag de procedencia se persiste: la UI omite el prefijo de ticker.
    assert (event.metadata_ or {}).get("headline_from_source") is False
    # Y se expone en /api/news (legacy sin flag -> True).
    from app.api.routes.news import news_events

    payload = news_events(db)
    assert payload[0]["headline_from_source"] is False


def test_titular_real_de_fuente_si_se_conserva(db):
    resp = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(title="Apple beats estimates", text=None, ticker="AAPL",
                      url="https://wire.example/aapl-1", source="rss",
                      published_at=datetime(2026, 9, 24, 8, tzinfo=UTC))],
        default_source="rss",
        connector="rss",
    )
    db.commit()
    assert resp.created == 1
    event = db.scalars(select(NewsEvent)).one()
    assert (event.metadata_ or {}).get("source_headline") == "Apple beats estimates"

def test_dos_filings_del_mismo_form_no_son_falsos_duplicados(db):
    """Dos 8-K distintos (distinto accession/URL) comparten el título
    canónico de display: la dedup NO puede casar por título sintético."""
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000123", "0000320193-26-000456"],
                "form": ["8-K", "8-K"],
                "filingDate": ["2026-09-24", "2026-09-18"],
                "reportDate": ["2026-09-20", "2026-09-15"],
                "primaryDocument": ["current-report.htm", "current-report.htm"],
            }
        }
    }

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sec = SECClient(client=client, requests_per_second=10)
            return await sec.recent_filings("320193", ticker="AAPL")

    result = run_async(probe())
    assert len(result.items) == 2
    out = FeedIngestionService().ingest_news_result(db, result)
    db.commit()
    assert out["created"] == 2, "el segundo 8-K no es un duplicado del primero"
    assert out["skipped_duplicates"] == 0
    events = db.scalars(select(NewsEvent)).all()
    assert len(events) == 2
    # Mismo título canónico (la UI distingue por fecha/URL), identidad por URL.
    assert {e.title for e in events} == {"AAPL 8-K presentado ante la SEC"}
    assert len({e.url for e in events}) == 2

    # Reingesta del MISMO payload: la URL sí es identidad -> duplicados.
    out2 = FeedIngestionService().ingest_news_result(db, result)
    db.commit()
    assert out2["created"] == 0
    assert out2["skipped_duplicates"] == 2
