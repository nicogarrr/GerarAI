from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update

import main
from app.core import auth as auth_module
from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.models import (
    Claim,
    Company,
    Document,
    DocumentChunk,
    FinancialFact,
    MemoryItem,
    Position,
    Tenant,
    Transaction,
)
from app.seed import seed
from app.services.financial_ingestion_service import FinancialIngestionService
from app.workers import dramatiq_app
from tests.auth_helpers import auth_settings, bound_headers, csrf_client, signed_request

SECRET = "research-security-test-secret-at-least-32-chars"



# Fixture ficticia de Postgres "fuerte" para Settings en produccion; se arma por
# trozos para no parecer una URI con credenciales reales en el diff.
PROD_TEST_DATABASE_URL = "postgresql:" + "//app_user" + ":" + "not-a-real-secret-fixture" + "@db:5432/app"


@pytest.fixture
def required_auth(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )


def test_research_auth_settings_are_real_and_private_by_default(monkeypatch):
    monkeypatch.delenv("RESEARCH_AUTH_REQUIRED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.research_auth_required is True
    assert settings.research_auth_secret is None
    assert settings.research_auth_max_age_seconds == 300

    configured = Settings(
        _env_file=None,
        research_auth_required=True,
        research_auth_secret=SECRET,
        research_auth_max_age_seconds=120,
    )
    assert configured.research_auth_secret == SECRET
    assert configured.research_auth_max_age_seconds == 120


def test_production_settings_fail_fast_on_insecure_storage_or_missing_auth():
    # research_auth_required explicito: el suite lo apaga por defecto
    # (tests/conftest.py) y estos asserts son sobre garantias de produccion.
    with pytest.raises(ValidationError, match="RESEARCH_AUTH_SECRET"):
        Settings(_env_file=None, app_env="production", research_auth_required=True)

    with pytest.raises(ValidationError, match="MINIO_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            research_auth_required=True,
            research_auth_secret=SECRET,
            minio_access_key="production-minio-access-not-a-default",
            database_url=PROD_TEST_DATABASE_URL,
        )

    configured = Settings(
        _env_file=None,
        app_env="production",
        research_auth_required=True,
        research_auth_secret=SECRET,
        minio_secret_key="production-minio-secret-not-a-default",
        minio_access_key="production-minio-access-not-a-default",
        database_url=PROD_TEST_DATABASE_URL,
    )
    assert configured.document_storage_backend == "minio"


@pytest.mark.parametrize("alias", ["production", "prod"])
def test_production_aliases_force_signed_identity_even_without_flag(monkeypatch, alias):
    # APP_ENV=prod debe forzar auth firmada igual que production (bug: antes
    # solo 'production' activaba la exigencia y 'prod' quedaba abierto).
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env=alias, required=False),
    )
    client = csrf_client(main.app)
    unsigned = client.get("/api/news")
    assert unsigned.status_code == 401


def test_is_production_accepts_both_aliases():
    prod = Settings(
        _env_file=None,
        app_env="prod",
        research_auth_required=True,
        research_auth_secret=SECRET,
        minio_secret_key="production-minio-secret-not-a-default",
        minio_access_key="production-minio-access-not-a-default",
        database_url=PROD_TEST_DATABASE_URL,
    )
    production = Settings(
        _env_file=None,
        app_env="production",
        research_auth_required=True,
        research_auth_secret=SECRET,
        minio_secret_key="production-minio-secret-not-a-default",
        minio_access_key="production-minio-access-not-a-default",
        database_url=PROD_TEST_DATABASE_URL,
    )
    local = Settings(_env_file=None, app_env="local")
    assert prod.is_production is True
    assert production.is_production is True
    assert local.is_production is False


def test_is_production_is_a_denylist_not_an_allowlist():
    # Regresion: con una allowlist {'production','prod'}, cualquier otro
    # APP_ENV (staging, preprod, prod-eu, o el default 'local' por typo)
    # degradaba en silencio la firma ligada al request, el nonce en Redis y el
    # rate limit. Ahora todo lo que no sea un entorno local conocido es
    # produccion.
    for value, expected in [
        ("production", True),
        ("prod", True),
        ("PRODUCTION", True),
        ("  prod  ", True),
        ("staging", True),
        ("stage", True),
        ("preprod", True),
        ("prod-eu", True),
        ("typo", True),
        ("local", False),
        ("test", False),
        ("ci", False),
        ("dev", False),
        ("development", False),
    ]:
        # Con app_env de produccion hay que aportar las garantias que
        # validate_production_security exige; si no, el Settings ni siquiera
        # se construye y la asercion que importa no llega a ejecutarse.
        kwargs = (
            {
                "research_auth_required": True,
                "research_auth_secret": SECRET,
                "minio_secret_key": "production-minio-secret-not-a-default",
                "minio_access_key": "production-minio-access-not-a-default",
                "database_url": PROD_TEST_DATABASE_URL,
            }
            if expected
            else {}
        )
        settings = Settings(_env_file=None, app_env=value, **kwargs)
        assert settings.is_production is expected, value
        assert settings.is_local_environment is (not expected), value


