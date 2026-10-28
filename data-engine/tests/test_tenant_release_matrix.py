"""Canario de aislamiento entre tenants para release (matriz adversarial).

Dos tenants sinteticos (A y B). A es dueno de objetos sembrados directamente en
BD y por API. B intenta leer, modificar, borrar y accionar cada objeto de A por
id contra las rutas reales, con firma estricta. Reglas:

* nunca 2xx con datos de A para B (los ids ajenos deben ser 404/403/4xx);
* nunca 5xx (una ruta que revienta con un id ajeno es un hueco de aislamiento
  o un fallo de manejo de errores);
* tras el ataque, el objeto de A sigue intacto y visible para A;
* los listados de B no contienen ids ni marcadores de A.

Determinista: SQLite del test, sin red, sin datos que no siembre el propio test.
No cubre: DCA, publicacion/archivo de tesis, Cerebro/watchlist (tienen sus
propias pruebas) ni la rotacion de secretos (fuera de este canario).
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models.entities import (
    AlertRule,
    Company,
    CompanyKPI,
    Document,
    DocumentChunk,
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeDocument,
    KPIExtractionCandidate,
    ProcessingJob,
    ResearchAlert,
    ResearchReview,
    Tenant,
    WorkflowRun,
)
from tests.auth_helpers import auth_settings, signed_request

SECRET = "release-matrix-secret-with-at-least-32-chars"
MARKER = "TENANT-A-SECRET-MARKER"


@dataclass
class World:
    call: object
    ids: dict = field(default_factory=dict)


@pytest.fixture()
def world(monkeypatch):
    real = socket.create_connection

    def local_only(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise OSError(f"network disabled in release matrix: {host}")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", local_only)
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app.broker, "enqueue", lambda message, delay=None: message)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def call(tenant, method, path, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    # Crea ambos tenants por la via normal (primera peticion firmada).
    assert call("a", "GET", "/api/alerts/rules").status_code == 200
    assert call("b", "GET", "/api/alerts/rules").status_code == 200
    ensured = call("a", "POST", "/api/companies/ensure", {"ticker": "MSFT"})
    assert ensured.status_code in (200, 201), ensured.text

    with SessionLocal() as db:
        tenant_a = db.scalar(select(Tenant).where(Tenant.external_id == f"a-{suffix}"))
        assert tenant_a is not None
        db.info["tenant_id"] = tenant_a.id
        ids: dict = {}

        doc = Document(title=f"{MARKER} doc", source_type="note", metadata_={})
        db.add(doc)
        db.flush()
        db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text=MARKER, token_count=1))
        ids["source_document"] = doc.id

        kdoc = KnowledgeDocument(title=f"{MARKER} kdoc", document_type="note", metadata_={})
        db.add(kdoc)
        db.flush()
        db.add(KnowledgeChunk(knowledge_document_id=kdoc.id, chunk_index=0, content=MARKER))
        ids["knowledge_document"] = kdoc.id

        job = ProcessingJob(
            job_type="knowledge_principle_extraction", entity_type="knowledge_document",
            entity_id=kdoc.id, status="completed", result={"note": MARKER},
        )
        db.add(job)

        review = ResearchReview(
            review_type="manual", title=f"{MARKER} review", summary=MARKER, metadata_={},
        )
        db.add(review)

        alert = ResearchAlert(
            alert_type="manual", title=f"{MARKER} alert", message=MARKER,
            fingerprint=f"fp-{suffix}", channels=["in_app"], metadata_={},
        )
        db.add(alert)

        company = db.scalar(select(Company).where(Company.ticker == "MSFT"))
        assert company is not None
        rule = AlertRule(
            company_id=company.id, name=f"{MARKER} rule", rule_type="price_above",
            condition={"operator": ">", "value": 1}, target={}, metadata_={},
        )
        db.add(rule)

        kpi = CompanyKPI(
            company_id=company.id, metric_key="marker_kpi", display_name=MARKER, aliases=[],
            metadata_={},
        )
        db.add(kpi)
        db.flush()
        candidate = KPIExtractionCandidate(
            company_id=company.id, company_kpi_id=kpi.id, document_id=doc.id,
            document_chunk_id=db.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id)),
            metric_key="marker_kpi", raw_label=MARKER, raw_value="42", period="2024",
            source_locator={}, trace={},
        )
        db.add(candidate)
        principle = InvestmentPrinciple(
            knowledge_document_id=kdoc.id, principle=f"{MARKER} principle",
            principle_fingerprint=f"fp-{suffix}", category="risk",
            application_conditions=[], exceptions=[], applies_to_company_ids=[],
            exact_fragment=MARKER, metadata_={},
        )
        db.add(principle)

        run = WorkflowRun(workflow_name="GenerateThesisWorkflow", status="completed")
        db.add(run)
        db.commit()
        ids.update(kpi_candidate=candidate.id, principle=principle.id, alert_rule=rule.id, job=job.id, review=review.id, alert=alert.id, thesis_run=run.id)

    return World(call=call, ids=ids)


def _assert_denied(resp, what: str) -> None:
    assert resp.status_code != 500 and resp.status_code < 500, (
        f"{what}: crashed {resp.status_code} {resp.text[:300]}"
    )
    assert resp.status_code >= 400, (
        f"{what}: cross-tenant succeeded {resp.status_code} {resp.text[:300]}"
    )
    assert MARKER not in resp.text, f"{what}: leaked tenant A data"


# (clave del objeto, metodo, plantilla, cuerpo)
ATTACKS = [
    ("source_document", "GET", "/api/sources/documents/{id}/chunks", None),
    ("source_document", "POST", "/api/sources/documents/{id}/analyze", None),
    ("source_document", "POST", "/api/sources/documents/{id}/extract-kpis", None),
    ("knowledge_document", "GET", "/api/knowledge/documents/{id}", None),
    ("knowledge_document", "PATCH", "/api/knowledge/documents/{id}", {"ticker": "MSFT"}),
    ("knowledge_document", "GET", "/api/knowledge/documents/{id}/chunks", None),
    ("knowledge_document", "POST", "/api/knowledge/documents/{id}/extract-principles", None),
    ("knowledge_document", "DELETE", "/api/knowledge/documents/{id}", None),
    ("job", "GET", "/api/knowledge/jobs/{id}", None),
    ("review", "PATCH", "/api/reviews/{id}", {"status": "resolved", "resolution_notes": "hijack"}),
    ("alert", "GET", "/api/alerts/{id}/analysis", None),
    ("alert", "POST", "/api/alerts/{id}/action", {"action": "acknowledge", "actor": "b"}),
    ("alert", "POST", "/api/alerts/{id}/dispatch", None),
    ("alert", "PATCH", "/api/alerts/{id}/channels", {"channels": ["telegram"]}),
    ("alert_rule", "DELETE", "/api/alerts/rules/{id}", None),
    ("kpi_candidate", "POST", "/api/sources/kpi-candidates/{id}/action", {"action": "approve", "actor": "b"}),
    ("kpi_candidate", "POST", "/api/sources/kpi-candidates/{id}/action", {"action": "reject", "actor": "b"}),
    ("principle", "PUT", "/api/knowledge/principles/{id}", {"principle": "hijacked principle"}),
    ("principle", "POST", "/api/knowledge/principles/{id}/action", {"action": "approve", "actor": "b"}),
    ("principle", "POST", "/api/knowledge/principles/{id}/action", {"action": "reject", "actor": "b"}),
    ("thesis_run", "GET", "/api/thesis/jobs/{id}", None),
]


@pytest.mark.parametrize(
    ("key", "method", "template", "body"),
    ATTACKS,
    ids=[f"{m} {t}" for _, m, t, _ in ATTACKS],
)
def test_tenant_b_is_denied_on_foreign_object(world, key, method, template, body):
    if key not in world.ids:
        pytest.skip(f"no se pudo sembrar {key}")
    path = template.format(id=world.ids[key])
    _assert_denied(world.call("b", method, path, body), f"{method} {path}")
    # El propietario real sigue viendo su objeto (no lo borro/oculto el ataque).
    if method == "GET":
        assert world.call("a", method, path, body).status_code < 400


def test_foreign_attacks_leave_objects_of_a_intact(world):
    for key, method, template, body in ATTACKS:
        if key in world.ids:
            world.call("b", method, template.format(id=world.ids[key]), body)
    with SessionLocal() as db:
        tenant_id = db.scalar(select(KnowledgeDocument.tenant_id).where(
            KnowledgeDocument.id == world.ids["knowledge_document"]
        ).execution_options(include_all_tenants=True))
        db.info["tenant_id"] = tenant_id
        review = db.get(ResearchReview, world.ids["review"])
        alert = db.get(ResearchAlert, world.ids["alert"])
        assert db.get(KnowledgeDocument, world.ids["knowledge_document"]) is not None
        assert review is not None and review.status == "open"
        assert alert is not None and alert.status == "open" and alert.channels == ["in_app"]
        assert alert.acknowledged_by is None
        candidate = db.get(KPIExtractionCandidate, world.ids["kpi_candidate"])
        assert candidate is not None and candidate.status == "pending_approval"
        principle = db.get(InvestmentPrinciple, world.ids["principle"])
        assert principle is not None and principle.status == "proposed"
        assert MARKER in principle.principle and principle.approved_by is None
        if "alert_rule" in world.ids:
            rule = db.get(AlertRule, world.ids["alert_rule"])
            assert rule is not None and rule.active is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/alerts",
        "/api/alerts/rules",
        "/api/reviews",
        "/api/knowledge/documents",
        "/api/knowledge/jobs",
        "/api/sources/documents",
        "/api/memory/claims",
    ],
)
def test_lists_of_b_do_not_contain_a(world, path):
    resp = world.call("b", "GET", path, params={"status": ""} if path == "/api/reviews" else None)
    assert resp.status_code < 500, resp.text[:300]
    assert MARKER not in resp.text
    own = world.call("a", "GET", path, params={"status": ""} if path == "/api/reviews" else None)
    assert own.status_code < 500


@pytest.mark.parametrize(
    "tenant_header_attack",
    ["tenant-forged", "", "a-" + "0" * 8],
)
def test_forged_tenant_header_without_valid_signature_is_rejected(world, tenant_header_attack):
    """Cambiar la cabecera de tenant sin re-firmar no debe dar acceso a nada."""
    from tests.auth_helpers import bound_headers

    client = TestClient(main.app, raise_server_exceptions=False)
    headers = bound_headers(SECRET, "a-real", "u", method="GET", path="/api/reviews")
    headers["X-CavaAI-Tenant"] = tenant_header_attack
    resp = client.get("/api/reviews", headers=headers)
    assert resp.status_code in (401, 403), resp.text[:200]


def test_tenant_b_cannot_delete_holding_of_a(world):
    created = world.call("a", "POST", "/api/portfolio/transactions", {
        "ticker": "MSFT", "action": "buy", "quantity": 3, "price": 100,
        "trade_date": "2024-01-15", "currency": "USD",
    })
    assert created.status_code in (200, 201), created.text
    _assert_denied(world.call("b", "DELETE", "/api/portfolio/holdings/MSFT"), "holding delete")
    mine = world.call("a", "GET", "/api/portfolio/transactions")
    assert mine.status_code == 200 and "MSFT" in mine.text
    assert "MSFT" not in world.call("b", "GET", "/api/portfolio/transactions").text
