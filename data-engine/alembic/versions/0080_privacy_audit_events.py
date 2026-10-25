"""privacy_audit_events: auditoria que sobrevive al borrado de la cuenta.

Aditiva y reversible. No guarda email ni contenido: solo tipo de evento,
identificadores externos y un detalle agregado.
"""
import sqlalchemy as sa

from alembic import op

revision = "0080_privacy_audit_events"
down_revision = "0079_fact_anchors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("retention_tombstoned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_documents_retention_tombstoned_at",
        "documents",
        ["retention_tombstoned_at"],
    )
    op.create_table(
        "privacy_audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("tenant_external_id", sa.String(length=160), nullable=True),
        sa.Column("user_id", sa.String(length=160), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_audit_events_event_type",
        "privacy_audit_events",
        ["event_type"],
    )
    op.create_index(
        "ix_privacy_audit_events_tenant_external_id",
        "privacy_audit_events",
        ["tenant_external_id"],
    )
    op.create_index(
        "ix_privacy_audit_events_user_id",
        "privacy_audit_events",
        ["user_id"],
    )
    op.create_index(
        "ix_privacy_audit_events_created_at",
        "privacy_audit_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_retention_tombstoned_at", table_name="documents")
    op.drop_column("documents", "retention_tombstoned_at")
    op.drop_index("ix_privacy_audit_events_created_at", table_name="privacy_audit_events")
    op.drop_index("ix_privacy_audit_events_user_id", table_name="privacy_audit_events")
    op.drop_index(
        "ix_privacy_audit_events_tenant_external_id",
        table_name="privacy_audit_events",
    )
    op.drop_index("ix_privacy_audit_events_event_type", table_name="privacy_audit_events")
    op.drop_table("privacy_audit_events")
