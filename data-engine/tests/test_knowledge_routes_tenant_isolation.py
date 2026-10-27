"""Aislamiento entre tenants en /api/knowledge (fixtures sinteticos).

El tenant A siembra filas REALES (coleccion, documento, chunk, principio y
job). Todas las aserciones del tenant B usan los ids reales de A, de modo que
un filtro de tenant roto hace fallar el test (no pasa por vacio).
"""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import (
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    ProcessingJob,
    Tenant,
)
from app.seed import seed
from app.services.knowledge_library_service import KnowledgeLibraryService
from tests.auth_helpers import auth_settings, signed_request
from tests.test_knowledge_library import PrincipleProvider

ALL = {"include_all_tenants": True}


def test_knowledge_routes_do_not_cross_tenants(monkeypatch):
    init_db()
    seed()
    secret = "tenant-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    suffix = uuid4().hex[:8]
    tenant_a, user_a = f"kn-a-{suffix}", f"user-a-{suffix}"
    tenant_b, user_b = f"kn-b-{suffix}", f"user-b-{suffix}"
    name = f"Coleccion privada {suffix}"
    fragment = f"Capital reinvested at high returns compounds {suffix}."
    client = TestClient(main.app)

    def call(tenant, user, method, path, **kw):
        return signed_request(client, secret, tenant, user, method, path, **kw)

    def as_a(method, path, **kw):
        return call(tenant_a, user_a, method, path, **kw)

    def as_b(method, path, **kw):
        return call(tenant_b, user_b, method, path, **kw)

    try:
        assert client.get("/api/knowledge/collections").status_code == 401

        created = as_a("POST", "/api/knowledge/collections", json_body={"name": name})
        assert created.status_code == 200
        collection_id = created.json()["id"]
        # Materializa el tenant B antes de sembrar nada de A.
        assert as_b("GET", "/api/knowledge/collections").status_code == 200

        # Siembra real de A: documento, chunk, principio y job.
        with SessionLocal() as db:
            a_id = db.scalar(select(Tenant.id).where(Tenant.external_id == tenant_a))
            b_id = db.scalar(select(Tenant.id).where(Tenant.external_id == tenant_b))
            assert a_id and b_id and a_id != b_id
            db.info["tenant_id"] = a_id
            service = KnowledgeLibraryService()
            ingested = service.ingest_bytes(
                db,
                title=f"Nota privada {suffix}",
                content=f"{fragment} Unica {suffix}.".encode(),
                filename="nota.txt",
                document_type="personal_note",
                collection_id=collection_id,
                author="audit",
                language="en",
                content_type="text/plain",
            )
            document_id = ingested["knowledge_document_id"]
            document = db.get(KnowledgeDocument, document_id)
            chunk = db.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.knowledge_document_id == document_id
                )
            )
            principles = asyncio.run(
                KnowledgeLibraryService(
                    PrincipleProvider(chunk.id, fragment)
                ).propose_principles(db, document)
            )
            assert len(principles) == 1
            principle_id = principles[0].id
            job = ProcessingJob(
                job_type="knowledge_principle_extraction",
                entity_type="knowledge_document",
                entity_id=document_id,
                status="queued",
            )
            db.add(job)
            db.commit()
            job_id = job.id
            assert job.tenant_id == a_id

        # Control positivo: A ve sus propias filas (el test no es vacuo).
        assert as_a("GET", f"/api/knowledge/jobs/{job_id}").status_code == 200
        assert any(j["id"] == job_id for j in as_a("GET", "/api/knowledge/jobs").json())
        assert as_a("GET", f"/api/knowledge/documents/{document_id}").status_code == 200
        assert as_a("GET", f"/api/knowledge/documents/{document_id}/chunks").json()
        assert any(p["id"] == principle_id for p in as_a("GET", "/api/knowledge/principles").json())

        # B con los ids REALES de A: todo vacio o 404.
        names_b = {c["name"] for c in as_b("GET", "/api/knowledge/collections").json()}
        assert name not in names_b
        assert as_b("DELETE", f"/api/knowledge/collections/{collection_id}").status_code == 404
        assert as_b("GET", "/api/knowledge/jobs").json() == []
        assert as_b("GET", "/api/knowledge/jobs", params={"document_id": document_id}).json() == []
        assert as_b("GET", f"/api/knowledge/jobs/{job_id}").status_code == 404
        assert as_b("GET", f"/api/knowledge/documents/{document_id}").status_code == 404
        assert as_b("GET", f"/api/knowledge/documents/{document_id}/chunks").status_code == 404
        assert as_b("GET", "/api/knowledge/documents").json() == []
        assert as_b("PATCH", f"/api/knowledge/documents/{document_id}",
                    json_body={"ticker": "MSFT"}).status_code == 404
        assert as_b("DELETE", f"/api/knowledge/documents/{document_id}").status_code == 404
        assert as_b("POST", f"/api/knowledge/documents/{document_id}/extract-principles"
                    ).status_code == 404
        assert as_b("GET", "/api/knowledge/principles").json() == []
        assert not as_b("GET", "/api/knowledge/principles/page").json().get("items")
        assert as_b("POST", f"/api/knowledge/principles/{principle_id}/action",
                    json_body={"action": "approve"}).status_code == 404
        assert as_b("PUT", f"/api/knowledge/principles/{principle_id}",
                    json_body={"principle": "Reescrito por B"}).status_code == 404

        # El mismo nombre en B no choca con el de A (unicidad por tenant).
        same_name_b = as_b("POST", "/api/knowledge/collections", json_body={"name": name})
        assert same_name_b.status_code == 200
        assert same_name_b.json()["id"] != collection_id

        # Nada de A cambio por los intentos de B.
        with SessionLocal() as db:
            principle = db.scalar(
                select(InvestmentPrinciple).where(InvestmentPrinciple.id == principle_id)
                .execution_options(**ALL)
            )
            assert principle.status == "proposed"
            assert principle.tenant_id == a_id
            doc = db.scalar(
                select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
                .execution_options(**ALL)
            )
            assert doc is not None and doc.ticker is None
        assert as_a("GET", f"/api/knowledge/documents/{document_id}").status_code == 200
    finally:
        with SessionLocal() as db:
            tenant_ids = db.scalars(
                select(Tenant.id).where(Tenant.external_id.in_([tenant_a, tenant_b]))
            ).all()
            if tenant_ids:
                for model in (InvestmentPrinciple, ProcessingJob, KnowledgeChunk,
                              KnowledgeDocument, KnowledgeCollection):
                    db.execute(
                        delete(model).where(model.tenant_id.in_(tenant_ids))
                        .execution_options(**ALL)
                    )
                db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
            db.commit()
