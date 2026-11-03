"""Barrido multiusuario: TODAS las rutas GET (y las mutaciones por id) como el tenant B.

El tenant A siembra datos de usuario por la API firmada (watchlist, cartera,
plan, screens, diario de decisiones, memoria, paper trading, supuestos) y
directamente en BD (documentos, alertas, reglas, revisiones, principios...),
todos con un marcador unico. Despues el tenant B:

1. llama a cada GET del OpenAPI (rellenando los parametros de ruta con los ids
   y el simbolo de A) y ninguna respuesta puede contener el marcador de A;
2. intenta PUT/PATCH/DELETE/POST contra cada ruta con id de un objeto de A:
   nunca 2xx con el marcador, y al final los objetos de A siguen intactos y
   visibles solo para A.

Complementa test_cross_tenant_probes / test_tenant_release_matrix (sondas
recurso a recurso): este barrido no depende de una lista mantenida a mano, asi
que una ruta GET nueva queda cubierta sin tocar el test.
"""

from __future__ import annotations

import json
import os
import re
import socket
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
    Document,
    DocumentChunk,
    KnowledgeChunk,
    KnowledgeDocument,
    ProcessingJob,
    ResearchAlert,
    ResearchReview,
    Tenant,
)
from tests.auth_helpers import auth_settings, signed_request

SECRET = "multiuser-sweep-secret-with-at-least-32-chars"
MARKER = "MULTIUSER-A-PRIVATE-MARKER"
SYMBOL = "MSFT"

# GET que no leen datos de usuario y son lentos o salen a red aunque la red este
# cortada (no aportan al aislamiento): se saltan para mantener el barrido acotado.
SKIP_GET = {
    "/api/csrf-token",
}

PARAM_DEFAULTS = {
    "ticker": SYMBOL,
    "symbol": SYMBOL,
    "year": "2025",
    "fiscal_year": "2025",
    "event_type": "dca_levels",
    "slug": "berkshire-hathaway",
    "name": "GenerateThesisWorkflow",
    "filename": "feed.ics",
    "cik": "0001067983",
    "norad_cat_id": "1",
    "theme_id": "1",
    "node_id": "1",
    "source_id": "1",
    "event_id": "1",
    "thesis_version_id": "1",
    "action_id": "1",
    "portfolio_id": "1",
    "challenge_id": "1",
}

QUERY_DEFAULTS = {
    "ticker": SYMBOL,
    "symbol": SYMBOL,
    "symbols": SYMBOL,
    "tickers": SYMBOL,
    "q": SYMBOL,
    "query": SYMBOL,
    "year": "2025",
    "fiscal_year": "2025",
}

# nombre del parametro de ruta -> clave del objeto sembrado por A
ID_PARAMS = {
    "rule_id": "alert_rule",
    "alert_id": "alert",
    "document_id": "knowledge_document",
    "job_id": "job",
    "review_id": "review",
    "claim_id": "claim",
    "transaction_id": "transaction",
    "contribution_id": "contribution",
    "screen_id": "screen",
    "proposal_id": "proposal",
    "entry_id": "journal_entry",
    "run_id": "job",
}


def _no_network(monkeypatch) -> None:
    real = socket.create_connection

    def local_only(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise OSError(f"network disabled in multiuser sweep: {host}")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", local_only)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "testserver")


def _first_id(payload):
    if isinstance(payload, dict):
        for key in ("id", "transaction_id", "entry_id", "proposal_id", "screen_id"):
            if isinstance(payload.get(key), int):
                return payload[key]
        for value in payload.values():
            found = _first_id(value)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _first_id(item)
            if found is not None:
                return found
    return None


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
    client = TestClient(main.app, raise_server_exceptions=False)

    def call(tenant, method, path, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    assert call("a", "GET", "/api/alerts/rules").status_code == 200
    assert call("b", "GET", "/api/alerts/rules").status_code == 200
    ensured = call("a", "POST", "/api/companies/ensure", {"ticker": SYMBOL})
    assert ensured.status_code in (200, 201), ensured.text

    ids: dict = {}
    seeded: dict = {}

    def seed(key, method, path, body):
        resp = call("a", method, path, body)
        seeded[key] = resp.status_code
        if resp.status_code >= 300:
            seeded[key + "_error"] = resp.text[:300]
        if resp.status_code < 300:
            try:
                found = _first_id(resp.json())
            except ValueError:
                found = None
            if found is not None:
                ids[key] = found
        return resp

    seed("watchlist", "POST", "/api/watchlist", {"symbol": SYMBOL, "company": f"{MARKER} co"})
    seed("transaction", "POST", "/api/portfolio/transactions", {
        "ticker": SYMBOL, "action": "buy", "quantity": 3, "price": 100,
        "trade_date": "2025-01-02", "currency": "USD", "notes": f"{MARKER} trade",
    })
    seed("plan", "PUT", "/api/plan", {"monthly_contribution": 500, "start_date": "2025-01-01"})
    seed("contribution", "POST", "/api/plan/contributions", {
        "date": "2025-01-03", "amount": 123, "currency": "EUR", "note": f"{MARKER} plan",
    })
    seed("screen", "POST", "/api/screeners/screens", {
        "name": f"{MARKER} screen", "criteria": [{"left": "pe", "operator": "<", "right": "20"}],
    })
    seed("journal_entry", "POST", f"/api/companies/{SYMBOL}/decision-journal", {
        "decision": "buy", "rationale": f"{MARKER} rationale",
    })
    seed("claim", "POST", "/api/memory/claims", {"statement": f"{MARKER} claim", "ticker": SYMBOL})
    seed("memory_item", "POST", "/api/memory/memory-items", {"content": f"{MARKER} memory", "ticker": SYMBOL})
    seed("research_session", "POST", "/api/memory/research-sessions", {
        "title": f"{MARKER} session", "question": f"{MARKER} question", "ticker": SYMBOL,
    })
    seed("proposal", "POST", "/api/paper-trading/proposals", {
        "proposal_key": f"k-{suffix}", "ticker": SYMBOL, "direction": "long", "horizon": "short",
        "thesis": f"{MARKER} paper", "conviction": 0.7, "proposed_entry": 100, "stop": 90,
        "target": 130, "quantity": 1, "inference_basis": f"{MARKER} basis",
    })

    with SessionLocal() as db:
        tenant_a = db.scalar(select(Tenant).where(Tenant.external_id == f"a-{suffix}"))
        assert tenant_a is not None
        db.info["tenant_id"] = tenant_a.id
        doc = Document(title=f"{MARKER} doc", source_type="note", metadata_={})
        db.add(doc)
        db.flush()
        db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text=MARKER, token_count=1))
        kdoc = KnowledgeDocument(title=f"{MARKER} kdoc", document_type="note", metadata_={})
        db.add(kdoc)
        db.flush()
        db.add(KnowledgeChunk(knowledge_document_id=kdoc.id, chunk_index=0, content=MARKER))
        job = ProcessingJob(
            job_type="knowledge_principle_extraction", entity_type="knowledge_document",
            entity_id=kdoc.id, status="completed", result={"note": MARKER},
        )
        review = ResearchReview(review_type="manual", title=f"{MARKER} review", summary=MARKER, metadata_={})
        alert = ResearchAlert(
            alert_type="manual", title=f"{MARKER} alert", message=MARKER,
            fingerprint=f"fp-{suffix}", channels=["in_app"], metadata_={},
        )
        company = db.scalar(select(Company).where(Company.ticker == SYMBOL))
        assert company is not None
        rule = AlertRule(
            company_id=company.id, name=f"{MARKER} rule", rule_type="price_above",
            condition={"operator": ">", "value": 1}, target={}, metadata_={},
        )
        db.add_all([job, review, alert, rule])
        db.commit()
        ids.update(
            knowledge_document=kdoc.id, source_document=doc.id, job=job.id,
            review=review.id, alert=alert.id, alert_rule=rule.id,
        )

    return call, ids, seeded


