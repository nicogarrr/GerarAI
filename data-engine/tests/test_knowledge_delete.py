"""DELETE /api/knowledge/documents/{id}: cascada y aislamiento de tenant."""
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import main
from app.core import auth as auth_module
from app.core.database import Base, SessionLocal, init_db
from app.models import (
    InvestmentCaseStudy,
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    Tenant,
)
from app.seed import seed
from app.services.knowledge_library_service import KnowledgeLibraryService
from tests.auth_helpers import auth_settings, csrf_client, signed_request


def _document(title: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        title=title,
        document_type="personal_note",
        language="en",
        status="ready",
        checksum=uuid4().hex,
        metadata_={"parser": "native_text"},
    )


def test_delete_document_cascada_fragmentos_principios_y_casos(monkeypatch):
    deleted_originals: list[str | None] = []
    vector_deletes: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.knowledge_library_service.DocumentStore.delete",
        lambda _self, uri: deleted_originals.append(uri) or True,
    )
    monkeypatch.setattr(
        "app.services.rag.RAGIndex.delete_knowledge_document_points",
        lambda _self, tenant_id, document_id: vector_deletes.append(
            (tenant_id, document_id)
        )
        or 1,
    )
    monkeypatch.delenv("CAVAAI_ENABLE_VECTOR_INGEST", raising=False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id=f"delete-test-{uuid4().hex[:8]}", name="Delete")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id

        kept = _document("Se queda")
        gone = _document("Se borra")
        gone.storage_uri = "minio://research/tenant-1/KNOWLEDGE/note/gone.txt"
        db.add_all([kept, gone])
        db.flush()
        db.add_all([
            KnowledgeChunk(knowledge_document_id=kept.id, chunk_index=0, content="kept chunk"),
            KnowledgeChunk(knowledge_document_id=gone.id, chunk_index=0, content="gone chunk 0"),
            KnowledgeChunk(knowledge_document_id=gone.id, chunk_index=1, content="gone chunk 1"),
        ])
        db.flush()
        kept_chunk = db.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == kept.id)
        )
        gone_chunk = db.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == gone.id)
        )
        db.add(
            InvestmentPrinciple(
                knowledge_document_id=gone.id,
                knowledge_chunk_id=gone_chunk.id,
                principle="Principio derivado del documento borrado.",
                category="capital_allocation",
                exact_fragment="gone chunk 0",
                status="proposed",
                principle_fingerprint=uuid4().hex,
            )
        )
        db.add(
            InvestmentCaseStudy(
                knowledge_document_id=gone.id,
                title="Caso que sobrevive sin enlace",
                summary="Resumen",
                outcome="Resultado",
            )
        )
        db.commit()
        gone_storage_uri = gone.storage_uri
        gone_id = gone.id
        tenant_id = tenant.id

        result = KnowledgeLibraryService.delete_document(db, gone)
        assert result == {"chunks_deleted": 2, "principles_deleted": 1}

        assert db.get(KnowledgeDocument, gone.id) is None
        assert db.get(KnowledgeDocument, kept.id) is not None
        remaining_chunks = db.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == gone.id)
        ).all()
        assert remaining_chunks == []
        assert kept_chunk.id is not None
        assert db.scalar(
            select(InvestmentPrinciple).where(
                InvestmentPrinciple.knowledge_document_id == gone.id
            )
        ) is None
        case_study = db.scalar(
            select(InvestmentCaseStudy).where(
                InvestmentCaseStudy.title == "Caso que sobrevive sin enlace"
            )
        )
        assert case_study is not None
        assert case_study.knowledge_document_id is None
        # El original y el vector se limpian aunque la ingesta vectorial este
        # apagada en este proceso: el flag no puede dejar huerfanos.
        assert deleted_originals == [gone_storage_uri]
        assert vector_deletes == [(tenant_id, gone_id)]


