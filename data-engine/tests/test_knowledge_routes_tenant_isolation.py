"""Aislamiento entre tenants en /api/knowledge (fixtures sinteticos)."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import KnowledgeCollection, Tenant
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request


def test_knowledge_collections_jobs_and_principles_do_not_cross_tenants(monkeypatch):
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
    client = TestClient(main.app)

    def call(tenant, user, method, path, **kw):
        return signed_request(client, secret, tenant, user, method, path, **kw)

    try:
        assert client.get("/api/knowledge/collections").status_code == 401

        created = call(tenant_a, user_a, "POST", "/api/knowledge/collections",
                       json_body={"name": name})
        assert created.status_code == 200
        collection_id = created.json()["id"]

        names_b = {c["name"] for c in call(
            tenant_b, user_b, "GET", "/api/knowledge/collections").json()}
        assert name not in names_b

        # Otro tenant no ve ni borra la coleccion ajena: 404 como inexistente.
        cross_delete = call(tenant_b, user_b, "DELETE",
                            f"/api/knowledge/collections/{collection_id}")
        assert cross_delete.status_code == 404

        # El mismo nombre en B no choca con el de A (unicidad por tenant).
        same_name_b = call(tenant_b, user_b, "POST", "/api/knowledge/collections",
                           json_body={"name": name})
        assert same_name_b.status_code == 200
        assert same_name_b.json()["id"] != collection_id

        # La coleccion de A sigue ahi tras el intento de B.
        names_a = {c["name"] for c in call(
            tenant_a, user_a, "GET", "/api/knowledge/collections").json()}
        assert name in names_a

        # Jobs, principios y documentos ajenos/inexistentes: sin fuga.
        assert call(tenant_b, user_b, "GET", "/api/knowledge/jobs").json() == []
        assert call(tenant_b, user_b, "GET", "/api/knowledge/jobs/999999999").status_code == 404
        assert call(tenant_b, user_b, "GET",
                    "/api/knowledge/documents/999999999").status_code == 404
        assert call(tenant_b, user_b, "POST", "/api/knowledge/principles/999999999/action",
                    json_body={"action": "approve"}).status_code == 404
    finally:
        db = SessionLocal()
        tenant_ids = db.scalars(
            select(Tenant.id).where(Tenant.external_id.in_([tenant_a, tenant_b]))
        ).all()
        if tenant_ids:
            db.execute(delete(KnowledgeCollection).where(
                KnowledgeCollection.tenant_id.in_(tenant_ids))
                .execution_options(include_all_tenants=True))
            db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        db.commit()
        db.close()
