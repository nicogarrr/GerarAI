"""Revisar un principio con texto en blanco.

``PrincipleRevision`` validaba la longitud antes de quitar espacios: «     »
pasaba ``min_length=3``, el servicio lo dejaba vacío y la ruta respondía 409
«conflict» (como si chocara con otra versión). Una categoría o un fragmento
en blanco ni siquiera se comprobaban: se guardaba una versión nueva con la
categoría vacía. Ahora es 422 de validación y no se crea ninguna versión.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import InvestmentPrinciple, KnowledgeChunk, KnowledgeDocument, Tenant
from app.services.knowledge_library_service import KnowledgeLibraryService
from tests.auth_helpers import auth_settings, signed_request
from tests.test_knowledge_library import PrincipleProvider

SECRET = "principle-revision-blank-secret-32-chars"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    tenant_ext, user = f"prb-{suffix}", f"prb-user-{suffix}"
    client = TestClient(main.app)

    def call(method, path, body=None):
        return signed_request(client, SECRET, tenant_ext, user, method, path, json_body=body)

    collection = call("POST", "/api/knowledge/collections", {"name": f"Revisiones {suffix}"})
    assert collection.status_code == 200, collection.text
    fragment = f"Buy businesses with durable moats {suffix}."
    with SessionLocal() as db:
        db.info["tenant_id"] = db.scalar(select(Tenant.id).where(Tenant.external_id == tenant_ext))
        ingested = KnowledgeLibraryService().ingest_bytes(
            db, title=f"Nota {suffix}", content=f"{fragment} Unica {suffix}.".encode(),
            filename="nota.txt", document_type="personal_note",
            collection_id=collection.json()["id"], author="audit", language="en",
            content_type="text/plain",
        )
        document = db.get(KnowledgeDocument, ingested["knowledge_document_id"])
        chunk = db.scalar(select(KnowledgeChunk).where(
            KnowledgeChunk.knowledge_document_id == document.id))
        principles = asyncio.run(
            KnowledgeLibraryService(PrincipleProvider(chunk.id, fragment)).propose_principles(db, document)
        )
        principle_id = principles[0].id

    def versions() -> int:
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(InvestmentPrinciple).where(
                (InvestmentPrinciple.id == principle_id)
                | (InvestmentPrinciple.canonical_principle_id == principle_id)))

    return call, principle_id, versions


@pytest.mark.parametrize("body", [
    {"principle": "      "},
    {"principle": " \t\n "},
    {"principle": "  a  "},
    {"category": "   "},
    {"exact_fragment": "   "},
])
def test_revision_en_blanco_es_422_y_no_crea_version(env, body) -> None:
    call, principle_id, versions = env
    before = versions()
    res = call("PUT", f"/api/knowledge/principles/{principle_id}", body)
    assert res.status_code == 422, (body, res.status_code, res.text)
    assert versions() == before


def test_revision_valida_sigue_funcionando(env) -> None:
    call, principle_id, versions = env
    before = versions()
    res = call("PUT", f"/api/knowledge/principles/{principle_id}",
               {"principle": "  Comprar negocios con foso duradero  ", "category": " moat "})
    assert res.status_code == 200, res.text
    assert res.json()["principle"] == "Comprar negocios con foso duradero"
    assert res.json()["category"] == "moat"
    assert versions() == before + 1


def test_revision_con_empresas_inexistentes_es_422(env) -> None:
    call, principle_id, versions = env
    before = versions()
    for ids in ([0], [-3], [987654321]):
        res = call("PUT", f"/api/knowledge/principles/{principle_id}", {"applies_to_company_ids": ids})
        assert res.status_code == 422, (ids, res.status_code, res.text)
    assert versions() == before
