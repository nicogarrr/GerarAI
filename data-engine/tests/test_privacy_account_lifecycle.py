"""Export completo y borrado de cuenta: aislamiento de tenant e idempotencia."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import (
    AlertSubscription,
    Company,
    Document,
    KnowledgeDocument,
    Portfolio,
    PrivacyAuditEvent,
    Tenant,
    ThesisVersion,
    WatchItem,
)
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "privacy-test-secret-with-at-least-32-characters"


def _client(monkeypatch) -> TestClient:
    init_db()
    seed()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="local"),
    )
    return TestClient(main.app)


def _tenant(db, suffix: str, prefix: str) -> tuple[Tenant, Company]:
    tenant = Tenant(external_id=f"{prefix}-{suffix}", name=f"Tenant {prefix}")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    company = db.scalar(
        select(Company).where(Company.ticker == "MSFT").limit(1)
    )
    assert company is not None
    return tenant, company


def _seed_tenant(db, suffix: str, prefix: str, symbol: str) -> tuple[int, int]:
    tenant, company = _tenant(db, suffix, prefix)
    portfolio = Portfolio(name=f"Cartera {symbol}")
    db.add(portfolio)
    db.flush()
    db.add(WatchItem(symbol=symbol, company=symbol))
    db.add(
        ThesisVersion(
            company_id=company.id,
            version=1,
            status="draft",
            thesis_markdown=f"Tesis privada {symbol}",
            executive_summary=f"Resumen {symbol}",
        )
    )
    db.add(
        Document(
            company_id=company.id,
            title=f"Documento {symbol}",
            source_type="SEC",
            storage_uri=f"minio://research/tenant-{tenant.id}/MSFT/filing/{symbol}.pdf",
            metadata_={"private": symbol},
        )
    )
    db.add(
        KnowledgeDocument(
            title=f"Nota {symbol}",
            document_type="personal_note",
            language="es",
            storage_uri=f"minio://research/tenant-{tenant.id}/KNOWLEDGE/note/{symbol}.txt",
            checksum=uuid4().hex,
        )
    )
    db.add(
        AlertSubscription(
            user_id=f"user-{prefix}",
            event_type="new_filing",
            enabled=True,
            chat_id=f"chat-{prefix}",
        )
    )
    db.commit()
    return tenant.id, portfolio.id


def test_export_scoped_to_signed_tenant_and_omits_internals(monkeypatch):
    client = _client(monkeypatch)
    suffix = uuid4().hex[:8]
    tenant_a = f"privacy-a-{suffix}"
    tenant_b = f"privacy-b-{suffix}"
    db = SessionLocal()
    tenant_a_id, _ = _seed_tenant(db, suffix, "privacy-a", "AAA")
    _seed_tenant(db, suffix, "privacy-b", "BBB")
    db.close()

    response = signed_request(
        client, SECRET, tenant_a, f"user-a-{suffix}", "GET", "/api/privacy/export"
    )
    assert response.status_code == 200
    payload = response.json()

    watch_symbols = {row["symbol"] for row in payload["watchlist"]}
    assert "AAA" in watch_symbols
    assert "BBB" not in watch_symbols
    assert {row["executive_summary"] for row in payload["thesis_versions"]} == {
        "Resumen AAA"
    }
    assert payload["documents"][0]["title"] == "Documento AAA"
    assert "storage_uri" not in payload["documents"][0]
    assert "storage_uri" not in payload["knowledge_documents"][0]
    assert "chat_id" not in payload["alert_subscriptions"][0]
    assert payload["profile"]["tenant"] == "Tenant privacy-a"

    db = SessionLocal()
    assert db.get(Tenant, tenant_a_id) is not None
    db.close()


def test_delete_account_is_compensated_idempotent_and_audited(monkeypatch):
    client = _client(monkeypatch)
    suffix = uuid4().hex[:8]
    tenant_a = f"delete-a-{suffix}"
    tenant_b = f"delete-b-{suffix}"
    db = SessionLocal()
    tenant_a_id, _ = _seed_tenant(db, suffix, "delete-a", "DELA")
    tenant_b_id, _ = _seed_tenant(db, suffix, "delete-b", "DELB")
    db.close()

    external: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "app.services.privacy_service.DocumentStore.delete",
        lambda _self, uri: True,
    )
    monkeypatch.setattr(
        "app.services.privacy_service.DocumentStore.delete_tenant_prefix",
        lambda _self, tenant_id: external.append(("objects", tenant_id)) or 2,
    )
    monkeypatch.setattr(
        "app.services.privacy_service.RAGIndex.delete_tenant_points",
        lambda _self, tenant_id: external.append(("vectors", tenant_id)) or 1,
    )
    monkeypatch.setattr(
        "app.services.privacy_service.PrivacyService._delete_knowledge_vectors",
        staticmethod(lambda tenant_id: 0),
    )

    wrong = signed_request(
        client,
        SECRET,
        tenant_a,
        f"user-a-{suffix}",
        "DELETE",
        "/api/privacy/account",
        json_body={"confirmation": "no"},
    )
    assert wrong.status_code == 400
    db = SessionLocal()
    assert db.get(Tenant, tenant_a_id) is not None
    db.close()

    deleted = signed_request(
        client,
        SECRET,
        tenant_a,
        f"user-a-{suffix}",
        "DELETE",
        "/api/privacy/account",
        json_body={"confirmation": "ELIMINAR MI CUENTA"},
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["status"] == "deleted"
    assert body["already_deleted"] is False
    assert external == [("objects", tenant_a_id), ("vectors", tenant_a_id)]

    # Reintento: idempotente y sin tocar al otro tenant.
    again = signed_request(
        client,
        SECRET,
        tenant_a,
        f"user-a-{suffix}",
        "DELETE",
        "/api/privacy/account",
        json_body={"confirmation": "ELIMINAR MI CUENTA"},
    )
    assert again.status_code == 200
    assert again.json()["already_deleted"] is True

    db = SessionLocal()
    assert db.get(Tenant, tenant_a_id) is None
    assert db.get(Tenant, tenant_b_id) is not None
    assert db.scalars(
        select(WatchItem)
        .where(WatchItem.symbol == "DELA")
        .execution_options(include_all_tenants=True)
    ).all() == []
    assert db.scalars(
        select(WatchItem)
        .where(WatchItem.symbol == "DELB")
        .execution_options(include_all_tenants=True)
    ).all() != []
    assert db.scalars(
        select(Document.title)
        .where(Document.title == "Documento DELB")
        .execution_options(include_all_tenants=True)
    ).all() == ["Documento DELB"]
    audit = db.scalars(
        select(PrivacyAuditEvent).where(
            PrivacyAuditEvent.event_type == "account.delete"
        )
    ).all()
    assert any(event.tenant_external_id == tenant_a for event in audit)
    db.close()

def test_knowledge_store_delete_tenant_is_idempotent():
    from types import SimpleNamespace

    from app.services.knowledge_rag.store import KnowledgeStore

    class FakeClient:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, int]] = []

        def get_collections(self):
            return SimpleNamespace(
                collections=[SimpleNamespace(name="knowledge_rag_v2")]
            )

        def delete(self, collection, *, points_selector, wait):
            self.deleted.append((collection, 1))

    client = FakeClient()
    store = KnowledgeStore(client, "knowledge_rag_v2")
    assert store.delete_tenant(7) == 1
    assert client.deleted == [("knowledge_rag_v2", 1)]

    missing = KnowledgeStore(client, "otra_coleccion")
    assert missing.delete_tenant(7) == 0
