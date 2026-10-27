"""Purga de datos caducados, idempotente y con tombstone auditable.

Politica (ver docs/PRIVACY_AND_DATA_RETENTION.md):
- documentos financieros: se borra el original, sus chunks y sus vectores al
  cumplir ``FINANCIAL_DOCUMENT_RETENTION_DAYS``. La fila ``documents`` se
  conserva como tombstone (sin URI ni texto) para que los hechos y las tesis
  historicas sigan siendo auditables;
- ``chat_telemetry_events``: se borra la pregunta cruda al cumplir
  ``CHAT_TELEMETRY_RETENTION_DAYS``;
- access requests (Mongo): TTL de Mongo; el scheduler de Postgres no toca
  Mongo. Se documenta como parte de la misma politica.

El scheduler solo lo registra si ``RETENTION_JOB_ENABLED=true``. Con
``RETENTION_DRY_RUN=true`` (default) cuenta candidatos y no modifica nada.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.tenancy import tenant_filters
from app.models import (
    ChatTelemetryEvent,
    ClaimEvidence,
    Document,
    DocumentChunk,
    EvidenceSuggestion,
    KPIExtractionCandidate,
    Tenant,
)
from app.services.document_store import DocumentStore
from app.services.rag import RAGIndex

logger = logging.getLogger(__name__)


class RetentionService:
    def __init__(
        self,
        *,
        store: DocumentStore | None = None,
        index: RAGIndex | None = None,
    ) -> None:
        self.store = store or DocumentStore()
        self.index = index or RAGIndex()

    def run(
        self,
        *,
        dry_run: bool | None = None,
        now: datetime | None = None,
        tenant_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Ejecuta (o simula) la purga de todos los tenants activos."""
        settings = get_settings()
        dry_run = settings.retention_dry_run if dry_run is None else dry_run
        now = now or datetime.now(UTC)
        with SessionLocal() as db:
            statement = select(Tenant).where(Tenant.status == "active")
            if tenant_ids is not None:
                statement = statement.where(Tenant.id.in_(tenant_ids))
            tenants = db.scalars(
                statement.order_by(Tenant.id).execution_options(include_all_tenants=True)
            ).all()
            tenant_rows = [(tenant.id, tenant.external_id) for tenant in tenants]

        totals: dict[str, Any] = {
            "dry_run": bool(dry_run),
            "cutoff_documents": (
                now - timedelta(days=settings.financial_document_retention_days)
            ).isoformat(),
            "cutoff_telemetry": (
                now - timedelta(days=settings.chat_telemetry_retention_days)
            ).isoformat(),
            "tenants": 0,
            "documents_tombstoned": 0,
            "documents_examined": 0,
            "chunks_deleted": 0,
            "telemetry_deleted": 0,
            "external_failures": 0,
            "documents_deferred_evidence": 0,
            "database_failures": 0,
            "access_requests": {
                "engine": "mongodb_ttl",
                "note": "Las solicitudes de acceso no viven en Postgres; Mongo las expira por TTL.",
            },
        }
        for tenant_id, external_id in tenant_rows:
            with SessionLocal() as db:
                db.info["tenant_id"] = tenant_id
                result = self.purge_tenant(
                    db,
                    now=now,
                    dry_run=bool(dry_run),
                    retention_days=settings.financial_document_retention_days,
                    telemetry_days=settings.chat_telemetry_retention_days,
                    limit=settings.retention_batch_limit,
                )
            totals["tenants"] += 1
            for key in (
                "documents_examined",
                "documents_tombstoned",
                "chunks_deleted",
                "telemetry_deleted",
                "external_failures",
                "documents_deferred_evidence",
                "database_failures",
            ):
                totals[key] += result[key]
            logger.info(
                "retention tenant=%s dry_run=%s examined=%s tombstoned=%s "
                "chunks=%s telemetry=%s external_failures=%s",
                external_id,
                dry_run,
                result["documents_examined"],
                result["documents_tombstoned"],
                result["chunks_deleted"],
                result["telemetry_deleted"],
                result["external_failures"],
            )
        logger.info("retention finished dry_run=%s summary=%s", dry_run, totals)
        return totals

    def purge_tenant(
        self,
        db: Session,
        *,
        now: datetime,
        dry_run: bool,
        retention_days: int,
        telemetry_days: int,
        limit: int = 500,
    ) -> dict[str, int]:
        """Purga un tenant ya vinculado a ``db.info['tenant_id']``."""
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None:
            raise ValueError("Tenant context is required for retention")
        document_cutoff = now - timedelta(days=retention_days)
        telemetry_cutoff = now - timedelta(days=telemetry_days)
        result = {
            "documents_examined": 0,
            "documents_tombstoned": 0,
            "chunks_deleted": 0,
            "telemetry_deleted": 0,
            "external_failures": 0,
            "documents_deferred_evidence": 0,
            "database_failures": 0,
        }

        documents = db.scalars(
            select(Document)
            .where(
                *tenant_filters(db, Document),
                Document.retention_tombstoned_at.is_(None),
                or_(
                    Document.published_at < document_cutoff,
                    and_(
                        Document.published_at.is_(None),
                        Document.created_at < document_cutoff,
                    ),
                ),
            )
            .order_by(Document.id)
            .limit(limit)
        ).all()
        for document in documents:
            metadata = dict(document.metadata_ or {})
            result["documents_examined"] += 1
            # Retener las pruebas de claims y candidatos: ni cascada ni
            # eliminar almacenamiento antes de descubrir un FK restrictivo.
            chunk_ids = select(DocumentChunk.id).where(
                *tenant_filters(db, DocumentChunk), DocumentChunk.document_id == document.id,
            )
            referenced = any(
                db.scalar(select(model.id).where(
                    *tenant_filters(db, model), model.document_chunk_id.in_(chunk_ids),
                ).limit(1)) is not None
                for model in (ClaimEvidence, EvidenceSuggestion, KPIExtractionCandidate)
            )
            if referenced:
                result["documents_deferred_evidence"] += 1
                continue
            if dry_run:
                result["documents_tombstoned"] += 1
                continue
            try:
                with db.begin_nested():
                    deleted = int(db.execute(delete(DocumentChunk).where(
                        *tenant_filters(db, DocumentChunk),
                        DocumentChunk.document_id == document.id,
                    )).rowcount)
                    document.storage_uri, uri = None, document.storage_uri
                    document.retention_tombstoned_at = now
                    document.metadata_ = {
                        **metadata,
                        "retention_tombstone": {
                            "tombstoned_at": now.isoformat(),
                            "policy_days": retention_days,
                            "reason": "financial_document_retention",
                        },
                    }
                    # Validar las restricciones antes de efectos externos.
                    db.flush()
                    if uri:
                        self.store.delete(uri)
                    self.index.delete_document_points(tenant_id, document.id)
            except SQLAlchemyError:
                result["database_failures"] += 1
                logger.warning("retention database cleanup deferred document=%s tenant=%s",
                               document.id, tenant_id, exc_info=True)
                continue
            except Exception:  # noqa: BLE001 - rollback del savepoint, se reintenta
                result["external_failures"] += 1
                logger.warning("retention external cleanup failed document=%s tenant=%s",
                               document.id, tenant_id, exc_info=True)
                continue
            result["chunks_deleted"] += deleted
            result["documents_tombstoned"] += 1

        telemetry_filter = and_(
            *tenant_filters(db, ChatTelemetryEvent),
            ChatTelemetryEvent.created_at < telemetry_cutoff,
        )
        if dry_run:
            result["telemetry_deleted"] = int(
                db.scalar(
                    select(func.count())
                    .select_from(ChatTelemetryEvent)
                    .where(telemetry_filter)
                )
                or 0
            )
        else:
            result["telemetry_deleted"] = int(
                db.execute(
                    delete(ChatTelemetryEvent).where(telemetry_filter)
                ).rowcount
            )
            db.commit()
        return result


def run_retention() -> dict[str, Any]:
    """Entrada del scheduler: respeta ``RETENTION_DRY_RUN``."""
    return RetentionService().run()