def test_production_rejects_disabling_signed_auth():
    # Desactivar la auth firmada no solo abre la API: deja la sesion sin
    # tenant_id y con el tenant ausente los guards de aislamiento no inyectan
    # scope, asi que se leerian/escribirian datos de otros tenants.
    with pytest.raises(ValidationError, match="tenant isolation"):
        Settings(
            _env_file=None,
            app_env="production",
            research_auth_required=False,
            research_auth_secret=SECRET,
            minio_secret_key="production-minio-secret-not-a-default",
            minio_access_key="production-minio-access-not-a-default",
            database_url=PROD_TEST_DATABASE_URL,
        )


def test_production_rejects_wildcard_cors_origin():
    # CORS se monta con allow_credentials=True: un origin '*' hace que
    # Starlette refleje el Origin del atacante y sirva respuestas autenticadas.
    with pytest.raises(ValidationError, match=r"CORS_ORIGINS"):
        Settings(
            _env_file=None,
            app_env="production",
            research_auth_required=True,
            research_auth_secret=SECRET,
            minio_secret_key="production-minio-secret-not-a-default",
            minio_access_key="production-minio-access-not-a-default",
            database_url=PROD_TEST_DATABASE_URL,
            cors_origins=["*"],
        )


def test_strict_binding_flag_exists_and_defaults_on():
    # El flag se leia por getattr sobre un Settings que no lo tenia, y como
    # model_config es extra="ignore" la variable de entorno se descartaba en
    # silencio: getattr devolvia False para siempre.
    settings = Settings(_env_file=None, app_env="test")
    assert settings.research_auth_strict_binding is True
    assert auth_module._strict_binding(settings) is True


def test_private_routers_reject_missing_and_invalid_signed_identity(required_auth):
    client = csrf_client(main.app)

    unsigned = client.get("/api/news")
    assert unsigned.status_code == 401
    assert unsigned.json()["detail"] == "Tu sesión no es válida o ha caducado. Vuelve a iniciar sesión."

    invalid_headers = bound_headers(
        SECRET, "tenant-security", "user-security",
        method="GET", path="/api/companies",
    )
    invalid_headers["X-CavaAI-Signature"] = "0" * 64
    invalid = client.get("/api/companies", headers=invalid_headers)
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "La firma de tu sesión no es válida. Vuelve a iniciar sesión."

    assert client.get("/health/live").status_code == 200