def test_delete_document_cross_tenant_devuelve_404(monkeypatch):
    monkeypatch.setattr(
        "app.services.rag.RAGIndex.delete_knowledge_document_points",
        lambda _self, tenant_id, document_id: 1,
    )
    init_db()
    seed()
    secret = "tenant-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    suffix = uuid4().hex[:8]
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    client = csrf_client(main.app)

    # Documento del tenant A creado con el contexto de tenant de la sesion,
    # como lo haria cualquier escritura real.
    db = SessionLocal()
    tenant_row = Tenant(external_id=tenant_a, name="Tenant A")
    db.add(tenant_row)
    db.flush()
    db.info["tenant_id"] = tenant_row.id
    document = _document(f"Doc privado {suffix}")
    db.add(document)
    db.flush()
    db.add(KnowledgeChunk(knowledge_document_id=document.id, chunk_index=0, content="privado"))
    db.commit()
    document_id = document.id
    tenant_row_id = tenant_row.id
    db.close()

    unauthenticated = client.delete(f"/api/knowledge/documents/{document_id}")
    assert unauthenticated.status_code == 401

    cross_tenant = signed_request(
        client, secret, tenant_b, f"user-b-{suffix}", "DELETE",
        f"/api/knowledge/documents/{document_id}",
    )
    assert cross_tenant.status_code == 404

    own = signed_request(
        client, secret, tenant_a, f"user-a-{suffix}", "DELETE",
        f"/api/knowledge/documents/{document_id}",
    )
    assert own.status_code == 204

    gone = signed_request(
        client, secret, tenant_a, f"user-a-{suffix}", "GET",
        f"/api/knowledge/documents/{document_id}",
    )
    assert gone.status_code == 404

    db = SessionLocal()
    assert db.get(KnowledgeDocument, document_id, execution_options={"include_all_tenants": True}) is None
    assert db.scalars(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.knowledge_document_id == document_id)
        .execution_options(include_all_tenants=True)
    ).all() == []
    db.delete(db.get(Tenant, tenant_row_id))
    db.commit()
    db.close()


def test_delete_collection_vacia_y_aislamiento(monkeypatch):
    monkeypatch.setattr(
        "app.services.rag.RAGIndex.delete_knowledge_document_points",
        lambda _self, tenant_id, document_id: 1,
    )
    init_db()
    seed()
    secret = "tenant-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    suffix = uuid4().hex[:8]
    tenant_a = f"tenant-a-col-{suffix}"
    tenant_b = f"tenant-b-col-{suffix}"
    client = csrf_client(main.app)

    db = SessionLocal()
    tenant_row = Tenant(external_id=tenant_a, name="Tenant A col")
    db.add(tenant_row)
    db.flush()
    db.info["tenant_id"] = tenant_row.id
    empty = KnowledgeCollection(
        name=f"Vacia {suffix}", slug=f"vacia-{suffix}",
        description="", collection_type="custom",
    )
    with_docs = KnowledgeCollection(
        name=f"Con docs {suffix}", slug=f"con-docs-{suffix}",
        description="", collection_type="custom",
    )
    db.add_all([empty, with_docs])
    db.flush()
    document = _document(f"Doc en coleccion {suffix}")
    document.collection_id = with_docs.id
    db.add(document)
    db.commit()
    empty_id, with_docs_id = empty.id, with_docs.id
    db.close()

    unauthenticated = client.delete(f"/api/knowledge/collections/{empty_id}")
    assert unauthenticated.status_code == 401

    cross_tenant = signed_request(
        client, secret, tenant_b, f"user-b-{suffix}", "DELETE",
        f"/api/knowledge/collections/{empty_id}",
    )
    assert cross_tenant.status_code == 404

    # Con documentos: la coleccion NO se borra (409 fijo, sin filtrar internos).
    not_empty = signed_request(
        client, secret, tenant_a, f"user-a-{suffix}", "DELETE",
        f"/api/knowledge/collections/{with_docs_id}",
    )
    assert not_empty.status_code == 409

    own = signed_request(
        client, secret, tenant_a, f"user-a-{suffix}", "DELETE",
        f"/api/knowledge/collections/{empty_id}",
    )
    assert own.status_code == 204

    db = SessionLocal()
    db.info["tenant_id"] = tenant_row.id
    assert db.get(KnowledgeCollection, empty_id) is None
    assert db.get(KnowledgeCollection, with_docs_id) is not None
    db.close()
