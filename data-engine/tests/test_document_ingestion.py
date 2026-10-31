from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter
from sqlalchemy import delete, select

import main
from app.core.csrf import generate_csrf_token
from app.core.database import SessionLocal, init_db
from app.models import Document, DocumentChunk
from app.seed import seed
from app.services.document_ingestion_service import DocumentIngestionService


def cleanup_test_uploads() -> None:
    init_db()
    db = SessionLocal()
    try:
        documents = db.scalars(select(Document).where(Document.source_type == "test_upload")).all()
        document_ids = [document.id for document in documents]
        if document_ids:
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids)))
            db.execute(delete(Document).where(Document.id.in_(document_ids)))
            db.commit()
    finally:
        db.close()

    raw_root = Path("storage/raw/MSFT/test_upload")
    if raw_root.exists():
        for path in raw_root.glob("*"):
            if path.is_file():
                path.unlink()


def test_pdf_parser_uses_the_maintained_pypdf_package():
    content = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(content)

    parsed = DocumentIngestionService()._parse_pdf(content.getvalue())

    assert parsed.parser == "pypdf"
    assert parsed.blocks == []


def test_ingest_file_rejects_source_url_beyond_document_column():
    """Document.source_url es String(1000): un source_url mas largo debe ser
    422 de validacion, no un 500 al insertar en Postgres."""
    cleanup_test_uploads()
    seed()
    client = TestClient(main.app)
    client.headers["X-CSRF-Token"] = generate_csrf_token()
    response = client.post(
        "/api/sources/documents/ingest-file",
        data={
            "ticker": "MSFT",
            "title": f"oversized source_url {uuid4().hex}",
            "source_type": "test_upload",
            "source_url": "https://example.com/" + "a" * 1200,  # 1220 > 1000
        },
        files={"file": ("note.txt", b"short note body for source_url bound test", "text/plain")},
    )
    assert response.status_code == 422


def test_file_ingestion_creates_traceable_chunks_and_dedupes():
    cleanup_test_uploads()
    seed()
    client = TestClient(main.app)
    client.headers["X-CSRF-Token"] = generate_csrf_token()
    unique = uuid4().hex
    text = (
        f"Azure AI demand and operating margin discipline are key thesis evidence {unique}. "
        "This manually uploaded document should be chunked with checksum lineage."
    )

    response = client.post(
        "/api/sources/documents/ingest-file",
        data={
            "ticker": "MSFT",
            "title": f"MSFT uploaded note {unique}",
            "source_type": "test_upload",
            "source_url": "https://example.com/msft-upload-note",
        },
        files={"file": ("msft-note.txt", text.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ingested"
    assert payload["chunks"] >= 1
    assert payload["parser"] == "native_text"
    assert len(payload["checksum"]) == 64

    duplicate = client.post(
        "/api/sources/documents/ingest-file",
        data={
            "ticker": "MSFT",
            "title": f"MSFT uploaded note duplicate {unique}",
            "source_type": "test_upload",
        },
        files={"file": ("msft-note.txt", text.encode("utf-8"), "text/plain")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

    documents = client.get("/api/sources/documents?ticker=MSFT&scope=all&include_chunks=true")
    assert documents.status_code == 200
    uploaded = next(item for item in documents.json() if item["id"] == payload["document_id"])
    assert uploaded["checksum"] == payload["checksum"]
    assert uploaded["metadata"]["parser"] == "native_text"
    assert uploaded["chunks"][0]["metadata"]["checksum"] == payload["checksum"]
    assert uploaded["chunks"][0]["metadata"]["chunk_sha256"]
    assert len(uploaded["chunks"][0]["text"]) > 120

    limited_documents = client.get("/api/sources/documents?ticker=MSFT&scope=all&include_chunks=true&chunk_text_limit=120")
    assert limited_documents.status_code == 200
    limited_uploaded = next(item for item in limited_documents.json() if item["id"] == payload["document_id"])
    assert len(limited_uploaded["chunks"][0]["text"]) <= 120

    chat = client.post(
        "/api/chat",
        json={
            "ticker": "MSFT",
            "scope": "company",
            "question": f"What source mentions operating margin discipline {unique}?",
        },
    )
    assert chat.status_code == 200
    assert "document_chunk" in {source["type"] for source in chat.json()["sources"]}

    cleanup_test_uploads()


def test_xlsx_ingestion_preserves_sheet_lineage():
    cleanup_test_uploads()
    seed()
    client = TestClient(main.app)
    client.headers["X-CSRF-Token"] = generate_csrf_token()
    unique = uuid4().hex

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "KPIs"
    sheet.append(["metric", "value", "note"])
    sheet.append(["revenue_growth", "12%", f"management guidance {unique}"])
    output = BytesIO()
    workbook.save(output)

    response = client.post(
        "/api/sources/documents/ingest-file",
        data={
            "ticker": "MSFT",
            "title": f"MSFT KPI workbook {unique}",
            "source_type": "test_upload",
        },
        files={
            "file": (
                "msft-kpis.xlsx",
                output.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ingested"
    assert payload["parser"] == "openpyxl"

    documents = client.get("/api/sources/documents?ticker=MSFT&scope=all&include_chunks=true")
    uploaded = next(item for item in documents.json() if item["id"] == payload["document_id"])
    assert uploaded["chunks"][0]["metadata"]["block_metadata"][0]["sheet"] == "KPIs"
    assert unique in uploaded["chunks"][0]["text"]

    cleanup_test_uploads()
