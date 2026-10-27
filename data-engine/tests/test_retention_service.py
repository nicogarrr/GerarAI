"""Retencion: tombstone de documentos, telemetria y dry-run sin efectos."""
from datetime import UTC, datetime, timedelta

import pytest
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


def test_referenced_chunk_is_deferred_without_external_deletion(monkeypatch):
    from app.models import Claim, ClaimEvidence

    session, _, company = _db()
    session.execute(__import__('sqlalchemy').text('PRAGMA foreign_keys=ON'))
    old = _old_document(session, company, 'Evidence', 'minio://evidence.pdf')
    chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == old.id))
    claim = Claim(company_id=company.id, statement='Revenue is documented', claim_type='fact', status='active')
    session.add(claim)
    session.flush()
    evidence = ClaimEvidence(claim_id=claim.id, document_id=old.id, document_chunk_id=chunk.id,
                             evidence_type='supports', summary='Revenue', quote='Revenue 123')
    session.add(evidence)
    session.commit()
    service = RetentionService()
    monkeypatch.setattr(service.store, 'delete', lambda uri: pytest.fail('referenced storage must survive'))
    monkeypatch.setattr(service.index, 'delete_document_points', lambda *args: pytest.fail('referenced vectors must survive'))
    result = service.purge_tenant(session, now=NOW, dry_run=False, retention_days=2555, telemetry_days=90)
    assert result['documents_deferred_evidence'] == 1
    assert result['documents_tombstoned'] == result['chunks_deleted'] == 0
    assert session.get(DocumentChunk, chunk.id) is not None
    assert session.get(ClaimEvidence, evidence.id).quote == 'Revenue 123'
    assert session.get(Document, old.id).storage_uri == 'minio://evidence.pdf'


def test_database_delete_failure_does_not_delete_external_objects_or_abort_next_document(monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError

    session, _, company = _db()
    blocked = _old_document(session, company, 'Blocked', 'minio://blocked.pdf')
    other = _old_document(session, company, 'Other', 'minio://other.pdf')
    ids = blocked.id, other.id
    calls = []
    service = RetentionService()
    monkeypatch.setattr(service.store, 'delete', lambda uri: calls.append(uri))
    monkeypatch.setattr(service.index, 'delete_document_points', lambda *args: None)

    def reject_first(execute_state):
        if execute_state.is_delete and execute_state.statement.table.name == 'document_chunks' and not getattr(reject_first, 'done', False):
            reject_first.done = True
            raise IntegrityError('synthetic restrictive FK', {}, Exception('blocked'))

    event.listen(session, 'do_orm_execute', reject_first)
    result = service.purge_tenant(session, now=NOW, dry_run=False, retention_days=2555, telemetry_days=90)
    assert result['database_failures'] == 1
    assert result['documents_tombstoned'] == 1
    assert calls == ['minio://other.pdf']
    assert session.get(Document, ids[0]).storage_uri == 'minio://blocked.pdf'
    assert session.get(Document, ids[1]).storage_uri is None


def test_external_failure_rolls_back_chunks_and_allows_other_document(monkeypatch):
    session, _, company = _db()
    blocked = _old_document(session, company, 'External failure', 'minio://failure.pdf')
    other = _old_document(session, company, 'Other', 'minio://other.pdf')
    ids = blocked.id, other.id
    service = RetentionService()

    def delete_object(uri):
        if uri == 'minio://failure.pdf':
            raise RuntimeError('synthetic external outage')

    monkeypatch.setattr(service.store, 'delete', delete_object)
    monkeypatch.setattr(service.index, 'delete_document_points', lambda *args: None)
    result = service.purge_tenant(session, now=NOW, dry_run=False, retention_days=2555, telemetry_days=90)
    assert result['external_failures'] == 1
    assert result['documents_tombstoned'] == 1
    assert session.get(Document, ids[0]).retention_tombstoned_at is None
    assert session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == ids[0])) is not None
    assert session.get(Document, ids[1]).retention_tombstoned_at is not None


def test_suggestion_reference_is_deferred_in_dry_run_and_real_run(monkeypatch):
    from app.models import EvidenceSuggestion

    session, _, company = _db()
    document = _old_document(session, company, 'Suggestion evidence', 'minio://suggestion.pdf')
    chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document.id))
    session.add(EvidenceSuggestion(company_id=company.id, document_id=document.id,
                                   document_chunk_id=chunk.id, statement='Evidence remains'))
    session.commit()
    service = RetentionService()
    monkeypatch.setattr(service.store, 'delete', lambda *args: pytest.fail('must defer'))
    monkeypatch.setattr(service.index, 'delete_document_points', lambda *args: pytest.fail('must defer'))
    for dry_run in (True, False):
        result = service.purge_tenant(session, now=NOW, dry_run=dry_run, retention_days=2555, telemetry_days=90)
        assert result['documents_deferred_evidence'] == 1
        assert result['documents_tombstoned'] == 0