def _get_operations():
    out = []
    for path, item in main.app.openapi()["paths"].items():
        for method, op in item.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            out.append((method.upper(), path, op))
    return out


def _fill(path: str, ids: dict) -> str | None:
    def repl(match):
        name = match.group(1)
        if name in ID_PARAMS:
            value = ids.get(ID_PARAMS[name])
            return str(value) if value is not None else "999999"
        return PARAM_DEFAULTS.get(name, "1")

    return re.sub(r"\{([^}]+)\}", repl, path)


def _query(op) -> dict:
    params = {}
    for param in op.get("parameters", []):
        if param.get("in") == "query" and param.get("required"):
            params[param["name"]] = QUERY_DEFAULTS.get(param["name"], "1")
    return params


def test_tenant_b_never_sees_tenant_a_marker_on_any_get(world):
    call, ids, seeded = world
    # La siembra principal tiene que haber funcionado; si no, el barrido no prueba nada.
    for key in ("watchlist", "transaction", "plan", "contribution", "screen", "journal_entry", "claim", "proposal"):
        assert seeded.get(key, 999) < 300, f"seed {key} failed: {seeded}"

    leaks, crashes, statuses = [], [], {}
    for method, path, op in _get_operations():
        if method != "GET" or path in SKIP_GET or not path.startswith("/api/"):
            continue
        url = _fill(path, ids)
        resp = call("b", "GET", url, params=_query(op))
        statuses[path] = resp.status_code
        if MARKER in resp.text:
            leaks.append(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 500:
            crashes.append(f"GET {url} -> {resp.status_code}")

    report = os.environ.get("MULTIUSER_SWEEP_REPORT")
    if report:
        with open(report, "w") as fh:
            json.dump({"seeded": seeded, "ids": ids, "get_statuses": statuses, "crashes": crashes, "leaks": leaks}, fh, indent=1)
    assert len(statuses) > 150, f"only {len(statuses)} GET routes swept"
    assert not leaks, "tenant A data visible to tenant B:\n" + "\n".join(leaks)


def test_tenant_b_cannot_mutate_tenant_a_objects_by_id(world):
    call, ids, _seeded = world
    attempts, wins = 0, []
    for method, path, _op in _get_operations():
        if method == "GET" or not path.startswith("/api/"):
            continue
        names = re.findall(r"\{([^}]+)\}", path)
        if not any(n in ID_PARAMS and ids.get(ID_PARAMS[n]) is not None for n in names):
            continue
        url = _fill(path, ids)
        resp = call("b", method, url, json_body={} if method != "DELETE" else None)
        attempts += 1
        if resp.status_code < 300 and MARKER in resp.text:
            wins.append(f"{method} {url} -> {resp.status_code}: {resp.text[:200]}")
        assert resp.status_code < 500, f"{method} {url} crashed with tenant B: {resp.status_code} {resp.text[:200]}"
    assert attempts >= 15, f"only {attempts} mutation routes attacked"
    assert not wins, "tenant B mutated tenant A objects:\n" + "\n".join(wins)

    # Lo de A sigue ahi y A lo ve.
    for path in ("/api/watchlist", "/api/portfolio/transactions", "/api/screeners/screens", "/api/plan/contributions"):
        resp = call("a", "GET", path)
        assert resp.status_code == 200, f"A {path}: {resp.status_code}"
        assert MARKER in resp.text, f"A lost its own data at {path}"
        assert MARKER not in call("b", "GET", path).text
