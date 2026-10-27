"""Biblioteca de conocimiento enlazada a un ticker (campo opcional ``ticker``).

Un libro, una carta o una nota sobre una empresa concreta se puede asociar a
su ticker: se guarda normalizado (strip + upper), se filtra con ``ticker=`` y
la ficha ``/research/[ticker]`` lo lista como lectura de la biblioteca.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from app.core import auth as auth_module
from app.core.database import Base, SessionLocal, init_db
from app.models import KnowledgeDocument, Tenant
from app.seed import seed
from app.services.knowledge_library_service import (
    KnowledgeLibraryService,
    normalize_knowledge_ticker,
)
from tests.auth_helpers import auth_settings, signed_request


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id=f"kticker-{uuid4().hex[:8]}", name="KTicker")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _document(title: str, ticker: str | None = None) -> KnowledgeDocument:
    return KnowledgeDocument(
        title=title,
        document_type="personal_note",
        language="es",
        status="ready",
        checksum=uuid4().hex,
        metadata_={"parser": "native_text"},
        ticker=ticker,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" san.mc ", "SAN.MC"),
        ("brk-b", "BRK-B"),
        ("CGEO.L", "CGEO.L"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normaliza_ticker_opcional(raw, expected):
    assert normalize_knowledge_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["AAPL MSFT", "<script>", "A" * 33, "$AAPL", "..."])
def test_rechaza_ticker_con_forma_invalida(raw):
    with pytest.raises(ValueError, match="ticker"):
        normalize_knowledge_ticker(raw)


def test_ingesta_guarda_ticker_normalizado_y_document_dict_lo_expone(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_library_service.DocumentStore.put_bytes",
        lambda _self, *args, **kwargs: "minio://test/knowledge.txt",
    )
    db = _db()
    result = KnowledgeLibraryService().ingest_bytes(
        db,
        title="Carta sobre Santander",
        content=f"Notas de lectura sobre el banco y su capital {uuid4().hex}.".encode(),
        filename="nota.txt",
        document_type="personal_note",
        language="es",
        content_type="text/plain",
        ticker=" san.mc ",
    )
    assert result["status"] == "ingested"
    document = db.get(KnowledgeDocument, result["knowledge_document_id"])
    assert document is not None
    assert document.ticker == "SAN.MC"
    assert KnowledgeLibraryService.document_dict(document)["ticker"] == "SAN.MC"


def test_ingesta_sin_ticker_queda_en_null(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_library_service.DocumentStore.put_bytes",
        lambda _self, *args, **kwargs: "minio://test/knowledge.txt",
    )
    db = _db()
    result = KnowledgeLibraryService().ingest_bytes(
        db,
        title="Libro general",
        content=f"Principios generales de asignacion de capital {uuid4().hex}.".encode(),
        filename="libro.txt",
        document_type="book",
        content_type="text/plain",
    )
    document = db.get(KnowledgeDocument, result["knowledge_document_id"])
    assert document is not None
    assert document.ticker is None
    assert KnowledgeLibraryService.document_dict(document)["ticker"] is None


def test_list_documents_filtra_por_ticker_sin_distinguir_mayusculas():
    db = _db()
    db.add_all([
        _document("Sobre Uber", "UBER"),
        _document("Otra de Uber", "UBER"),
        _document("Sobre Pool", "POOL"),
        _document("General"),
    ])
    db.commit()
    titles = {
        item["title"] for item in KnowledgeLibraryService.list_documents(db, ticker="uber")
    }
    assert titles == {"Sobre Uber", "Otra de Uber"}
    assert len(KnowledgeLibraryService.list_documents(db)) == 4


def test_set_document_ticker_asigna_cambia_y_borra():
    db = _db()
    document = _document("Nota")
    db.add(document)
    db.commit()
    assert KnowledgeLibraryService.set_document_ticker(db, document, "rklb")["ticker"] == "RKLB"
    assert KnowledgeLibraryService.set_document_ticker(db, document, "ASTS")["ticker"] == "ASTS"
    assert KnowledgeLibraryService.set_document_ticker(db, document, "")["ticker"] is None
    db.refresh(document)
    assert document.ticker is None


def _client(monkeypatch) -> tuple[TestClient, str]:
    init_db()
    seed()
    secret = "tenant-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    return TestClient(main.app), secret


def test_api_patch_ticker_y_filtro_con_aislamiento_de_tenant(monkeypatch):
    client, secret = _client(monkeypatch)
    suffix = uuid4().hex[:8]
    tenant_a, tenant_b = f"kt-a-{suffix}", f"kt-b-{suffix}"
    db = SessionLocal()
    tenant_row = Tenant(external_id=tenant_a, name="Tenant A ticker")
    db.add(tenant_row)
    db.flush()
    db.info["tenant_id"] = tenant_row.id
    document = _document(f"Nota {suffix}")
    db.add(document)
    db.commit()
    document_id = document.id
    db.close()

    def call(tenant: str, method: str, path: str, **kwargs):
        return signed_request(client, secret, tenant, f"user-{tenant}", method, path, **kwargs)

    patch_path = f"/api/knowledge/documents/{document_id}"

    foreign = call(tenant_b, "PATCH", patch_path, json_body={"ticker": "POOL"})
    assert foreign.status_code == 404

    invalid = call(tenant_a, "PATCH", patch_path, json_body={"ticker": "AAPL MSFT"})
    assert invalid.status_code == 400

    own = call(tenant_a, "PATCH", patch_path, json_body={"ticker": " pool "})
    assert own.status_code == 200, own.text
    assert own.json()["ticker"] == "POOL"

    listed = call(tenant_a, "GET", "/api/knowledge/documents", params={"ticker": "pool"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [document_id]
    assert call(tenant_b, "GET", "/api/knowledge/documents", params={"ticker": "POOL"}).json() == []

    cleared = call(tenant_a, "PATCH", patch_path, json_body={"ticker": None})
    assert cleared.status_code == 200
    assert cleared.json()["ticker"] is None
    assert call(tenant_a, "GET", "/api/knowledge/documents", params={"ticker": "POOL"}).json() == []
