"""Comprobaciones fechadas con fuente y notas privadas de compromisos.

Dos tablas NUEVAS (no toca datos existentes): management_promise_checks
(visibles para el tenant) y management_promise_notes (privadas por
owner_user_id). Downgrade = DROP de ambas: solo seguro mientras no haya datos
que conservar; en prod exige backup restorable antes.
"""
import sqlalchemy as sa

from alembic import op

revision = "0079_commitment_checks_notes"
down_revision = "0078_promise_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "management_promise_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column(
            "promise_id",
            sa.Integer(),
            sa.ForeignKey("management_promises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_url", sa.String(1000), nullable=True),
        sa.Column("evidence_date", sa.Date(), nullable=True),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_management_promise_checks_tenant_id", "management_promise_checks", ["tenant_id"])
    op.create_index("ix_management_promise_checks_promise_id", "management_promise_checks", ["promise_id"])
    op.create_table(
        "management_promise_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column(
            "promise_id",
            sa.Integer(),
            sa.ForeignKey("management_promises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_management_promise_notes_tenant_id", "management_promise_notes", ["tenant_id"])
    op.create_index("ix_management_promise_notes_promise_id", "management_promise_notes", ["promise_id"])
    op.create_index("ix_management_promise_notes_owner_user_id", "management_promise_notes", ["owner_user_id"])


def downgrade() -> None:
    op.drop_table("management_promise_notes")
    op.drop_table("management_promise_checks")
