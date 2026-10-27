"""F252: el mismo filing de archivo inmutable no se ingesta ni se lista dos
veces, y ningun otro documento se oculta por compartir URL o titulo.

SEC sirve el mismo filing con bytes que varian entre dias y el checksum no
lo capturaba, asi que cada re-ingesta creaba otra fila (ASML 34/17, AAPL
40/20, /research/sources 50/26). La identidad por URL solo se aplica a URLs
de archivo inmutable (SEC Archives); ante cualquier otra ambiguedad la vista
no oculta nada.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.sources import documents, documents_count
from app.models.entities import Base, Company, Document
from app.services.company_events_service import CompanyEventsService
from app.services.document_ingestion_service import DocumentIngestionService

SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/0001/aapl-20250329.htm"
SEC_URL_8K = "https://www.sec.gov/Archives/edgar/data/320193/0002/aapl-8k.htm"
FEED_URL = "https://feeds.example.com/aapl/latest"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _doc(db: Session, company: Company, url: str | None, title: str, day: int) -> Document:
    doc = Document(
        company_id=company.id, title=title, source_type="SEC", source_url=url,
        published_at=datetime(2026, 9, day, tzinfo=UTC), checksum=f"sum-{url}-{day}-{title}",
        metadata_={}, tenant_id="tenant-test",
    )
    db.add(doc)
    return doc


def test_ingest_bytes_dedupes_sec_archive_url_despite_byte_drift(db):
    """Mismo filing SEC, bytes ligeramente distintos (deriva diaria):
    la segunda ingesta es duplicado, no una fila nueva."""
    _company(db)
    service = DocumentIngestionService()
    text = b"AAPL 10-Q content with enough text to parse into blocks. " * 4

    first = service.ingest_bytes(
        db, ticker="AAPL", title="AAPL 10-Q (2025-03-29)", content=text,
        filename="aapl-20250329.htm", source_type="SEC", source_url=SEC_URL,
    )
    assert first["status"] == "ingested"

    second = service.ingest_bytes(
        db, ticker="AAPL", title="AAPL 10-Q (2025-03-29)", content=text + b" ",
        filename="aapl-20250329.htm", source_type="SEC", source_url=SEC_URL,
    )
    assert second["status"] == "duplicate"
    assert "archive URL" in second["warnings"][0]
    assert len(db.scalars(select(Document).where(Document.source_url == SEC_URL)).all()) == 1


def test_ingest_bytes_keeps_changed_content_under_non_archive_url(db):
    """Una URL no-archivo puede servir contenido que cambia (un feed):
    contenido distinto bajo la misma URL es un documento nuevo."""
    _company(db)
    service = DocumentIngestionService()
    base = b"AAPL feed item with enough text to parse into blocks. " * 4

    first = service.ingest_bytes(
        db, ticker="AAPL", title="Feed snapshot 1", content=base,
        filename="feed-1.txt", source_type="feed", source_url=FEED_URL,
    )
    assert first["status"] == "ingested"

    second = service.ingest_bytes(
        db, ticker="AAPL", title="Feed snapshot 2", content=base + b"updated ",
        filename="feed-2.txt", source_type="feed", source_url=FEED_URL,
    )
    assert second["status"] == "ingested"
    assert second["document_id"] != first["document_id"]
    assert len(db.scalars(select(Document).where(Document.source_url == FEED_URL)).all()) == 2


def test_db_documents_collapses_sec_archive_reingests(db):
    """La vista por empresa lista una sola tarjeta por filing de archivo;
    se conserva la de mayor fecha de publicacion (no simplemente max id)."""
    company = _company(db)
    _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", 27)
    _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", 26)
    _doc(db, company, SEC_URL_8K, "AAPL 8-K", 25)
    db.commit()

    docs = CompanyEventsService(db)._db_documents(company, 40)
    assert [d["url"] for d in docs].count(SEC_URL) == 1
    assert len(docs) == 2
    kept = next(d for d in docs if d["url"] == SEC_URL)
    assert kept["published_at"].startswith("2026-09-27")


def test_db_documents_limit_applies_after_dedupe(db):
    """El limite se aplica sobre las filas ya deduplicadas: muchas
    re-ingestas recientes no pueden ocultar un documento unico antiguo."""
    company = _company(db)
    _doc(db, company, None, "Nota interna unica", 1)
    for day in range(2, 12):
        _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", day)
    db.commit()

    docs = CompanyEventsService(db)._db_documents(company, 2)
    assert len(docs) == 2
    titles = {d["title"] for d in docs}
    assert titles == {"AAPL 10-Q (2025-03-29)", "Nota interna unica"}


def test_db_documents_keeps_shared_non_archive_url_and_homonymous_notes(db):
    """Dos documentos distintos que comparten URL no-archivo se muestran
    ambos; dos notas internas homonimas sin URL tambien (consistencia con
    la vista global)."""
    company = _company(db)
    _doc(db, company, FEED_URL, "Feed snapshot 1", 26)
    _doc(db, company, FEED_URL, "Feed snapshot 2", 25)
    _doc(db, company, None, "Nota interna", 24)
    _doc(db, company, None, "Nota interna", 23)
    db.commit()

    docs = CompanyEventsService(db)._db_documents(company, 40)
    assert [d["url"] for d in docs].count(FEED_URL) == 2
    assert [d["title"] for d in docs].count("Nota interna") == 2
    assert len(docs) == 4


def test_global_documents_and_count_collapse_only_archive_groups(db):
    """La vista global /research/sources y su contador colapsan solo los
    grupos de archivo inmutable; el resto pasa siempre."""
    company = _company(db)
    _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", 26)
    _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", 27)
    _doc(db, company, FEED_URL, "Feed snapshot 1", 25)
    _doc(db, company, FEED_URL, "Feed snapshot 2", 24)
    _doc(db, company, None, "FMP normalized financials - AAPL", 23)
    db.commit()

    rows = documents(
        ticker=None, scope="all", include_chunks=False, page=1, page_size=50,
        chunk_limit=1000, chunk_text_limit=1500, db=db,
    )
    urls = [row["source_url"] for row in rows]
    assert urls.count(SEC_URL) == 1
    assert urls.count(FEED_URL) == 2
    assert len(rows) == 4

    total = documents_count(ticker=None, scope="all", db=db)
    assert total["total"] == 4


def test_http_documents_routes_registered_and_deduped(db):
    """Las rutas HTTP /api/sources/documents y /documents/count responden
    (registro de decoradores correcto) y aplican el mismo dedupe."""
    import os

    os.environ["RESEARCH_AUTH_REQUIRED"] = "false"
    from fastapi.testclient import TestClient

    import main
    from app.core.database import get_db

    company = _company(db)
    _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", 26)
    _doc(db, company, SEC_URL, "AAPL 10-Q (2025-03-29)", 27)
    _doc(db, company, None, "Nota interna", 25)
    db.commit()

    main.app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(main.app)
        listing = client.get("/api/sources/documents?ticker=AAPL&scope=all")
        assert listing.status_code == 200
        assert len(listing.json()) == 2
        count = client.get("/api/sources/documents/count?ticker=AAPL&scope=all")
        assert count.status_code == 200
        assert count.json()["total"] == 2
    finally:
        main.app.dependency_overrides.pop(get_db, None)
