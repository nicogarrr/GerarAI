from __future__ import annotations

import main
from app.api.routes import knowledge, sources
from tests.auth_helpers import csrf_client

_INTERNAL_DETAIL = (
    "provider=https://secret.example/path?token=abc "
    "local=C:/private/cavaai/cache.sql "
    "sql=SELECT private_value FROM credentials"
)


def _assert_no_internal_detail(response) -> None:
    body = response.text
    for fragment in (
        "https://secret.example/path?token=abc",
        "C:/private/cavaai/cache.sql",
        "SELECT private_value FROM credentials",
    ):
        assert fragment not in body


def test_knowledge_upload_does_not_expose_internal_exception(monkeypatch):
    class FailingKnowledgeLibraryService:
        def ingest_bytes(self, *args, **kwargs):
            raise RuntimeError(_INTERNAL_DETAIL)

    monkeypatch.setattr(
        knowledge,
        "KnowledgeLibraryService",
        FailingKnowledgeLibraryService,
    )
    client = csrf_client(main.app, raise_server_exceptions=False)

    response = client.post(
        "/api/knowledge/documents/upload",
        data={"title": "Private source", "document_type": "book"},
        files={"file": ("source.txt", b"private material", "text/plain")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Knowledge ingestion failed"
    _assert_no_internal_detail(response)


def test_sources_url_ingestion_does_not_expose_provider_url_or_exception(monkeypatch):
    class FailingDocumentIngestionService:
        def ingest_url(self, *args, **kwargs):
            raise RuntimeError(_INTERNAL_DETAIL)

    monkeypatch.setattr(
        sources,
        "DocumentIngestionService",
        FailingDocumentIngestionService,
    )
    client = csrf_client(main.app, raise_server_exceptions=False)

    response = client.post(
        "/api/sources/documents/ingest-url",
        json={
            "ticker": "MSFT",
            "title": "Private source",
            "url": "https://provider.example/report.pdf",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "URL ingestion failed"
    _assert_no_internal_detail(response)


def test_sources_file_ingestion_does_not_expose_internal_exception(monkeypatch):
    class FailingDocumentIngestionService:
        def ingest_bytes(self, *args, **kwargs):
            raise RuntimeError(_INTERNAL_DETAIL)

    monkeypatch.setattr(sources, "DocumentIngestionService", FailingDocumentIngestionService)
    client = csrf_client(main.app, raise_server_exceptions=False)
    response = client.post(
        "/api/sources/documents/ingest-file",
        data={"ticker": "MSFT", "title": "Private upload"},
        files={"file": ("source.txt", b"private material", "text/plain")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Document ingestion failed"
    _assert_no_internal_detail(response)