def test_worker_session_requires_and_preserves_tenant_and_user():
    init_db()
    suffix = uuid4().hex[:8]
    db = SessionLocal()
    tenant = Tenant(
        external_id=f"worker-{suffix}",
        name="Worker tenant",
        metadata_={"created_by": f"worker-user-{suffix}"},
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    tenant_id = tenant.id
    db.close()

    with pytest.raises(ValueError, match="tenant_id and user_id"):
        dramatiq_app._session(None, None)

    scoped = dramatiq_app._session(tenant_id, f"worker-user-{suffix}")
    try:
        assert scoped.info == {
            "tenant_id": tenant_id,
            "user_id": f"worker-user-{suffix}",
        }
    finally:
        scoped.close()

    assert (tenant_id, f"worker-user-{suffix}") in dramatiq_app.tenant_contexts()

    db = SessionLocal()
    db.execute(delete(Tenant).where(Tenant.id == tenant_id))
    db.commit()
    db.close()


def test_worker_memory_consolidation_cannot_touch_another_tenant():
    init_db()
    suffix = uuid4().hex[:8]
    db = SessionLocal()
    tenants = [
        Tenant(
            external_id=f"memory-{name}-{suffix}",
            name=f"Tenant {name}",
            metadata_={"created_by": f"user-{name}-{suffix}"},
        )
        for name in ("a", "b")
    ]
    db.add_all(tenants)
    db.commit()
    for tenant in tenants:
        db.refresh(tenant)
        db.add_all(
            [
                MemoryItem(
                    tenant_id=tenant.id,
                    scope="portfolio",
                    memory_type="note",
                    content=f"Duplicate memory {suffix}",
                    status="active",
                ),
                MemoryItem(
                    tenant_id=tenant.id,
                    scope="portfolio",
                    memory_type="note",
                    content=f" duplicate   memory {suffix} ",
                    status="active",
                ),
            ]
        )
    db.commit()
    tenant_a_id, tenant_b_id = (tenant.id for tenant in tenants)
    db.close()

    result = dramatiq_app.consolidate_memory.fn(
        tenant_a_id,
        f"user-a-{suffix}",
    )
    assert result["status"] == "ok"
    assert result["duplicates_consolidated"] == 1

    db = SessionLocal()
    rows_a = db.scalars(
        select(MemoryItem)
        .where(MemoryItem.tenant_id == tenant_a_id)
        .execution_options(include_all_tenants=True)
    ).all()
    rows_b = db.scalars(
        select(MemoryItem)
        .where(MemoryItem.tenant_id == tenant_b_id)
        .execution_options(include_all_tenants=True)
    ).all()
    assert sorted(item.status for item in rows_a) == ["active", "consolidated"]
    assert [item.status for item in rows_b] == ["active", "active"]
    db.execute(delete(MemoryItem).where(MemoryItem.tenant_id.in_([tenant_a_id, tenant_b_id])))
    db.execute(delete(Tenant).where(Tenant.id.in_([tenant_a_id, tenant_b_id])))
    db.commit()
    db.close()


def test_financial_replacement_delete_is_tenant_scoped():
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    db = SessionLocal()
    company = db.scalar(select(Company).where(Company.ticker == "MSFT"))
    assert company is not None
    tenants = [
        Tenant(external_id=f"facts-{name}-{suffix}", name=f"Facts {name}")
        for name in ("a", "b")
    ]
    db.add_all(tenants)
    db.commit()
    for tenant in tenants:
        db.refresh(tenant)
        db.add(
            FinancialFact(
                tenant_id=tenant.id,
                company_id=company.id,
                metric=f"tenant_delete_probe_{suffix}",
                value=Decimal("1"),
                unit="USD",
                period=f"FY-{suffix}",
                source_type="SEC",
            )
        )
    db.commit()
    tenant_a_id, tenant_b_id = (tenant.id for tenant in tenants)
    company_id = company.id
    db.close()

    scoped = SessionLocal()
    scoped.info["tenant_id"] = tenant_a_id
    scoped.info["user_id"] = f"user-a-{suffix}"
    company = scoped.get(Company, company_id)
    assert company is not None
    # _replace_sec_data only deletes the facts of the document it is replacing,
    # so the test needs one: the probe rows carry no source_id.
    probe_doc = Document(
        company_id=company_id, title=f"probe {suffix}", source_type="SEC"
    )
    scoped.add(probe_doc)
    scoped.commit()
    for tenant_id in (tenant_a_id, tenant_b_id):
        scoped.execute(
            update(FinancialFact)
            .where(
                FinancialFact.metric == f"tenant_delete_probe_{suffix}",
                FinancialFact.tenant_id == tenant_id,
            )
            .values(source_id=probe_doc.id)
        )
    scoped.commit()
    FinancialIngestionService()._replace_sec_data(scoped, company, probe_doc)
    scoped.commit()
    scoped.close()

    db = SessionLocal()
    probes = db.scalars(
        select(FinancialFact)
        .where(FinancialFact.metric == f"tenant_delete_probe_{suffix}")
        .execution_options(include_all_tenants=True)
    ).all()
    assert [(fact.tenant_id, fact.value) for fact in probes] == [
        (tenant_b_id, Decimal("1.000000"))
    ]
    db.execute(delete(FinancialFact).where(FinancialFact.metric == f"tenant_delete_probe_{suffix}"))
    db.execute(delete(Tenant).where(Tenant.id.in_([tenant_a_id, tenant_b_id])))
    db.commit()
    db.close()


def test_cross_tenant_document_chunk_cannot_be_linked_as_evidence(required_auth):
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    tenant_a_external = f"chunk-a-{suffix}"
    tenant_b_external = f"chunk-b-{suffix}"
    user_a = f"user-a-{suffix}"
    user_b = f"user-b-{suffix}"
    client = csrf_client(main.app)

    claim_response = signed_request(
        client, SECRET, tenant_a_external, user_a, "POST", "/api/memory/claims",
        json_body={"ticker": "MSFT", "statement": f"Private claim {suffix}"},
    )
    assert claim_response.status_code == 200
    claim_id = claim_response.json()["id"]

    # Create tenant B through the real signed bridge, then attach a private chunk.
    tenant_b_claim = signed_request(
        client, SECRET, tenant_b_external, user_b, "POST", "/api/memory/claims",
        json_body={"ticker": "MSFT", "statement": f"Tenant B bootstrap {suffix}"},
    )
    assert tenant_b_claim.status_code == 200

    db = SessionLocal()
    tenant_b = db.scalar(select(Tenant).where(Tenant.external_id == tenant_b_external))
    company = db.scalar(select(Company).where(Company.ticker == "MSFT"))
    assert tenant_b is not None and company is not None
    document = Document(
        tenant_id=tenant_b.id,
        company_id=company.id,
        title=f"Tenant B private document {suffix}",
        source_type="manual",
    )
    db.add(document)
    db.flush()
    chunk = DocumentChunk(
        tenant_id=tenant_b.id,
        document_id=document.id,
        chunk_index=0,
        text=f"Private evidence {suffix}",
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    chunk_id = chunk.id
    document_id = document.id
    tenant_ids = db.scalars(
        select(Tenant.id).where(
            Tenant.external_id.in_([tenant_a_external, tenant_b_external])
        )
    ).all()
    db.close()

    response = signed_request(
        client, SECRET, tenant_a_external, user_a, "POST",
        f"/api/memory/claims/{claim_id}/evidence",
        json_body={
            "document_chunk_id": chunk_id,
            "evidence_type": "supports",
            "summary": "Attempted cross-tenant evidence",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Document chunk not found"

    db = SessionLocal()
    db.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk_id))
    db.execute(delete(Document).where(Document.id == document_id))
    db.execute(delete(Claim).where(Claim.id.in_([claim_id, tenant_b_claim.json()["id"]])))
    db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
    db.commit()
    db.close()


def test_postgres_portfolio_crud_is_tenant_scoped(required_auth):
    suffix = uuid4().hex[:8]
    ticker = f"P{suffix[:5]}".upper()
    tenant_a = f"portfolio-a-{suffix}"
    tenant_b = f"portfolio-b-{suffix}"
    client = csrf_client(main.app)
    payload = {
        "ticker": ticker,
        "action": "buy",
        "quantity": 4,
        "price": 25,
        "trade_date": "2026-01-02",
        "notes": "canonical postgres transaction",
    }

    created = signed_request(
        client, SECRET, tenant_a, f"user-a-{suffix}", "POST",
        "/api/portfolio/transactions", json_body=payload,
    )
    assert created.status_code == 201
    transaction_id = created.json()["id"]

    own = signed_request(
        client, SECRET, tenant_a, f"user-a-{suffix}", "GET", "/api/portfolio/transactions"
    )
    other = signed_request(
        client, SECRET, tenant_b, f"user-b-{suffix}", "GET", "/api/portfolio/transactions"
    )
    assert [row["id"] for row in own.json()["items"]] == [transaction_id]
    assert other.json()["items"] == []

    forbidden_update = signed_request(
        client, SECRET, tenant_b, f"user-b-{suffix}", "PUT",
        f"/api/portfolio/transactions/{transaction_id}",
        json_body={**payload, "quantity": 9},
    )
    assert forbidden_update.status_code == 404

    deleted = signed_request(
        client, SECRET, tenant_a, f"user-a-{suffix}", "DELETE",
        f"/api/portfolio/transactions/{transaction_id}",
    )
    assert deleted.status_code == 204

    db = SessionLocal()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    assert company is not None
    assert db.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .execution_options(include_all_tenants=True)
    ) is None
    db.execute(
        delete(Position)
        .where(Position.company_id == company.id)
        .execution_options(include_all_tenants=True)
    )
    db.execute(delete(Tenant).where(Tenant.external_id.in_([tenant_a, tenant_b])))
    db.delete(company)
    db.commit()
    db.close()


def test_production_rejects_sqlite_database_url():
    with pytest.raises(ValidationError, match="SQLite"):
        Settings(
            _env_file=None,
            app_env="production",
            research_auth_required=True,
            research_auth_secret=SECRET,
            minio_secret_key="production-minio-secret-not-a-default",
            minio_access_key="production-minio-access-not-a-default",
            database_url="sqlite:///./x.db",
        )


def test_production_checks_credentials_for_driver_suffixed_postgres_url():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            app_env="production",
            research_auth_required=True,
            research_auth_secret=SECRET,
            minio_secret_key="production-minio-secret-not-a-default",
            minio_access_key="production-minio-access-not-a-default",
            database_url="postgresql+psycopg://postgres:postgres@db:5432/cavaai",
        )
