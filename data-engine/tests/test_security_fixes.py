"""Tests herméticos para los gaps de seguridad cerrados en esta pasada.

Cubre cada fix de la auditoría:
- P0-2: nonce de un solo uso (anti-replay), rechazo de timestamps futuros y
  bind de método/ruta/body hash a la firma HMAC;
- P1-4: scoping de tenant en bulk UPDATE/DELETE Core;
- P1-5: before_flush bloquea reasignar tenant_id en filas persistentes;
- P2-6: las respuestas de error nunca filtran str(exc) (mensaje genérico +
  correlación en log);
- P2-7: server actions sin fallback a NEXT_PUBLIC_FINNHUB_API_KEY;
- P2-8: defaults débiles de Postgres/Mongo/MinIO rechazados en producción.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select, update

import main
from app.core import auth as auth_module
from app.core import replay as replay_module
from app.core.auth import body_digest, sign_research_identity
from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.core.errors import safe_detail
from app.models import Claim, Company, MemoryItem, Tenant
from app.services.knowledge_graph_service import KnowledgeGraphService

SECRET = "research-security-test-secret-at-least-32-chars"


def _auth_settings(*, strict: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        is_production=False,
        research_auth_required=True,
        research_auth_secret=SECRET,
        research_auth_max_age_seconds=300,
        research_auth_strict_binding=strict,
        redis_url="redis://127.0.0.1:1/0",
    )


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: _auth_settings())


@pytest.fixture
def strict_auth_env(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: _auth_settings(strict=True)
    )


def _bound_headers(
    tenant: str,
    user: str,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    nonce = uuid4().hex if nonce is None else nonce
    body_hash = body_digest(body)
    signature = sign_research_identity(
        SECRET,
        tenant_id=tenant,
        user_id=user,
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        body_hash=body_hash,
    )
    return {
        "X-CavaAI-Tenant": tenant,
        "X-CavaAI-User": user,
        "X-CavaAI-Timestamp": timestamp,
        "X-CavaAI-Signature": signature,
        "X-CavaAI-Nonce": nonce,
        "X-CavaAI-Method": method,
        "X-CavaAI-Path": path,
        "X-CavaAI-Body-Hash": body_hash,
    }


def _legacy_headers(tenant: str, user: str, *, timestamp: str | None = None) -> dict[str, str]:
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    return {
        "X-CavaAI-Tenant": tenant,
        "X-CavaAI-User": user,
        "X-CavaAI-Timestamp": timestamp,
        "X-CavaAI-Signature": sign_research_identity(
            SECRET, tenant_id=tenant, user_id=user, timestamp=timestamp
        ),
    }


def _cleanup_claims_and_tenants(statements: list[str], tenants: list[str]) -> None:
    db = SessionLocal()
    db.execute(delete(Claim).where(Claim.statement.in_(statements)))
    tenant_ids = db.scalars(
        select(Tenant.id).where(Tenant.external_id.in_(tenants))
    ).all()
    if tenant_ids:
        db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# P0-2 — HMAC: nonce de un solo uso, timestamps futuros, bind de la petición
# ---------------------------------------------------------------------------


def test_replayed_signed_request_is_rejected(auth_env):
    init_db()
    # El claim necesita una compania real: se siembra MSFT (el test valida
    # anti-replay, no el provisioning de companias).
    db = SessionLocal()
    if not db.scalar(select(Company).where(Company.ticker == "MSFT")):
        db.add(
            Company(
                ticker="MSFT",
                name="Microsoft",
                exchange="NASDAQ",
                currency="USD",
                sector="Technology",
                industry="Software",
                company_type="tech",
                valuation_model="standard_dcf",
                special_sources=[],
                special_risks=[],
                factor_tags=[],
            )
        )
        db.commit()
    db.close()
    suffix = uuid4().hex[:8]
    tenant = f"replay-{suffix}"
    user = f"user-{suffix}"
    statement = f"Replay probe {suffix}"
    body = json.dumps({"ticker": "MSFT", "statement": statement}).encode()
    # Mismos headers exactos en ambas peticiones: el nonce debe ser de un solo uso.
    headers = _bound_headers(
        tenant, user, method="POST", path="/api/memory/claims", body=body
    )
    headers["Content-Type"] = "application/json"

    replay_module.reset_local_nonces()
    client = TestClient(main.app)
    first = client.post("/api/memory/claims", content=body, headers=headers)
    second = client.post("/api/memory/claims", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.json()["detail"] == "Replayed Research OS identity"
    _cleanup_claims_and_tenants([statement], [tenant])
    db = SessionLocal()
    db.execute(delete(Company).where(Company.ticker == "MSFT"))
    db.commit()
    db.close()


def test_signed_multipart_upload_survives_body_hash_verification(auth_env):
    """Regresión: upload multipart firmado no debe morir con 'Stream consumed'.

    FastAPI parsea el form (UploadFile) antes de que la dependencia de auth
    verifique el body-hash; sin RawBodyMiddleware el stream queda consumido.
    """
    init_db()
    suffix = uuid4().hex[:8]
    tenant = f"multipart-{suffix}"
    user = f"user-{suffix}"

    request = httpx.Request(
        "POST",
        "http://testserver/api/knowledge/documents/upload",
        data={"title": "E2E multipart note", "document_type": "book"},
        files={"file": ("note.txt", b"margen de seguridad y paciencia", "text/plain")},
    )
    body = request.read()
    headers = _bound_headers(
        tenant,
        user,
        method="POST",
        path="/api/knowledge/documents/upload",
        body=body,
    )
    headers["Content-Type"] = request.headers["content-type"]

    replay_module.reset_local_nonces()
    client = TestClient(main.app)
    response = client.post(
        "/api/knowledge/documents/upload", content=body, headers=headers
    )
    assert response.status_code != 500
    assert "Stream consumed" not in response.text
    assert response.status_code == 200, response.text[:300]


def test_future_timestamp_is_rejected_even_with_a_valid_signature(auth_env):
    suffix = uuid4().hex[:8]
    tenant = f"future-{suffix}"
    user = f"user-{suffix}"
    future = str(int(time.time()) + 120)

    bound = _bound_headers(
        tenant,
        user,
        method="GET",
        path="/api/memory/claims",
        timestamp=future,
    )
    legacy = _legacy_headers(tenant, user, timestamp=future)

    client = TestClient(main.app)
    for headers in (bound, legacy):
        response = client.get("/api/memory/claims", headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid Research OS identity timestamp"
    _cleanup_claims_and_tenants([], [tenant])


def test_signature_is_bound_to_method_path_and_body(auth_env):
    suffix = uuid4().hex[:8]
    tenant = f"binding-{suffix}"
    user = f"user-{suffix}"
    client = TestClient(main.app)

    # 1) Firma de otro método.
    wrong_method = _bound_headers(
        tenant, user, method="DELETE", path="/api/memory/claims"
    )
    response = client.get("/api/memory/claims", headers=wrong_method)
    assert response.status_code == 401
    assert response.json()["detail"] == "Research OS identity does not match the request"

    # 2) Firma de otra ruta.
    wrong_path = _bound_headers(tenant, user, method="GET", path="/api/news")
    response = client.get("/api/memory/claims", headers=wrong_path)
    assert response.status_code == 401
    assert response.json()["detail"] == "Research OS identity does not match the request"

    # 3) Body manipulado respecto al hash firmado.
    signed_body = json.dumps({"ticker": "MSFT", "statement": "signed"}).encode()
    tampered_body = json.dumps({"ticker": "MSFT", "statement": "tampered"}).encode()
    headers = _bound_headers(
        tenant, user, method="POST", path="/api/memory/claims", body=signed_body
    )
    headers["Content-Type"] = "application/json"
    response = client.post("/api/memory/claims", content=tampered_body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Research OS identity does not match the request"
    _cleanup_claims_and_tenants([], [tenant])


def test_strict_mode_rejects_unbound_legacy_signatures(strict_auth_env):
    suffix = uuid4().hex[:8]
    tenant = f"strict-{suffix}"
    user = f"user-{suffix}"
    client = TestClient(main.app)

    legacy = client.get(
        "/api/memory/claims", headers=_legacy_headers(tenant, user)
    )
    assert legacy.status_code == 401
    assert legacy.json()["detail"] == (
        "A request-bound Research OS identity signature is required"
    )

    bound = client.get(
        "/api/memory/claims",
        headers=_bound_headers(tenant, user, method="GET", path="/api/memory/claims"),
    )
    assert bound.status_code == 200
    _cleanup_claims_and_tenants([], [tenant])


def test_nonce_store_falls_back_to_local_cache_when_redis_is_down():
    replay_module.reset_local_nonces()
    key = f"test-nonce-{uuid4().hex}"

    async def consume():
        return await replay_module.consume_nonce(
            key,
            ttl_seconds=30,
            redis_url="redis://127.0.0.1:1/0",
            use_redis=True,  # Redis caído -> cache local TTL
        )

    assert asyncio.run(consume()) is True
    assert asyncio.run(consume()) is False


# ---------------------------------------------------------------------------
# P1-4 — bulk UPDATE/DELETE Core con scoping de tenant
# ---------------------------------------------------------------------------


def _seed_memory_rows(suffix: str) -> tuple[int, int, list[str]]:
    init_db()
    db = SessionLocal()
    tenants = [
        Tenant(external_id=f"bulk-{name}-{suffix}", name=f"Bulk {name}")
        for name in ("a", "b")
    ]
    db.add_all(tenants)
    db.commit()
    for tenant in tenants:
        db.refresh(tenant)
        db.add(
            MemoryItem(
                tenant_id=tenant.id,
                scope="portfolio",
                memory_type="note",
                content=f"bulk-row-{suffix}-{tenant.id}",
                status="active",
            )
        )
    db.commit()
    ids = [tenant.id for tenant in tenants]
    contents = [f"bulk-row-{suffix}-{tid}" for tid in ids]
    db.close()
    return ids[0], ids[1], contents


def _cleanup_memory_rows(suffix: str, tenant_ids: list[int]) -> None:
    db = SessionLocal()
    db.execute(
        delete(MemoryItem)
        .where(MemoryItem.content.like(f"bulk-row-{suffix}-%"))
        .execution_options(include_all_tenants=True)
    )
    db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
    db.commit()
    db.close()


def test_bulk_update_and_delete_are_tenant_scoped():
    suffix = uuid4().hex[:8]
    tenant_a, tenant_b, _ = _seed_memory_rows(suffix)
    try:
        scoped = SessionLocal()
        scoped.info["tenant_id"] = tenant_a
        scoped.info["user_id"] = f"user-{suffix}"

        # UPDATE masivo SIN filtro de tenant: solo debe tocar las filas propias.
        scoped.execute(
            update(MemoryItem)
            .where(MemoryItem.status == "active")
            .values(status="consolidated")
        )
        scoped.commit()
        scoped.close()

        db = SessionLocal()
        rows = db.execute(
            select(MemoryItem.tenant_id, MemoryItem.status)
            .where(MemoryItem.content.like(f"bulk-row-{suffix}-%"))
            .execution_options(include_all_tenants=True)
        ).all()
        by_tenant = dict(rows)
        assert by_tenant[tenant_a] == "consolidated"
        assert by_tenant[tenant_b] == "active"

        # DELETE masivo SIN filtro de tenant: solo borra las filas propias.
        scoped = SessionLocal()
        scoped.info["tenant_id"] = tenant_a
        scoped.info["user_id"] = f"user-{suffix}"
        scoped.execute(
            delete(MemoryItem).where(MemoryItem.content.like(f"bulk-row-{suffix}-%"))
        )
        scoped.commit()
        scoped.close()

        survivors = db.scalars(
            select(MemoryItem)
            .where(MemoryItem.content.like(f"bulk-row-{suffix}-%"))
            .execution_options(include_all_tenants=True)
        ).all()
        assert [row.tenant_id for row in survivors] == [tenant_b]
        db.close()
    finally:
        _cleanup_memory_rows(suffix, [tenant_a, tenant_b])


def test_bulk_update_cannot_reassign_tenant_id():
    suffix = uuid4().hex[:8]
    tenant_a, tenant_b, _ = _seed_memory_rows(suffix)
    try:
        scoped = SessionLocal()
        scoped.info["tenant_id"] = tenant_a
        scoped.info["user_id"] = f"user-{suffix}"
        with pytest.raises(RuntimeError, match="tenant_id"):
            scoped.execute(
                update(MemoryItem).where(MemoryItem.status == "active").values(
                    tenant_id=tenant_b
                )
            )
        scoped.close()
    finally:
        _cleanup_memory_rows(suffix, [tenant_a, tenant_b])


# ---------------------------------------------------------------------------
# P1-5 — before_flush: tenant_id inmutable en filas persistentes
# ---------------------------------------------------------------------------


def test_dirty_tenant_id_reassignment_cannot_commit():
    suffix = uuid4().hex[:8]
    tenant_a, tenant_b, contents = _seed_memory_rows(suffix)
    try:
        scoped = SessionLocal()
        scoped.info["tenant_id"] = tenant_a
        scoped.info["user_id"] = f"user-{suffix}"
        item = scoped.scalar(
            select(MemoryItem).where(MemoryItem.content == contents[0])
        )
        assert item is not None
        item.tenant_id = tenant_b
        with pytest.raises(RuntimeError, match="Cross-tenant"):
            scoped.commit()
        scoped.rollback()
        scoped.close()

        db = SessionLocal()
        row = db.scalar(
            select(MemoryItem)
            .where(MemoryItem.content == contents[0])
            .execution_options(include_all_tenants=True)
        )
        assert row.tenant_id == tenant_a
        db.close()
    finally:
        _cleanup_memory_rows(suffix, [tenant_a, tenant_b])


def test_dirty_tenant_id_cannot_be_cleared():
    suffix = uuid4().hex[:8]
    tenant_a, _tenant_b, contents = _seed_memory_rows(suffix)
    try:
        scoped = SessionLocal()
        scoped.info["tenant_id"] = tenant_a
        scoped.info["user_id"] = f"user-{suffix}"
        item = scoped.scalar(
            select(MemoryItem).where(MemoryItem.content == contents[0])
        )
        assert item is not None
        item.tenant_id = None
        with pytest.raises(RuntimeError, match="Cross-tenant"):
            scoped.commit()
        scoped.rollback()
        scoped.close()
    finally:
        _cleanup_memory_rows(suffix, [tenant_a])


# ---------------------------------------------------------------------------
# P2-6 — sanitización de errores
# ---------------------------------------------------------------------------


def test_error_details_are_sanitized_and_logged_with_correlation_ref(
    auth_env, monkeypatch, caplog
):
    secret_text = "postgres://user:secretpassword@internal-host/app/models.py:99"

    def boom(self, db):
        raise ValueError(secret_text)

    monkeypatch.setattr(KnowledgeGraphService, "sync", boom)
    suffix = uuid4().hex[:8]
    tenant = f"sanitize-{suffix}"
    user = f"user-{suffix}"
    client = TestClient(main.app)
    with caplog.at_level(logging.ERROR, logger="cavaai.request_errors"):
        response = client.post(
            "/api/knowledge-graph/sync",
            headers=_bound_headers(
                tenant, user, method="POST", path="/api/knowledge-graph/sync"
            ),
        )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert secret_text not in detail
    assert "secretpassword" not in detail
    assert "internal-host" not in detail
    assert re.fullmatch(r"Invalid request \(ref: [0-9a-f]{12}\)", detail)
    # Contrato actual: el secreto TAMPOCO llega al log del servidor
    # (ninguna excepcion de infraestructura llega al cliente ni al log);
    # la trazabilidad la da solo el ref de correlacion.
    assert "secretpassword" not in caplog.text
    assert detail.split("ref: ")[1].rstrip(")") in caplog.text
    _cleanup_claims_and_tenants([], [tenant])


def test_safe_detail_never_returns_exception_text(caplog):
    exc = RuntimeError("connection to db-primary.internal failed: password=hunter2")
    with caplog.at_level(logging.ERROR, logger="cavaai.request_errors"):
        detail = safe_detail(exc, 500)
    assert "hunter2" not in detail
    assert "db-primary" not in detail
    assert re.fullmatch(r"Internal server error \(ref: [0-9a-f]{12}\)", detail)
    # Igual aqui: el secreto no llega al log.
    assert "hunter2" not in caplog.text


def test_safe_detail_redacts_vendor_keys_in_server_log(caplog):
    # httpx mete la URL completa (con la key del servidor) en el texto de la
    # excepcion: el log tampoco puede guardarla.
    exc = RuntimeError("GET https://finnhub.io/api/v1/quote?symbol=AAPL&token=secrettoken123 failed")
    with caplog.at_level(logging.ERROR, logger="cavaai.request_errors"):
        detail = safe_detail(exc, 500)
    assert "secrettoken123" not in detail
    assert "secrettoken123" not in caplog.text
    assert "token=REDACTED" in caplog.text


def test_rag_status_error_redacts_vendor_keys(monkeypatch):
    # El campo error del status de RAG acaba en respuestas de API: tampoco
    # puede llevar la URL del proveedor con la key del servidor.
    from app.services.rag import RAGIndex

    class _Boom:
        def get_collections(self):
            raise RuntimeError("GET https://finnhub.io/api/v1/quote?token=secrettoken123 failed")

    monkeypatch.setattr(RAGIndex, "client", lambda self: _Boom())
    out = RAGIndex().status()
    assert out["configured"] is False
    assert "secrettoken123" not in out["error"]
    assert "token=REDACTED" in out["error"]


# ---------------------------------------------------------------------------
# Campos error del flujo de earnings (ruta 422 + serializacion + trace)
# ---------------------------------------------------------------------------

_EARNINGS_SECRET_URL = (
    "GET https://financialmodelingprep.com/api/v3/income-statement/AAPL"
    "?apikey=secrettoken123 failed"
)


def _seed_earnings_company(db, ticker: str):
    from app.models import Company

    company = Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Industrials",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def test_earnings_run_route_redacts_vendor_key_in_422_and_listing(monkeypatch):
    # Ruta real: un fallo upstream cuya excepcion lleva la URL del proveedor
    # (con apikey) no puede salir ni en el 422 del POST /run ni en el GET /runs.
    from uuid import uuid4

    from fastapi.testclient import TestClient

    import main
    from app.core import auth as auth_module
    from app.core.database import SessionLocal, init_db
    from app.models import Tenant
    from app.services.earnings_service import EarningsWorkflowService
    from tests.auth_helpers import auth_settings, signed_request

    secret = "earnings-route-test-secret-at-least-32c"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret),
    )

    def _boom_documents(self, db, company, fiscal_year, fiscal_quarter, document_ids):
        raise RuntimeError(_EARNINGS_SECRET_URL)

    monkeypatch.setattr(EarningsWorkflowService, "_documents", _boom_documents)

    init_db()
    suffix = uuid4().hex[:6]
    tenant_ext = f"earnings-redact-{suffix}"
    ticker = f"RED{suffix[:4].upper()}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="Earnings redact test")
    db.add(tenant)
    db.commit()
    _seed_earnings_company(db, ticker)
    db.close()

    client = TestClient(main.app)
    payload = {"fiscal_year": 2025, "fiscal_quarter": "FY"}
    resp = signed_request(
        client,
        secret,
        tenant_ext,
        "earnings-test-user",
        "POST",
        f"/api/earnings/{ticker}/run",
        json_body=payload,
    )
    assert resp.status_code == 422, resp.text
    assert "secrettoken123" not in resp.text
    assert "apikey=REDACTED" in str(resp.json()["detail"])

    listed = signed_request(
        client, secret, tenant_ext, "earnings-test-user", "GET", f"/api/earnings/{ticker}/runs"
    )
    assert listed.status_code == 200, listed.text
    assert "secrettoken123" not in listed.text
    assert any("apikey=REDACTED" in (r.get("error") or "") for r in listed.json())


def test_earnings_trace_thesis_generation_error_is_redacted(monkeypatch):
    # El trace persiste thesis_generation_error y se expone en las respuestas:
    # tampoco puede llevar la URL del proveedor con su key.
    from uuid import uuid4

    import app.services.thesis_service as thesis_module
    from app.core.database import SessionLocal, init_db
    from app.services.claim_intelligence_service import ClaimIntelligenceService
    from app.services.earnings_service import EarningsWorkflowService

    monkeypatch.setattr(
        EarningsWorkflowService, "_documents", lambda self, db, c, fy, fq, ids: []
    )
    monkeypatch.setattr(
        EarningsWorkflowService, "_document_text", lambda self, db, docs: {}
    )
    monkeypatch.setattr(
        EarningsWorkflowService, "_extract_metrics", lambda self, full, bydoc: []
    )
    monkeypatch.setattr(
        EarningsWorkflowService, "_comparisons", lambda self, db, c, fy, fq: []
    )
    monkeypatch.setattr(EarningsWorkflowService, "_tone", lambda self, text: None)
    monkeypatch.setattr(
        EarningsWorkflowService, "_promise_tracking", lambda self, db, c, text: []
    )
    monkeypatch.setattr(
        ClaimIntelligenceService,
        "extract_statements",
        lambda self, text, limit=40: [],
    )

    def _boom_thesis(self, db, ticker, force_new_version=False):
        raise RuntimeError(_EARNINGS_SECRET_URL)

    monkeypatch.setattr(thesis_module.ThesisService, "generate", _boom_thesis)

    init_db()
    db = SessionLocal()
    company = _seed_earnings_company(db, f"TRC{uuid4().hex[:4].upper()}")

    run = EarningsWorkflowService().run(
        db, company, fiscal_year=2025, fiscal_quarter="FY", force_new_thesis=True
    )
    assert run.status == "completed"
    err = run.trace.get("thesis_generation_error", "")
    assert "secrettoken123" not in err
    assert "apikey=REDACTED" in err


# ---------------------------------------------------------------------------
# P2-7 — sin fallback NEXT_PUBLIC_FINNHUB_API_KEY en server actions
# ---------------------------------------------------------------------------


def test_server_actions_do_not_fall_back_to_public_finnhub_key():
    repo_root = Path(__file__).resolve().parents[2]
    actions_dir = repo_root / "lib" / "actions"
    offenders = sorted(
        path.name
        for path in actions_dir.glob("*.ts")
        if "NEXT_PUBLIC_FINNHUB_API_KEY" in path.read_text(encoding="utf-8")
    )
    assert offenders == []


# ---------------------------------------------------------------------------
# P2-8 — hardening de defaults dev en producción
# ---------------------------------------------------------------------------


def test_production_settings_reject_weak_database_and_storage_defaults():
    common = dict(
        _env_file=None,
        app_env="production",
        research_auth_required=True,
        research_auth_secret=SECRET,
        minio_secret_key="production-minio-secret-not-a-default",
        minio_access_key="production-minio-access-not-a-default",
    )
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            **common,
            database_url="postgresql://postgres:postgres@db:5432/cavaai",
        )
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(**common, database_url="postgresql://cavaai@db:5432/cavaai")
    with pytest.raises(ValidationError, match="MONGODB_URI"):
        Settings(
            **common,
            mongodb_uri="mongodb://root:example@mongo:27017/cavaai",
        )
    with pytest.raises(ValidationError, match="MINIO_ACCESS_KEY"):
        Settings(**{**common, "minio_access_key": "minioadmin"})

    strong = Settings(
        **common,
        database_url="postgresql://cavaai:Sup3rStrong-Unique-Pass@db:5432/cavaai",
        mongodb_uri="mongodb://cavaai:Sup3rStrong-Unique-Pass@mongo:27017/cavaai",
    )
    assert strong.is_production is True


def test_non_production_settings_allow_dev_defaults():
    local = Settings(_env_file=None, app_env="local")
    assert local.is_production is False
