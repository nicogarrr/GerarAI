"""Bordes de ingesta: dedup por reintento, out-of-order, límite y timeout.

- Reintento del mismo documento/noticia → "duplicate"/skipped, sin filas
  nuevas (idempotencia ante reintentos de red).
- Transacciones insertadas fuera de orden cronológico → el rebuild
  ordena por trade_date y la posición queda correcta.
- Payload sobre el límite (15 MB) → ValueError en servicio y 400 honesto
  en la ruta (el fuente mapea a 400, no a 413: se fija el real).
- Timeout/destino caído en ingest-url → excepción sin fabricar documento
  y 502 honesto en la ruta.
Hermético salvo el TestClient local (SQLite de tests, sin red externa).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from app.core.database import SessionLocal, init_db
from app.models.entities import (
    Base,
    Company,
    Document,
    DocumentChunk,
    Transaction,
)
from app.schemas.api import NewsFeedItem
from app.services import document_ingestion_service as doc_module
from app.services.document_ingestion_service import (
    MAX_DOCUMENT_BYTES,
    DocumentIngestionService,
)
from app.services.news_service import NewsService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from tests.auth_helpers import csrf_client


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _text(marker: str) -> bytes:
    return (
        f"Azure AI demand and operating margin discipline support durable "
        f"cloud revenue growth for the thesis evidence set {marker}. "
        f"Capital expenditure remains disciplined across regions {marker}."
    ).encode()


def test_document_retry_returns_duplicate_without_new_rows(db):
    _company(db, "MSFT")
    marker = uuid4().hex
    content = _text(marker)
    service = DocumentIngestionService()

    first = service.ingest_bytes(
        db, ticker="MSFT", title=f"retry note {marker}", content=content,
        filename="retry-note.txt", source_type="test_upload",
        source_url="https://example.com/retry",
    )
    assert first["status"] == "ingested"
    docs_before = db.query(Document).count()
    chunks_before = db.query(DocumentChunk).count()

    second = service.ingest_bytes(
        db, ticker="MSFT", title=f"retry note {marker}", content=content,
        filename="retry-note.txt", source_type="test_upload",
        source_url="https://example.com/retry",
    )
    assert second["status"] == "duplicate"
    assert second["document_id"] == first["document_id"]
    assert db.query(Document).count() == docs_before
    assert db.query(DocumentChunk).count() == chunks_before

    # Limpieza del fichero local escrito por DocumentStore (ruta absoluta).
    uri = first.get("storage_uri") or ""
    candidate = Path(uri)
    if uri and candidate.is_absolute() and "storage" in candidate.parts:
        candidate.unlink(missing_ok=True)


def test_news_retry_skips_duplicate_deterministically(db):
    _company(db, "MSFT")
    marker = uuid4().hex
    item = NewsFeedItem(
        title=f"MSFT cuts guidance after earnings miss {marker}",
        text="The company lowered revenue and FCF margin guidance.",
        ticker="MSFT",
        url=f"https://www.sec.gov/Archives/{marker}",
        source="sec_filing",
    )
    service = NewsService()
    first = service.ingest_news_items(db, [item], default_source="sec_filing")
    assert first.created == 1 and first.skipped_duplicates == 0

    second = service.ingest_news_items(db, [item], default_source="sec_filing")
    assert second.received == 1
    assert second.created == 0
    assert second.skipped_duplicates == 1


def test_out_of_order_inserts_rebuild_correct_position(db):
    service = PortfolioLedgerService()
    company = service.ensure_company(db, "OOO")
    # Insertadas fuera de orden: la venta (posterior) llega primero.
    db.add(Transaction(
        company_id=company.id, trade_date=date(2026, 3, 10), action="sell",
        quantity=Decimal("5"), price=Decimal("150"), fees=Decimal("0"),
        currency="EUR", external_id="manual-ooo-sell",
    ))
    db.add(Transaction(
        company_id=company.id, trade_date=date(2026, 1, 10), action="buy",
        quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"),
        currency="EUR", external_id="manual-ooo-buy",
    ))
    db.commit()

    position = service.rebuild_position(db, company.id)
    assert position is not None
    assert position.quantity == Decimal("5")
    assert position.average_cost == Decimal("100")
    assert position.realized_pnl == Decimal("250")  # (150−100)×5


def test_oversize_payload_rejected_at_service_limit(db):
    _company(db, "MSFT")
    content = b"x" * (MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds 15MB"):
        DocumentIngestionService().ingest_bytes(
            db, ticker="MSFT", title="oversize", content=content,
            filename="big.txt", source_type="test_upload",
        )


def test_oversize_upload_rejected_honestly_by_route():
    """La ruta (15MB) valida el fichero decodificado y rechaza con 400.

    El middleware deja margen de ~1MB sobre 15MB para el overhead multipart,
    asi que un cuerpo de 15MB+1 llega a la ruta y es ella quien responde
    con su error de validacion, no un 413 generico del middleware.
    """
    init_db()
    client = csrf_client(main.app)
    response = client.post(
        "/api/sources/documents/ingest-file",
        data={
            "ticker": "MSFT",
            "title": "oversize upload",
            "source_type": "test_upload",
        },
        files={"file": ("big.txt", b"x" * (MAX_DOCUMENT_BYTES + 1), "text/plain")},
        # Una subida legitima viene firmada; sin firma el RawBodyMiddleware la
        # corta a 1MB (413) antes de que llegue a la ruta.
        headers={"X-CavaAI-Signature": "present-but-not-checked-by-the-body-middleware"},
    )
    assert response.status_code == 400
    assert "15MB" in response.json()["detail"]


def test_ingest_url_timeout_raises_without_fabricating(db, monkeypatch):
    _company(db, "MSFT")

    def _boom(url, **kwargs):
        raise TimeoutError("upstream silencioso (simulado)")

    monkeypatch.setattr(doc_module, "fetch_public_url", _boom)
    with pytest.raises(TimeoutError):
        DocumentIngestionService().ingest_url(
            db, ticker="MSFT", title="timeout",
            url="https://example.com/slow.pdf", source_type="test_upload",
        )
    assert db.query(Document).count() == 0  # nada fabricado


def test_ingest_url_route_maps_timeout_to_502(monkeypatch):
    init_db()
    db = SessionLocal()
    try:
        from app.seed import seed
        seed()
    finally:
        db.close()

    def _boom(url, **kwargs):
        raise TimeoutError("upstream silencioso (simulado)")

    monkeypatch.setattr(doc_module, "fetch_public_url", _boom)
    client = csrf_client(main.app)
    response = client.post(
        "/api/sources/documents/ingest-url",
        json={
            "ticker": "MSFT",
            "title": "timeout upload",
            "url": "https://example.com/slow.pdf",
            "source_type": "test_upload",
        },
    )
    assert response.status_code == 502
    assert "failed" in response.json()["detail"].lower()
