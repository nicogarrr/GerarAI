"""Ciclo de vida de la cuenta: export completo y borrado compensado.

El principal firmado resuelve el tenant; ningun identificador del cliente
decide que se exporta o se borra. El borrado no publica exito hasta que la
base de datos, el almacen de objetos/vectores y la cache LLM del tenant estan
limpios, y deja un tombstone por external_id que impide recrear el tenant.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.tenancy import tenant_filters
from app.llm.response_cache import purge_llm_response_cache
from app.models import (
    AlertRule,
    AlertSubscription,
    BudgetUsage,
    CashBalance,
    CashDailySnapshot,
    ChatSession,
    ChatTelemetryEvent,
    Claim,
    ClaimEvidence,
    CustomMetricDefinition,
    DcaAlertOverride,
    DcaEvaluationRun,
    DcaSignalState,
    DecisionJournalEntry,
    DecisionLesson,
    Document,
    ExpectationReview,
    FxConversion,
    IbkrRawRow,
    InvestmentCaseStudy,
    InvestmentPlan,
    InvestmentPrinciple,
    KnowledgeCollection,
    KnowledgeDocument,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeRagParent,
    KnowledgeRagSource,
    MemoryItem,
    PaperTrade,
    PlanContribution,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    PositionDailySnapshot,
    PrivacyAuditEvent,
    ResearchAlert,
    ResearchReview,
    ResearchSession,
    SavedScreen,
    TaxReport,
    Tenant,
    TenantLLMSettings,
    ThesisChange,
    ThesisDiff,
    ThesisSection,
    ThesisVersion,
    Transaction,
    WatchItem,
    WorkflowRun,
    WorkflowStepRun,
)
from app.services.document_store import DocumentStore
from app.services.rag import RAGIndex

logger = logging.getLogger(__name__)


class PrivacyConfirmationError(ValueError):
    """La frase de confirmacion no coincide; nunca se toca ningun dato."""


class PrivacyPartialFailure(RuntimeError):
    """La limpieza externa no termino: no se publica un 200 ni se borra SQL."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__("External privacy cleanup did not complete")
        self.failures = tuple(failures)

SENSITIVE_COLUMNS = {
    "tenant_id",
    "storage_uri",
    "token_hash",
    "chat_id",
    "qdrant_point_id",
    "password",
    "secret",
    "api_key",
    "api_key_ciphertext",
    "api_key_last4",
    "token_ciphertext",
    "password_hash",
    "refresh_token",
    "access_token",
}

# Categorias pedidas por privacidad. No se incluyen las tablas derivadas del
# mercado (hechos, metricas ni chunks crudos) porque no son datos aportados por
# el usuario y multiplicarian el tamano sin valor de portabilidad.
EXPORT_TABLES: tuple[tuple[str, Any], ...] = (
    ("ibkr_raw_rows", IbkrRawRow),
    ("fx_conversions", FxConversion),
    ("dca_signal_states", DcaSignalState),
    ("dca_evaluation_runs", DcaEvaluationRun),
    ("tenant_llm_settings", TenantLLMSettings),
    ("budget_usage", BudgetUsage),
    ("workflow_runs", WorkflowRun),
    ("workflow_step_runs", WorkflowStepRun),
    ("portfolios", Portfolio),
    ("positions", Position),
    ("transactions", Transaction),
    ("cash_balances", CashBalance),
    ("portfolio_snapshots", PortfolioDailySnapshot),
    ("position_snapshots", PositionDailySnapshot),
    ("cash_snapshots", CashDailySnapshot),
    ("watchlist", WatchItem),
    ("dca_alert_overrides", DcaAlertOverride),
    ("thesis_versions", ThesisVersion),
    ("thesis_sections", ThesisSection),
    ("thesis_diffs", ThesisDiff),
    ("thesis_changes", ThesisChange),
    ("claims", Claim),
    ("claim_evidence", ClaimEvidence),
    ("alert_rules", AlertRule),
    ("alerts", ResearchAlert),
    ("alert_subscriptions", AlertSubscription),
    ("knowledge_collections", KnowledgeCollection),
    ("knowledge_documents", KnowledgeDocument),
    ("knowledge_rag_sources", KnowledgeRagSource),
    ("knowledge_rag_parents", KnowledgeRagParent),
    ("investment_principles", InvestmentPrinciple),
    ("investment_case_studies", InvestmentCaseStudy),
    ("knowledge_graph_nodes", KnowledgeGraphNode),
    ("knowledge_graph_edges", KnowledgeGraphEdge),
    ("memory_items", MemoryItem),
    ("research_sessions", ResearchSession),
    ("chat_sessions", ChatSession),
    ("documents", Document),
    ("investment_plans", InvestmentPlan),
    ("plan_contributions", PlanContribution),
    ("tax_reports", TaxReport),
    ("decision_journal_entries", DecisionJournalEntry),
    ("decision_lessons", DecisionLesson),
    ("expectation_reviews", ExpectationReview),
    ("research_reviews", ResearchReview),
    ("paper_trades", PaperTrade),
    ("chat_telemetry_events", ChatTelemetryEvent),
    ("saved_screens", SavedScreen),
    ("custom_metric_definitions", CustomMetricDefinition),
)

