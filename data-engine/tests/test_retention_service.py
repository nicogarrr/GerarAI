"""Retencion: tombstone de documentos, telemetria y dry-run sin efectos."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    ChatTelemetryEvent,
    Company,
    Document,
    DocumentChunk,
    FinancialFact,
    Tenant,
)
from app.services.retention_service import RetentionService

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="retention-test", name="Retention")
    session.add(tenant)
    session.flush()
    session.info["tenant_id"] = tenant.id
    company = Company(
        ticker="RETA",
        name="Retention Co",
        exchange="NASDAQ",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    return session, tenant, company


def _old_document(session, company, title: str, storage_uri: str | None) -> Document:
    document = Document(
        company_id=company.id,
        title=title,
        source_type="SEC",
        storage_uri=storage_uri,
        published_at=NOW - timedelta(days=3000),
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            text=f"texto privado de {title}",
        )
    )
    session.commit()
    return document


def test_retention_tombstones_document_but_keeps_financial_fact(monkeypatch):
    session, tenant, company = _db()
    old = _old_document(session, company, "Viejo", "minio://research/tenant-1/old.pdf")
    fresh = Document(
        company_id=company.id,
        title="Nuevo",
        source_type="SEC",
        storage_uri="minio://research/tenant-1/new.pdf",
        published_at=NOW - timedelta(days=10),
    )
    session.add(fresh)
    session.add(
        FinancialFact(
            company_id=company.id,
            metric="revenue",
            value=100,
            unit="USD",
            period="FY2020",
            source_id=old.id,
            source_type="SEC",
        )
    )
    session.add_all(
        [
            ChatTelemetryEvent(
                question="pregunta vieja",
                route="small_talk",
                created_at=NOW - timedelta(days=120),
            ),
            ChatTelemetryEvent(
                question="pregunta nueva",
                route="small_talk",
                created_at=NOW - timedelta(days=1),
            ),
        ]
    )
    session.commit()
    old_id, fresh_id, tenant_id = old.id, fresh.id, tenant.id

    service = RetentionService()
    deleted_objects: list[str] = []
    deleted_vectors: list[tuple[int, int]] = []
    monkeypatch.setattr(
        service.store, "delete", lambda uri: deleted_objects.append(uri) or True
    )
    monkeypatch.setattr(
        service.index,
        "delete_document_points",
        lambda tenant, document: deleted_vectors.append((tenant, document)) or 1,
    )

    result = service.purge_tenant(
        session,
        now=NOW,
        dry_run=False,
        retention_days=2555,
        telemetry_days=90,
    )

    assert result["documents_examined"] == 1
    assert result["documents_tombstoned"] == 1
    assert result["chunks_deleted"] == 1
    assert result["telemetry_deleted"] == 1
    assert deleted_objects == ["minio://research/tenant-1/old.pdf"]
    assert deleted_vectors == [(tenant_id, old_id)]

    tombstone = session.get(Document, old_id)
    assert tombstone is not None
    assert tombstone.storage_uri is None
    assert tombstone.retention_tombstoned_at is not None
    assert tombstone.title == "Viejo"
    assert tombstone.metadata_["retention_tombstone"]["reason"] == (
        "financial_document_retention"
    )
    assert session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == old_id)
    ).all() == []
    assert session.scalars(
        select(FinancialFact).where(FinancialFact.source_id == old_id)
    ).all() != []
    assert session.get(Document, fresh_id).storage_uri == (
        "minio://research/tenant-1/new.pdf"
    )
    assert session.scalars(select(ChatTelemetryEvent)).all() != []
    assert [row.question for row in session.scalars(select(ChatTelemetryEvent))] == [
        "pregunta nueva"
    ]

    # Segunda pasada: el tombstone no se vuelve a procesar.
    again = service.purge_tenant(
        session,
        now=NOW,
        dry_run=False,
        retention_days=2555,
        telemetry_days=90,
    )
    assert again["documents_examined"] == 0
    assert again["telemetry_deleted"] == 0


def test_retention_telemetry_counts_and_deletes_only_active_tenant():
    session, tenant, _ = _db()
    session.info["tenant_id"] = tenant.id
    session.add(
        ChatTelemetryEvent(
            question="pregunta A",
            route="small_talk",
            created_at=NOW - timedelta(days=120),
        )
    )
    tenant_b = Tenant(external_id="retention-other", name="Other")
    session.add(tenant_b)
    session.flush()
    session.info["tenant_id"] = tenant_b.id
    session.add(
        ChatTelemetryEvent(
            question="pregunta B",
            route="small_talk",
            created_at=NOW - timedelta(days=120),
        )
    )
    session.commit()

    service = RetentionService()
    session.info["tenant_id"] = tenant.id
    dry = service.purge_tenant(
        session,
        now=NOW,
        dry_run=True,
        retention_days=2555,
        telemetry_days=90,
    )
    assert dry["telemetry_deleted"] == 1

    real = service.purge_tenant(
        session,
        now=NOW,
        dry_run=False,
        retention_days=2555,
        telemetry_days=90,
    )
    assert real["telemetry_deleted"] == 1

    session.info["tenant_id"] = tenant_b.id
    assert [row.question for row in session.scalars(select(ChatTelemetryEvent))] == [
        "pregunta B"
    ]


def test_retention_dry_run_counts_without_deleting(monkeypatch):
    session, _, company = _db()
    old = _old_document(session, company, "Viejo dry", "minio://research/tenant-1/x.pdf")
    old_id = old.id
    session.add(
        ChatTelemetryEvent(
            question="pregunta vieja",
            route="small_talk",
            created_at=NOW - timedelta(days=120),
        )
    )
    session.commit()

    service = RetentionService()
    monkeypatch.setattr(
        service.store,
        "delete",
        lambda uri: (_ for _ in ()).throw(AssertionError("dry-run no borra objetos")),
    )
    monkeypatch.setattr(
        service.index,
        "delete_document_points",
        lambda tenant, document: (_ for _ in ()).throw(
            AssertionError("dry-run no borra vectores")
        ),
    )

    result = service.purge_tenant(
        session,
        now=NOW,
        dry_run=True,
        retention_days=2555,
        telemetry_days=90,
    )

    assert result["documents_examined"] == 1
    assert result["documents_tombstoned"] == 1
    assert result["telemetry_deleted"] == 1
    assert session.get(Document, old_id).storage_uri == (
        "minio://research/tenant-1/x.pdf"
    )
    assert session.scalars(select(DocumentChunk)).all() != []
    assert [row.question for row in session.scalars(select(ChatTelemetryEvent))] == [
        "pregunta vieja"
    ]
