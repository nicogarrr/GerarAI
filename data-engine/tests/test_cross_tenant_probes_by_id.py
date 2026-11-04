"""Sondas de aislamiento entre tenants en las rutas que cargan por id.

Complementa tests/test_cross_tenant_probes.py (que crea los recursos por la
API). Aquí los recursos del tenant A se siembran directamente en la base, con
el contexto de tenant de A, para cubrir las familias que no se pueden crear
por la API sin red ni LLM: estado de jobs de tesis y de la biblioteca,
documentos de fuentes y de la biblioteca, alertas, revisiones y principios.

Para cada ruta por id, el tenant B recibe 404/403 (nunca 2xx ni 5xx) y el
recurso de A sigue intacto. El tenant A sí puede leer lo suyo: la sonda no
pasa por un 404 que lo deniegue a todo el mundo.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.models.entities import (
    Document,
    DocumentChunk,
    InvestmentPrinciple,
    KnowledgeDocument,
    ProcessingJob,
    ResearchAlert,
    ResearchReview,
    WorkflowRun,
)
from tests.auth_helpers import auth_settings, signed_request
from tests.test_cross_tenant_probes import _no_network

SECRET = "cross-tenant-by-id-secret-with-at-least-32-chars"


@pytest.fixture()
def world(monkeypatch):
    _no_network(monkeypatch)
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app.broker, "enqueue", lambda message, delay=None: message)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app)

    def call(tenant: str, method: str, path: str, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    # Materializa los dos tenants por la ruta real (get_db los crea).
    for who in ("a", "b"):
        assert call(who, "GET", "/api/alerts/rules").status_code == 200

    with SessionLocal() as db:
        tenant_a = db.scalar(select(Tenant).where(Tenant.external_id == f"a-{suffix}"))
        assert tenant_a is not None
        db.info["tenant_id"] = tenant_a.id
        run = WorkflowRun(
            workflow_name="GenerateThesisWorkflow", status="running",
            input_payload={"ticker": "MSFT"},
        )
        document = Document(title="Informe privado de A", source_type="upload")
        alert = ResearchAlert(
            alert_type="thesis_review", title="Alerta privada de A",
            message="solo A", fingerprint=f"h9-{suffix}", channels=["in_app"],
        )
        job = ProcessingJob(
            job_type="knowledge_principle_extraction", entity_type="knowledge_document",
            status="running",
        )
        review = ResearchReview(review_type="thesis", title="Revisión privada de A", status="open")
        knowledge = KnowledgeDocument(title="Libro privado de A", document_type="book")
        db.add_all([run, document, alert, job, review, knowledge])
        db.flush()
        db.add(DocumentChunk(document_id=document.id, chunk_index=0, text="texto privado de A"))
        principle = InvestmentPrinciple(
            **_principle_kwargs(knowledge.id, suffix),
        )
        db.add(principle)
        db.commit()
        ids = {
            "run": run.id, "document": document.id, "alert": alert.id, "job": job.id,
            "review": review.id, "knowledge": knowledge.id, "principle": principle.id,
            "tenant_a": tenant_a.id,
        }
    return call, ids


def _principle_kwargs(knowledge_id: int, suffix: str) -> dict:
    """Campos obligatorios de InvestmentPrinciple sin depender de su orden."""
    columns = InvestmentPrinciple.__table__.columns
    values: dict = {}
    for column in columns:
        if column.primary_key or column.nullable or column.default is not None:
            continue
        if column.server_default is not None or column.name == "tenant_id":
            continue
        python_type = getattr(column.type, "python_type", str)
        values[column.name] = (
            knowledge_id if column.name.endswith("document_id")
            else f"principio privado de A {suffix}" if python_type is str
            else 1
        )
    return values


# (método, ruta con {clave}, clave del recurso, cuerpo)
PROBES = [
    ("GET", "/api/thesis/jobs/{run}", "run", None),
    ("GET", "/api/sources/documents/{document}/chunks", "document", None),
    ("POST", "/api/sources/documents/{document}/analyze", "document", None),
    ("GET", "/api/alerts/{alert}/analysis", "alert", None),
    ("POST", "/api/alerts/{alert}/action", "alert", {"action": "resolve"}),
    ("PATCH", "/api/alerts/{alert}/channels", "alert", {"channels": ["email"]}),
    ("POST", "/api/alerts/{alert}/dispatch", "alert", None),
    ("PATCH", "/api/reviews/{review}", "review", {"status": "dismissed"}),
    ("GET", "/api/knowledge/jobs/{job}", "job", None),
    ("GET", "/api/knowledge/documents/{knowledge}", "knowledge", None),
    ("GET", "/api/knowledge/documents/{knowledge}/chunks", "knowledge", None),
    ("PATCH", "/api/knowledge/documents/{knowledge}", "knowledge", {"ticker": "MSFT"}),
    ("POST", "/api/knowledge/documents/{knowledge}/extract-principles", "knowledge", None),
    ("DELETE", "/api/knowledge/documents/{knowledge}", "knowledge", None),
    ("POST", "/api/knowledge/principles/{principle}/action", "principle", {"action": "approve"}),
]


@pytest.mark.parametrize(
    ("method", "template", "key", "body"), PROBES, ids=[f"{m} {t}" for m, t, _, _ in PROBES]
)
def test_otro_tenant_no_accede_por_id(world, method, template, key, body):
    call, ids = world
    path = template.format(**ids)
    response = call("b", method, path, body)
    assert response.status_code in (403, 404), (
        f"tenant B {method} {path} -> {response.status_code} {response.text[:300]}"
    )


@pytest.mark.parametrize(
    "template",
    [t for m, t, _, _ in PROBES if m == "GET"],
)
def test_el_propio_tenant_si_lee_lo_suyo(world, template):
    call, ids = world
    path = template.format(**ids)
    response = call("a", "GET", path)
    assert response.status_code == 200, f"tenant A GET {path} -> {response.status_code} {response.text[:300]}"


def test_recursos_de_a_intactos_tras_las_sondas(world):
    call, ids = world
    for method, template, _key, body in PROBES:
        call("b", method, template.format(**ids), body)
    with SessionLocal() as db:
        db.info["tenant_id"] = ids["tenant_a"]
        alert = db.get(ResearchAlert, ids["alert"])
        review = db.get(ResearchReview, ids["review"])
        knowledge = db.get(KnowledgeDocument, ids["knowledge"])
        assert alert is not None and alert.channels == ["in_app"]
        assert alert.status != "resolved"
        assert review is not None and review.status == "open"
        assert knowledge is not None


@pytest.mark.parametrize(
    ("method", "template", "key", "body"), PROBES, ids=[f"anon {m} {t}" for m, t, _, _ in PROBES]
)
def test_peticion_anonima_recibe_401(world, method, template, key, body):
    """Sin identidad firmada, ninguna ruta llega a los datos.

    Las lecturas dan 401; las escrituras las corta antes el guard CSRF (403).
    """
    _call, ids = world
    client = TestClient(main.app)
    response = client.request(method, template.format(**ids), json=body)
    expected = {401} if method == "GET" else {401, 403}
    assert response.status_code in expected, f"anon {method} -> {response.status_code} {response.text[:200]}"