DELETE_CONFIRMATION = "ELIMINAR MI CUENTA"


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _json_value(item) for key, item in value.items()
            if str(key).lower() not in SENSITIVE_COLUMNS
            and not any(part in str(key).lower() for part in ("ciphertext", "password", "secret", "api_key", "access_token", "refresh_token"))
        }
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _dump_row(row: Any) -> dict[str, Any]:
    """Serializa columnas mapeadas, no atributos homonimos de SQLAlchemy.

    ``mapped_column("metadata", ...)`` expone la columna como ``metadata``
    pero el atributo ORM es ``metadata_``: leer ``row.metadata`` devolveria
    ``Base.metadata`` (un MetaData no serializable). Se resuelve la propiedad
    real via mapper.
    """
    mapper = row.__mapper__
    data: dict[str, Any] = {}
    for column in row.__table__.columns:
        attribute = mapper.get_property_by_column(column).key
        if column.name in SENSITIVE_COLUMNS or attribute in SENSITIVE_COLUMNS:
            continue
        data[column.name] = _json_value(getattr(row, attribute))
    return data


class PrivacyService:
    def export_account(self, db: Session) -> dict[str, Any]:
        """Exporta los datos del tenant de la sesion, nunca de otro."""
        tenant_id = db.info.get("tenant_id")
        user_id = db.info.get("user_id")
        if tenant_id is None:
            raise ValueError("Tenant context is required to export the account")
        tenant = db.get(Tenant, tenant_id)
        metadata = dict((tenant.metadata_ if tenant else {}) or {})
        # `created_by` es un id interno de autenticacion, no un dato portable.
        metadata.pop("created_by", None)
        data: dict[str, Any] = {
            "schema_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "profile": {
                "tenant": tenant.name if tenant else None,
                "status": tenant.status if tenant else None,
                "created_at": (
                    tenant.created_at.isoformat()
                    if tenant and tenant.created_at
                    else None
                ),
                "metadata": _json_value(metadata),
            },
            "settings": {
                "tax_declarant": _json_value(metadata.get("tax_declarant")),
                "note": (
                    "El plan y sus aportaciones viajan en investment_plans y "
                    "plan_contributions."
                ),
            },
        }
        for key, model in EXPORT_TABLES:
            rows = db.scalars(
                select(model)
                .where(*tenant_filters(db, model))
                .order_by(model.id)
            ).all()
            data[key] = [_dump_row(row) for row in rows]
        data["knowledge_documents"] = self._with_chunk_counts(
            db, data["knowledge_documents"], KnowledgeDocument, "knowledge_document_id"
        )
        data["documents"] = self._with_chunk_counts(
            db, data["documents"], Document, "document_id"
        )
        self._audit(
            "account.export",
            tenant_id=tenant_id,
            user_id=user_id,
            detail={
                "tables": len(EXPORT_TABLES),
                "rows": sum(len(data[key]) for key, _ in EXPORT_TABLES),
            },
        )
        return data

    @staticmethod
    def _with_chunk_counts(
        db: Session, rows: list[dict], model: Any, fk_name: str
    ) -> list[dict]:
        if not rows:
            return rows
        from app.models import DocumentChunk, KnowledgeChunk

        chunk_model = KnowledgeChunk if model is KnowledgeDocument else DocumentChunk
        fk = getattr(chunk_model, fk_name)
        counts = dict(
            db.execute(
                select(fk, func.count())
                .where(*tenant_filters(db, chunk_model))
                .group_by(fk)
            ).all()
        )
        return [
            {**row, "chunk_count": int(counts.get(row.get("id"), 0))}
            for row in rows
        ]

    def delete_account(
        self,
        db: Session,
        *,
        confirmation: str,
        reason: str = "user_request",
    ) -> dict[str, Any]:
        """Borra el tenant de la sesion de forma compensada e idempotente.

        Orden: limpieza externa (objetos, vectores, cache LLM) -> transaccion
        unica de borrado en Postgres -> auditoria. Si la limpieza externa falla
        no se toca Postgres y se lanza ``PrivacyPartialFailure``: nunca se
        publica un exito parcial. El tenant NO se elimina: queda como tombstone
        ``deleted`` por ``external_id`` para que ``get_db`` no lo recree.
        """
        if confirmation.strip().upper() != DELETE_CONFIRMATION:
            raise PrivacyConfirmationError(
                "La confirmación no coincide con la frase exigida."
            )
        tenant_id = db.info.get("tenant_id")
        user_id = db.info.get("user_id")
        if tenant_id is None:
            raise ValueError("Tenant context is required to delete the account")

        tenant = db.get(Tenant, tenant_id)
        external_id = tenant.external_id if tenant else None
        if tenant is None:
            # Idempotencia: un reintento tras un borrado correcto no falla.
            self._audit(
                "account.delete",
                tenant_id=None,
                user_id=user_id,
                detail={"status": "already_deleted", "reason": reason},
                tenant_external_id=external_id,
            )
            return self._deleted_result(already_deleted=True)

        if tenant.status == "deleted":
            # Tombstone: la cuenta ya se borro y la fila se conserva para que
            # get_db rechace cualquier recreacion del mismo external_id.
            self._audit(
                "account.delete",
                tenant_id=None,
                user_id=user_id,
                detail={"status": "already_deleted", "reason": reason},
                tenant_external_id=external_id,
            )
            return self._deleted_result(already_deleted=True)

        # 1) Externo primero. Si algo falla, Postgres sigue intacto y se puede
        # reintentar sin perder la referencia a los objetos. Se borran tanto
        # las URIs registradas (pueden apuntar a un bucket anterior) como el
        # prefijo actual del tenant. Hay dos indices Qdrant: el de documentos
        # financieros y el de la biblioteca de conocimiento; ambos se limpian.
        store = DocumentStore()
        storage_uris: set[str] = set()
        for model in (Document, KnowledgeDocument):
            storage_uris.update(
                uri
                for uri in db.scalars(
                    select(model.storage_uri)
                    .where(model.storage_uri.is_not(None), *tenant_filters(db, model))
                ).all()
                if uri
            )
        failures: list[str] = []
        objects_removed = 0
        for uri in sorted(storage_uris):
            try:
                objects_removed += int(bool(store.delete(uri)))
            except Exception:  # noqa: BLE001 - se agrega y se falla cerrado
                failures.append("object_storage")
                logger.warning("privacy storage delete failed", exc_info=True)
        try:
            objects_removed += store.delete_tenant_prefix(tenant_id)
        except Exception:  # noqa: BLE001
            failures.append("object_storage_prefix")
            logger.warning("privacy storage prefix delete failed", exc_info=True)
        try:
            RAGIndex().delete_tenant_points(tenant_id)
        except Exception:  # noqa: BLE001
            failures.append("document_vectors")
            logger.warning("privacy document vector delete failed", exc_info=True)
        try:
            knowledge_collections_cleared = self._delete_knowledge_vectors(tenant_id)
        except Exception:  # noqa: BLE001
            failures.append("knowledge_vectors")
            knowledge_collections_cleared = 0
            logger.warning("privacy knowledge vector delete failed", exc_info=True)
        try:
            llm_cache_entries_purged = purge_llm_response_cache(
                tenant_id=external_id
            )
        except Exception:  # noqa: BLE001
            failures.append("llm_cache")
            llm_cache_entries_purged = 0
            logger.warning("privacy LLM cache purge failed", exc_info=True)
        if failures:
            raise PrivacyPartialFailure(sorted(set(failures)))

        # 2) Postgres en una sola transaccion. Orden inverso a las
        # dependencias: hijos antes que padres. La fila ``tenants`` no se
        # borra: se convierte en tombstone sin nombre ni metadata.
        counts: dict[str, int] = {}
        tenant_tables = [
            table
            for table in reversed(Base.metadata.sorted_tables)
            if "tenant_id" in table.columns and table.name != "tenants"
        ]
        with engine.begin() as connection:
            previous = connection.execute(
                select(func.count())
                .select_from(PrivacyAuditEvent.__table__)
                .where(
                    PrivacyAuditEvent.__table__.c.event_type == "account.delete",
                    PrivacyAuditEvent.__table__.c.tenant_external_id == external_id,
                )
            ).scalar_one()
            for table in tenant_tables:
                where = table.c.tenant_id == tenant_id
                count = connection.execute(
                    select(func.count()).select_from(table).where(where)
                ).scalar_one()
                if count:
                    counts[table.name] = int(count)
                    connection.execute(table.delete().where(where))
            tombstoned = connection.execute(
                Tenant.__table__.update()
                .where(Tenant.__table__.c.id == tenant_id)
                .values(status="deleted", name="Cuenta eliminada", metadata={})
            ).rowcount
            already_deleted = tombstoned == 0 or (bool(previous) and not counts)
            connection.execute(
                PrivacyAuditEvent.__table__.insert().values(
                    event_type="account.delete",
                    tenant_external_id=external_id,
                    user_id=user_id,
                    detail={
                        "status": "already_deleted" if already_deleted else "deleted",
                        "reason": reason,
                        "tables": counts,
                        "external_objects_removed": objects_removed,
                        "knowledge_vector_collections_cleared": (
                            knowledge_collections_cleared
                        ),
                        "llm_cache_entries_purged": llm_cache_entries_purged,
                    },
                    created_at=datetime.now(UTC),
                )
            )

        logger.info(
            "account deleted tenant_external=%s tables=%s objects=%s cache=%s already=%s",
            external_id,
            len(counts),
            objects_removed,
            llm_cache_entries_purged,
            already_deleted,
        )
        return self._deleted_result(
            already_deleted=already_deleted,
            tables=counts,
            external_objects_removed=objects_removed,
            knowledge_collections_cleared=knowledge_collections_cleared,
            llm_cache_entries_purged=llm_cache_entries_purged,
        )

    @staticmethod
    def _deleted_result(
        *,
        already_deleted: bool,
        tables: dict[str, int] | None = None,
        external_objects_removed: int = 0,
        knowledge_collections_cleared: int = 0,
        llm_cache_entries_purged: int = 0,
    ) -> dict[str, Any]:
        return {
            "status": "deleted",
            "already_deleted": already_deleted,
            "tables": tables or {},
            "external_objects_removed": external_objects_removed,
            "knowledge_vector_collections_cleared": (
                knowledge_collections_cleared
            ),
            "llm_cache_entries_purged": llm_cache_entries_purged,
        }

    @staticmethod
    def _delete_knowledge_vectors(tenant_id: int) -> int:
        """Limpia la coleccion Qdrant del RAG de conocimiento, si existe."""
        from qdrant_client import QdrantClient

        from app.services.knowledge_rag.store import KnowledgeStore

        settings = get_settings()
        store = KnowledgeStore(
            QdrantClient(url=settings.qdrant_url),
            settings.knowledge_rag_collection,
            dims=settings.knowledge_rag_dense_dims,
        )
        return store.delete_tenant(tenant_id)

    @staticmethod
    def _audit(
        event_type: str,
        *,
        tenant_id: int | None,
        user_id: str | None,
        detail: dict[str, Any],
        tenant_external_id: str | None = None,
    ) -> None:
        if tenant_external_id is None and tenant_id is not None:
            with SessionLocal() as db:
                tenant = db.get(Tenant, tenant_id)
                tenant_external_id = tenant.external_id if tenant else None
        with SessionLocal() as db:
            db.add(
                PrivacyAuditEvent(
                    event_type=event_type,
                    tenant_external_id=tenant_external_id,
                    user_id=user_id,
                    detail=detail,
                )
            )
            db.commit()
